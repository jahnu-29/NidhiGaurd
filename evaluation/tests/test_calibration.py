"""
V2.5 calibration / operating-point tests.

* Every threshold and Top-K table is recomputed INDEPENDENTLY with the csv module and plain loops (no pandas, no V2.2 metrics),
  and compared with the committed results.
* Hand-computed synthetic fixtures pin the confusion-matrix arithmetic, boundary inclusivity, tie-breaking and tie ranges.
* Leakage is checked by source, runtime file access, and behaviour on a bare input directory.
* Frozen-file checks compare with hashes recorded outside this stage; the "unchanged since the V2.5 run" check compares with the
  manifest written by the V2.5 run, so it detects later edits but cannot by itself prove equality with an earlier git commit.
"""
import ast
import csv
import hashlib
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from unittest import mock

import pandas as pd
import pytest

from evaluation import evaluation_metrics as M
from evaluation.ablation import run_ablation as RA
from evaluation.baselines import run_baselines as RB
from evaluation.calibration import run_calibration as RC

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(EVAL_DIR)
CAL_DIR = os.path.join(EVAL_DIR, "calibration")
OUT_FILES = ("calibration_predictions.csv", "calibration_metadata.json", "calibration_results.json", "calibration_report.md")
PLOTS = ("score_distribution.svg", "queue_size_vs_recall.svg", "queue_size_vs_precision.svg", "threshold_vs_queued.svg", "threshold_vs_precision_recall.svg")
ALL_FILES = OUT_FILES + tuple(os.path.join("plots", p) for p in PLOTS)

FORBIDDEN = ["ground_truth", "evaluation_labels", "anomaly_signals", "scenario_type", "difficulty", "injected_signals", "group_id",
             "adversarial_subtype", "rationale", "y_true", "evaluation_metrics", "engine_input", "ablation", "baseline", "intelligence"]
STAGE1 = ("v1_risk_level", "band_of", "load_scores", "build_calibration_predictions")


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _tokens(tree):
    doc = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            doc.add(id(n.body[0].value))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out += [n.module or ""] + [a.name for a in n.names]
        elif isinstance(n, (ast.Name,)):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
        elif isinstance(n, ast.arg):
            out.append(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc:
            out.append(n.value)
    return out


def _hits(toks):
    return sorted({f for f in FORBIDDEN for t in toks if f.lower() in str(t).lower()})


def _copy_eval(tmp_path, name):
    dst = tmp_path / name / "evaluation"
    shutil.copytree(EVAL_DIR, dst, ignore=shutil.ignore_patterns("__pycache__", "calibration"))
    return str(dst)


def _tree_hashes(root, skip=("calibration", "__pycache__")):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = _sha(p)
    return out


@pytest.fixture(scope="module")
def results():
    return json.load(open(os.path.join(CAL_DIR, "calibration_results.json"), encoding="utf-8"))


def _read_inputs():
    """Pure-python read of the frozen scores and labels."""
    score = {r["project_id"]: float(r["risk_score"]) for r in csv.DictReader(open(os.path.join(EVAL_DIR, "evaluation_predictions.csv"), encoding="utf-8", newline=""))}
    lab = {r["project_id"]: r for r in csv.DictReader(open(os.path.join(EVAL_DIR, "evaluation_labels.csv"), encoding="utf-8", newline=""))}
    return score, lab


# --------------------------------------------------------------------------- #
# independent recomputation of the committed results
# --------------------------------------------------------------------------- #
def test_150_projects_and_label_counts(results):
    score, lab = _read_inputs()
    assert len(score) == len(lab) == 150 and set(score) == set(lab)
    d = results["dataset"]
    assert (d["projects"], d["anomalous"], d["normal"], d["adversarial_normal"]) == (150, 49, 101, 41)
    assert sum(1 for r in lab.values() if r["ground_truth_label"] == "ANOMALOUS") == 49
    assert sum(1 for r in lab.values() if r["scenario_type"] == "ADVERSARIAL_NORMAL") == 41


def test_thresholds_and_capacities_are_exactly_the_predefined_lists(results):
    assert RC.THRESHOLDS == (20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0) and RC.CAPACITIES == (5, 10, 20, 25, 30, 40, 50)
    assert [t["threshold"] for t in results["threshold_table"]] == [20, 25, 30, 35, 40, 45, 50]
    assert [k["capacity"] for k in results["top_k_table"]] == [5, 10, 20, 25, 30, 40, 50]
    assert 30.0 in RC.THRESHOLDS and RC.V1_NATIVE_QUEUE_THRESHOLD == 30.0 and RC.V2_2_EVALUATION_THRESHOLD == 40.0


def test_threshold_table_matches_independent_calculation(results):
    score, lab = _read_inputs()
    anom = {p for p, r in lab.items() if r["ground_truth_label"] == "ANOMALOUS"}
    adv = {p for p, r in lab.items() if r["scenario_type"] == "ADVERSARIAL_NORMAL"}
    n = len(score)
    for row in results["threshold_table"]:
        t = row["threshold"]
        queued = {p for p, s in score.items() if s >= t}
        tp, fp = len(queued & anom), len(queued - anom)
        fn, tn = len(anom - queued), (n - len(anom)) - len(queued - anom)
        assert (row["projects_queued"], row["tp"], row["fp"], row["fn"], row["tn"]) == (len(queued), tp, fp, fn, tn)
        assert tp + fp + fn + tn == n and tp + fn == 49 and fp + tn == 101
        assert row["pct_of_dataset"] == pytest.approx(len(queued) / n, abs=1e-6)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / 49
        f1 = 2 * prec * rec / (prec + rec) if prec is not None and prec + rec else None
        assert row["recall"] == pytest.approx(rec, abs=1e-6)
        assert (row["precision"] is None) == (prec is None) and (prec is None or row["precision"] == pytest.approx(prec, abs=1e-6))
        assert (row["f1"] is None) == (f1 is None) and (f1 is None or row["f1"] == pytest.approx(f1, abs=1e-6))
        assert row["anomalous_captured"] == tp and row["normal_incorrectly_queued"] == fp
        assert row["adversarial_queued"] == len(queued & adv) and row["adversarial_ids"] == sorted(queued & adv)
        assert row["adversarial_queued_pct"] == pytest.approx(len(queued & adv) / 41, abs=1e-6)
        assert row["plain_normal_queued"] == len([p for p in queued if lab[p]["scenario_type"] == "NORMAL"])
        for sc, cnt in row["scenario_captured"].items():
            assert cnt == len([p for p in queued if lab[p]["scenario_type"] == sc])


def test_top_k_table_matches_independent_calculation(results):
    score, lab = _read_inputs()
    order = sorted(score, key=lambda p: (-score[p], p))                        # score desc, project_id asc
    anom = {p for p, r in lab.items() if r["ground_truth_label"] == "ANOMALOUS"}
    first_normal = next(i for i, p in enumerate(order) if p not in anom)
    for row in results["top_k_table"]:
        k = row["capacity"]
        sel = order[:k]
        tp = len([p for p in sel if p in anom])
        assert (row["anomalous_captured"], row["false_positives"]) == (tp, k - tp)
        assert row["recall"] == pytest.approx(tp / 49, abs=1e-6) and row["precision"] == pytest.approx(tp / k, abs=1e-6)
        assert row["pct_of_dataset"] == pytest.approx(k / 150, abs=1e-6)
        assert row["lowest_selected_score"] == pytest.approx(score[sel[-1]], abs=1e-6)
        hn = row["highest_ranked_normal"]
        assert (hn["project_id"], hn["rank"], hn["inside_selection"]) == (order[first_normal], first_normal + 1, first_normal + 1 <= k)
        assert row["adversarial_queued"] == len([p for p in sel if lab[p]["scenario_type"] == "ADVERSARIAL_NORMAL"])
        # ties: how many projects share the cutoff score, and the exact range of captured counts over every tie ordering
        cut = score[sel[-1]]
        tied = [p for p in order if score[p] == cut]
        above = [p for p in order if score[p] > cut]
        slots = k - len(above)
        a = len([p for p in tied if p in anom])
        base = len([p for p in above if p in anom])
        assert row["tied_at_cutoff"] == len(tied) and row["slots_filled_from_tie"] == slots
        assert row["captured_if_ties_ordered_worst"] == base + max(0, slots - (len(tied) - a))
        assert row["captured_if_ties_ordered_best"] == base + min(slots, a)


def test_score_distribution_matches_independent_calculation(results):
    score, lab = _read_inputs()
    vals = sorted(score.values())
    o = results["score_distribution"]["overall"]
    n = len(vals)
    mean = sum(vals) / n
    assert (o["min"], o["max"]) == (11.8, 55.5) and o["mean"] == pytest.approx(mean, abs=1e-6)
    assert o["std_population"] == pytest.approx((sum((v - mean) ** 2 for v in vals) / n) ** 0.5, abs=1e-6)
    med = (vals[n // 2 - 1] + vals[n // 2]) / 2
    assert o["median"] == pytest.approx(med, abs=1e-6)
    edges = [(None, 20), (20, 25), (25, 30), (30, 35), (35, 40), (40, 45), (45, 50), (50, None)]
    for b, (lo, hi) in zip(results["score_distribution"]["bands"], edges):
        ids = [p for p, s in score.items() if (lo is None or s >= lo) and (hi is None or s < hi)]
        assert b["n"] == len(ids) and b["anomalous"] == len([p for p in ids if lab[p]["ground_truth_label"] == "ANOMALOUS"])
        assert b["adversarial_normal"] == len([p for p in ids if lab[p]["scenario_type"] == "ADVERSARIAL_NORMAL"])
    assert sum(b["n"] for b in results["score_distribution"]["bands"]) == 150
    assert sum(lv["n"] for lv in results["score_distribution"]["native_risk_levels"]) == 150


def test_threshold_and_top_k_code_paths_agree_with_the_curve(results):
    """Cross-check two independent code paths: thresholds vs the cumulative queue curve (catches off-by-one in either)."""
    curve = {c["k"]: c for c in results["queue_curve"]}
    assert len(curve) == 150 and curve[150]["recall"] == 1.0 and curve[150]["precision"] == pytest.approx(49 / 150, abs=1e-6)
    for row in results["threshold_table"]:
        assert row["selection_identical_to_top_q"] is True              # no tie straddles any predefined cutoff
        assert curve[row["projects_queued"]]["tp"] == row["tp"]
    for row in results["top_k_table"]:
        assert curve[row["capacity"]]["tp"] == row["anomalous_captured"]
    qs = [t["projects_queued"] for t in results["threshold_table"]]
    assert qs == sorted(qs, reverse=True)
    rec = [t["recall"] for t in results["threshold_table"]]
    assert rec == sorted(rec, reverse=True)
    cap = [k["anomalous_captured"] for k in results["top_k_table"]]
    assert cap == sorted(cap)


def test_scale_sensitivity_agrees_with_v2_4_results(results):
    v24 = json.load(open(os.path.join(EVAL_DIR, "ablation", "ablation_comparison.json"), encoding="utf-8"))
    rows = {r["variant"]: r for r in results["scale_sensitivity_of_fixed_thresholds"]}
    assert set(rows) == set(v24["results"])
    for v, r in rows.items():
        assert r["queued_at_ge_30"] == v24["results"][v]["thresholds"]["30"]["flagged_total"]
        assert r["anomalous_at_ge_30"] == v24["results"][v]["thresholds"]["30"]["anomalous_detected"]
        assert r["queued_at_ge_40"] == v24["results"][v]["thresholds"]["40"]["flagged_total"]
        assert r["anomalous_in_top_20"] == round(v24["results"][v]["precision_at_k"]["20"]["precision"] * 20)
    full = rows["FULL"]
    t = {x["threshold"]: x for x in results["threshold_table"]}
    assert full["queued_at_ge_30"] == t[30]["projects_queued"] and full["anomalous_at_ge_40"] == t[40]["tp"]


def test_results_agree_with_v2_2_report(results):
    v22 = json.load(open(os.path.join(EVAL_DIR, "evaluation_report.json"), encoding="utf-8"))
    t = {x["threshold"]: x for x in results["threshold_table"]}
    for thr, key in ((40, "primary"), (30, "v1_queue_reference")):
        ref = v22["thresholded_classification"][key]
        assert (t[thr]["tp"], t[thr]["fp"], t[thr]["tn"], t[thr]["fn"]) == (ref["tp"], ref["fp"], ref["tn"], ref["fn"])
    k = {x["capacity"]: x for x in results["top_k_table"]}
    for cap in (5, 10, 20):
        assert k[cap]["precision"] == pytest.approx(v22["ranking"][f"precision_at_{cap}"]["precision"], abs=1e-6)
        assert k[cap]["recall"] == pytest.approx(v22["ranking"][f"precision_at_{cap}"]["recall_at_k"], abs=1e-6)


# --------------------------------------------------------------------------- #
# hand-computed synthetic fixture
# --------------------------------------------------------------------------- #
ANOM = {0, 1, 2, 4, 5, 8, 12, 20, 30, 45}          # 10 anomalous of 60
ADVS = {3, 6, 7, 15, 33}                            # 5 adversarial normals


def _synthetic():
    rows = []
    for i in range(60):
        pid = f"P{i:03d}"
        sc = "COST_ANOMALY" if i in ANOM else "ADVERSARIAL_NORMAL" if i in ADVS else "NORMAL"
        rows.append((pid, 59.0 - i, "ANOMALOUS" if i in ANOM else "NORMAL", sc))
    pred = pd.DataFrame([{"project_id": r[0], "risk_score": r[1], "risk_level": "LOW"} for r in rows])
    labels = pd.DataFrame([{"project_id": r[0], "ground_truth_label": r[2], "scenario_type": r[3]} for r in rows])
    df = M.prepare(pred, labels)
    return df, M.rank(df)


def test_threshold_arithmetic_hand_computed():
    df, ranked = _synthetic()
    rows = {r["threshold"]: r for r in RC.threshold_rows(df, ranked, n_adv=5)}
    # score = 59 - i, so ">= 50" selects i = 0..9, ">= 40" i = 0..19, etc.
    r50 = rows[50.0]
    assert (r50["projects_queued"], r50["tp"], r50["fp"], r50["fn"], r50["tn"]) == (10, 6, 4, 4, 46)     # anomalous in i<=9: {0,1,2,4,5,8}
    assert (r50["precision"], r50["recall"], r50["f1"]) == (pytest.approx(0.6), pytest.approx(0.6), pytest.approx(0.6))
    assert (r50["adversarial_queued"], r50["adversarial_queued_pct"], r50["plain_normal_queued"]) == (3, pytest.approx(0.6), 1)   # adv {3,6,7}; plain normal {9}
    r40 = rows[40.0]
    assert (r40["projects_queued"], r40["tp"], r40["fp"], r40["fn"], r40["tn"]) == (20, 7, 13, 3, 37)   # adds anomalous 12
    assert r40["precision"] == pytest.approx(0.35) and r40["recall"] == pytest.approx(0.7) and r40["f1"] == pytest.approx(2 * 0.35 * 0.7 / 1.05)
    assert rows[30.0]["tp"] == 8 and rows[30.0]["projects_queued"] == 30            # adds anomalous 20
    assert rows[20.0]["tp"] == 9 and rows[20.0]["projects_queued"] == 40            # adds anomalous 30
    assert all(r["tp"] + r["fp"] + r["tn"] + r["fn"] == 60 for r in rows.values())
    assert r50["scenario_captured"]["COST_ANOMALY"] == 6 and r50["scenario_captured"]["BILLING_ANOMALY"] == 0


def test_threshold_boundary_is_inclusive():
    df, ranked = _synthetic()
    rows = {r["threshold"]: r for r in RC.threshold_rows(df, ranked, n_adv=5)}
    assert df[df.risk_score == 50.0].shape[0] == 1                                   # exactly one project scores 50.0 (i = 9)
    assert rows[50.0]["projects_queued"] == 10 and (df.risk_score >= 50.0).sum() == 10 and (df.risk_score > 50.0).sum() == 9
    assert rows[25.0]["projects_queued"] == 35 and (df.risk_score == 25.0).sum() == 1


def test_top_k_hand_computed_and_deterministic():
    df, ranked = _synthetic()
    rows = {r["capacity"]: r for r in RC.topk_rows(df, ranked, n_adv=5)}
    expect = {5: 4, 10: 6, 20: 7, 25: 8, 30: 8, 40: 9, 50: 10}                      # anomalous captured in the first K
    for k, tp in expect.items():
        assert rows[k]["anomalous_captured"] == tp and rows[k]["false_positives"] == k - tp
        assert rows[k]["recall"] == pytest.approx(tp / 10) and rows[k]["precision"] == pytest.approx(tp / k)
        assert rows[k]["lowest_selected_score"] == 59.0 - (k - 1) and rows[k]["tie_sensitive"] is False
    hn = rows[5]["highest_ranked_normal"]
    assert (hn["project_id"], hn["rank"], hn["scenario_type"]) == ("P003", 4, "ADVERSARIAL_NORMAL")
    assert rows[5]["highest_ranked_normal"]["inside_selection"] is True
    assert rows[10]["adversarial_queued"] == 3 and rows[10]["plain_normal_queued"] == 1 and rows[10]["adversarial_queued_pct"] == pytest.approx(0.6)
    for seed in range(4):
        shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        assert list(M.rank(shuffled).project_id) == list(ranked.project_id)


def test_ties_are_broken_by_project_id_and_the_range_is_reported():
    rows = [("P-B", 50.0, "ANOMALOUS", "COST_ANOMALY"), ("P-A", 50.0, "NORMAL", "NORMAL"), ("P-C", 50.0, "ANOMALOUS", "COST_ANOMALY"),
            ("P-D", 50.0, "NORMAL", "NORMAL")] + [(f"Q{i:02d}", 40.0 - i, "NORMAL", "NORMAL") for i in range(56)]
    pred = pd.DataFrame([{"project_id": r[0], "risk_score": r[1], "risk_level": "LOW"} for r in rows])
    labels = pd.DataFrame([{"project_id": r[0], "ground_truth_label": r[2], "scenario_type": r[3]} for r in rows])
    df = M.prepare(pred, labels)
    ranked = M.rank(df)
    assert list(ranked.project_id[:4]) == ["P-A", "P-B", "P-C", "P-D"]
    top = {r["capacity"]: r for r in RC.topk_rows(df, ranked, n_adv=0)}
    k5 = top[5]                                                       # 4-way tie at ranks 1-4, all inside; rank 5 is a normal
    assert k5["anomalous_captured"] == 2 and k5["tie_sensitive"] is False
    ranked_small = ranked  # K=1 would be tie-sensitive: one slot from a 4-block with 2 anomalous
    cr = RC.captured_range(ranked_small, 1)
    assert (cr["tied_at_cutoff"], cr["slots_filled_from_tie"], cr["tied_excluded"]) == (4, 1, 3)
    assert (cr["captured_if_ties_ordered_worst"], cr["captured_if_ties_ordered_best"]) == (0, 1)
    assert RC.captured_range(ranked_small, 2)["captured_if_ties_ordered_worst"] == 0 and RC.captured_range(ranked_small, 2)["captured_if_ties_ordered_best"] == 2
    assert RC.captured_range(ranked_small, 4) == {**RC.captured_range(ranked_small, 4), "captured_if_ties_ordered_worst": 2, "captured_if_ties_ordered_best": 2}


def test_score_band_boundaries_are_half_open():
    for score, band in ((11.8, "<20"), (19.9, "<20"), (20.0, "20-24.9"), (24.9, "20-24.9"), (25.0, "25-29.9"), (29.9, "25-29.9"), (30.0, "30-34.9"),
                        (34.9, "30-34.9"), (35.0, "35-39.9"), (39.9, "35-39.9"), (40.0, "40-44.9"), (44.9, "40-44.9"), (45.0, "45-49.9"),
                        (49.9, "45-49.9"), (50.0, ">=50"), (55.5, ">=50"), (100.0, ">=50")):
        assert RC.band_of(score) == band, score


def test_v1_level_boundaries_and_queue_rule_match_v1_source():
    src = open(os.path.join(ROOT, "intelligence", "risk_engine.py"), encoding="utf-8").read()
    fn = re.search(r"def classify_risk_level.*?return \"LOW\"", src, re.S).group(0)
    assert re.findall(r"score >= (\d+)", fn) == ["80", "60", "30"]
    for score, level in ((80, "CRITICAL"), (79.9, "HIGH"), (60, "HIGH"), (59.9, "MEDIUM"), (30, "MEDIUM"), (29.9, "LOW")):
        assert RC.v1_risk_level(score) == level
    route = open(os.path.join(ROOT, "backend", "app", "api", "routes", "investigation_queue.py"), encoding="utf-8").read()
    assert 'r.risk_level != "LOW"' in route and "sort(key=lambda r: r.risk_score, reverse=True)" in route
    cal = pd.read_csv(os.path.join(CAL_DIR, "calibration_predictions.csv"), dtype={"project_id": str})
    assert ((cal.risk_level != "LOW").astype(int) == cal.in_v1_native_queue).all()
    assert (cal.in_v1_native_queue == (cal.risk_score >= 30).astype(int)).all()


# --------------------------------------------------------------------------- #
# leakage
# --------------------------------------------------------------------------- #
def test_stage_one_source_references_no_labels_signals_dataset_or_other_stages():
    tree = ast.parse(open(os.path.join(CAL_DIR, "run_calibration.py"), encoding="utf-8").read())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in STAGE1:
        assert _hits(_tokens(fns[name])) == [], name
    assert "evaluation_labels.csv" in " ".join(map(str, _tokens(fns["analyze"]))), "labels are read only in the separate analysis stage"
    imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    froms = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not {"intelligence", "backend"} & ({m.split(".")[0] for m in froms} | imports)
    assert froms <= {"__future__", "xml.sax.saxutils", "evaluation"}


def test_runtime_stage_one_reads_only_the_frozen_v1_predictions():
    seen, opened = [], []
    real_read, real_open = pd.read_csv, open

    def spy_read(path, *a, **k):
        seen.append(os.path.basename(str(path)))
        return real_read(path, *a, **k)

    def spy_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    with mock.patch("pandas.read_csv", spy_read), mock.patch("builtins.open", spy_open):
        RC.build_calibration_predictions(EVAL_DIR)
    assert seen == ["evaluation_predictions.csv"]
    assert [o for o in opened if any(w in o for w in ("evaluation_labels", "anomaly_signals", "engine_input", "ablation", "baseline"))] == []


def test_stage_one_output_identical_from_a_bare_directory(tmp_path):
    shutil.copy(os.path.join(EVAL_DIR, "evaluation_predictions.csv"), tmp_path / "evaluation_predictions.csv")
    assert sorted(os.listdir(tmp_path)) == ["evaluation_predictions.csv"]
    out = RC.build_calibration_predictions(str(tmp_path))
    committed = pd.read_csv(os.path.join(CAL_DIR, "calibration_predictions.csv"), dtype={"project_id": str})
    pd.testing.assert_frame_equal(out.reset_index(drop=True), committed.reset_index(drop=True))


def test_stage_one_refuses_scores_that_disagree_with_v1_levels(tmp_path):
    df = pd.read_csv(os.path.join(EVAL_DIR, "evaluation_predictions.csv"))
    df.loc[0, "risk_score"] = 59.0 if df.loc[0, "risk_score"] < 30 else 5.0          # a level V1's boundaries do not produce
    df.to_csv(tmp_path / "evaluation_predictions.csv", index=False)
    with pytest.raises(ValueError, match="risk_level disagrees"):
        RC.build_calibration_predictions(str(tmp_path))


def test_analysis_refuses_if_labels_differ_from_frozen_hash(tmp_path):
    d = _copy_eval(tmp_path, "tamper")
    RC.write_predictions(d)
    path = os.path.join(d, "evaluation_labels.csv")
    before = _sha(path)
    lab = pd.read_csv(path, dtype=str, keep_default_na=False)
    i = lab.index[lab.ground_truth_label == "ANOMALOUS"][0]
    lab.loc[i, "ground_truth_label"], lab.loc[i, "scenario_type"] = "NORMAL", "NORMAL"
    lab.to_csv(path, index=False)
    assert _sha(path) != before
    with pytest.raises(M.EvaluationInputError, match="provenance"):
        RC.analyze(d)


# --------------------------------------------------------------------------- #
# determinism, scope, newlines
# --------------------------------------------------------------------------- #
def test_repeated_execution_is_byte_identical_and_matches_committed(tmp_path):
    d1, d2 = _copy_eval(tmp_path, "run1"), _copy_eval(tmp_path, "run2")
    for d in (d1, d2):
        RC.write_predictions(d)
        RC.analyze(d)
    for f in ALL_FILES:
        b1, b2 = (open(os.path.join(d, "calibration", f), "rb").read() for d in (d1, d2))
        assert b1 == b2, f"{f} differs between two runs"
        assert b1 == open(os.path.join(CAL_DIR, f), "rb").read(), f"{f} differs from the committed copy"


def test_outputs_are_lf_even_when_text_mode_defaults_to_crlf(tmp_path):
    real_open = open

    def windows_like_open(file, mode="r", *args, **kwargs):
        if "w" in mode and "b" not in mode and not (len(args) >= 4 or kwargs.get("newline") is not None or "newline" in kwargs):
            kwargs["newline"] = "\r\n"
        return real_open(file, mode, *args, **kwargs)

    d = _copy_eval(tmp_path, "winsim")
    with mock.patch("builtins.open", windows_like_open):
        RC.write_predictions(d)
        RC.analyze(d)
    for f in ALL_FILES:
        assert b"\r" not in open(os.path.join(d, "calibration", f), "rb").read(), f"{f} contains CR bytes"


def test_run_writes_only_inside_the_calibration_folder_and_changes_nothing_else(tmp_path):
    d = _copy_eval(tmp_path, "scope")
    before = _tree_hashes(d)
    intel = {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py")}
    writes, real_open = [], open

    def spy_open(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            writes.append(os.path.abspath(str(file)))
        return real_open(file, mode, *a, **k)

    with mock.patch("builtins.open", spy_open):
        RC.write_predictions(d)
        RC.analyze(d)
    out_dir = os.path.abspath(os.path.join(d, "calibration"))
    assert writes and all(w.startswith(out_dir + os.sep) for w in writes), writes
    assert _tree_hashes(d) == before, "dataset, labels and V2.2-V2.4 artifacts must be byte-identical after a run"
    assert {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in intel} == intel


# --------------------------------------------------------------------------- #
# frozen files
# --------------------------------------------------------------------------- #
def test_v1_intelligence_unmodified_against_v2_2_recorded_hashes():
    rec = json.load(open(os.path.join(EVAL_DIR, "evaluation_predictions_meta.json"), encoding="utf-8"))["engine_source_sha256"]
    cur = {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py")}
    assert cur == rec


def test_v2_1_dataset_labels_and_v2_2_predictions_match_recorded_hashes():
    frozen = json.load(open(os.path.join(EVAL_DIR, "evaluation_metadata.json"), encoding="utf-8"))["file_sha256"]
    assert {k: _sha(os.path.join(EVAL_DIR, k)) for k in frozen} == frozen
    prov = json.load(open(os.path.join(EVAL_DIR, "evaluation_report.json"), encoding="utf-8"))["dataset_summary"]["provenance"]
    assert _sha(os.path.join(EVAL_DIR, "evaluation_predictions.csv")) == prov["predictions_sha256"]


def test_v2_3_and_v2_4_recorded_manifests_still_match_current_files():
    for mod, meta in ((RB, "baseline_predictions_meta.json"), (RA, os.path.join("ablation", "ablation_predictions_meta.json"))):
        rec = json.load(open(os.path.join(EVAL_DIR, meta), encoding="utf-8"))["frozen_manifest"]
        now = mod.manifest(EVAL_DIR)
        diff = {g: sorted(k for k in set(now[g]) | set(rec[g]) if now[g].get(k) != rec[g].get(k)) for g in rec}
        assert not {g: v for g, v in diff.items() if v}, (meta, diff)


def test_nothing_frozen_changed_since_the_v2_5_run():
    """The recorded manifest must have been produced by running the V2.5 command in THIS repository."""
    rec = json.load(open(os.path.join(CAL_DIR, "calibration_metadata.json"), encoding="utf-8"))["frozen_manifest"]
    now = RC.manifest(EVAL_DIR)
    assert set(rec) == {"v1_intelligence_source", "v1_backend_and_frontend_source", "v2_1_dataset_and_spec",
                        "v2_2_metrics_and_reference_outputs", "v2_3_baselines", "v2_4_ablation"}
    diff = {g: sorted(k for k in set(now[g]) | set(rec[g]) if now[g].get(k) != rec[g].get(k)) for g in rec}
    diff = {g: v for g, v in diff.items() if v}
    assert not diff, ("frozen assets differ from the manifest recorded by the V2.5 run; if (and only if) the current files are the intended "
                      f"frozen state, regenerate with `python -m evaluation.calibration.run_calibration --dir evaluation`: {diff}")


def test_manifest_covers_exactly_the_intended_frozen_assets():
    from evaluation.generate_evaluation_data import ENGINE_FILES
    m = RC.manifest(EVAL_DIR)
    intel = sorted(f"intelligence/{f}" for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py"))
    assert sorted(m["v1_intelligence_source"]) == intel and len(intel) >= 10
    walked = sorted(os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/") for b in ("backend/app", "src")
                    for dp, _dn, fn in os.walk(os.path.join(ROOT, b)) if "__pycache__" not in dp for f in fn)
    assert sorted(m["v1_backend_and_frontend_source"]) == walked and walked
    assert sorted(m["v2_1_dataset_and_spec"]) == sorted([f"evaluation/engine_input/{f}" for f in ENGINE_FILES] + [f"evaluation/{f}" for f in (
        "evaluation_labels.csv", "evaluation_metadata.json", "spec_constants.py", "SCENARIO_SPEC.md", "generate_evaluation_data.py", "run_v1_predictions.py")])
    assert sorted(m["v2_2_metrics_and_reference_outputs"]) == sorted(f"evaluation/{f}" for f in (
        "evaluation_metrics.py", "evaluation_predictions.csv", "evaluation_predictions_meta.json", "evaluation_report.json", "evaluation_report.md"))
    assert sorted(m["v2_3_baselines"]) == sorted([f"evaluation/baselines/{f}" for f in os.listdir(os.path.join(EVAL_DIR, "baselines")) if f.endswith(".py")] + [
        f"evaluation/{f}" for f in ("baseline_predictions.csv", "baseline_predictions_meta.json", "baseline_comparison.json", "baseline_comparison.md")])
    assert sorted(m["v2_4_ablation"]) == sorted([f"evaluation/ablation/{f}" for f in os.listdir(os.path.join(EVAL_DIR, "ablation")) if f.endswith(".py")] + [
        f"evaluation/ablation/{f}" for f in ("ablation_predictions.csv", "ablation_predictions_meta.json", "ablation_comparison.json", "ablation_comparison.md")])
    assert not [k for g in m.values() for k in g if "calibration" in k], "V2.5 outputs are not frozen assets"


# --------------------------------------------------------------------------- #
# plots and report
# --------------------------------------------------------------------------- #
def test_plots_are_well_formed_and_plot_the_reported_numbers(results):
    for p in PLOTS:
        root = ET.parse(os.path.join(CAL_DIR, "plots", p)).getroot()
        assert root.tag.endswith("svg") and root.find("{http://www.w3.org/2000/svg}title") is not None
        txt = open(os.path.join(CAL_DIR, "plots", p), encoding="utf-8").read()
        assert "nan" not in txt.lower().replace("financial", "") and "inf" not in re.sub(r"info", "", txt.lower())
    dist = open(os.path.join(CAL_DIR, "plots", "score_distribution.svg"), encoding="utf-8").read()
    for b in results["score_distribution"]["bands"]:
        assert f">{b['n']}</text>" in dist and f">{b['band'].replace('>', '&gt;').replace('<', '&lt;')}</text>" in dist
    q = open(os.path.join(CAL_DIR, "plots", "threshold_vs_queued.svg"), encoding="utf-8").read()
    for t in results["threshold_table"]:
        assert f">{t['projects_queued']}</text>" in q
    assert open(os.path.join(CAL_DIR, "plots", "queue_size_vs_recall.svg"), encoding="utf-8").read().count("<circle") == 7
    assert open(os.path.join(CAL_DIR, "plots", "threshold_vs_precision_recall.svg"), encoding="utf-8").read().count("<circle") == 14


def test_report_answers_the_six_questions_and_keeps_the_four_concepts_apart():
    md = open(os.path.join(CAL_DIR, "calibration_report.md"), encoding="utf-8").read()
    for q in ("**Q1.", "**Q2.", "**Q3.", "**Q4.", "**Q5.", "**Q6."):
        assert q in md, q
    assert re.search(r"\*\*Q6\..*?\*\*No\.\*\*", md, re.S), "Q6 must answer directly"
    for term in ("Model score", "Evaluation threshold", "Investigator operating point", "Production threshold"):
        assert f"**{term}**" in md, term
    assert RC.MANDATORY_CLAIM in md
    for needed in ("not a probability", "not production-calibrated", "evaluation operating points", "hypothetical", "synthetic"):
        assert needed in md, needed
    for h in ("## 3. Score distribution", "## 4. Fixed-score evaluation thresholds", "## 5. Investigator-capacity operating points (Top-K)",
              "## 6. Fixed threshold versus Top-K", "## 7. Adversarial normals", "## 8. Scenario capture", "## 9. Plots", "## 11. Limitations", "## 12. Conclusion"):
        assert h in md, h
    low = md.lower()
    for banned in ("optimal", "best threshold", "best f1", "threshold 37", "proven", "proves"):
        assert banned not in low, banned
    for row in ("| 5 |", "| 10 |", "| 20 |", "| 25 |", "| 30 |", "| 40 |", "| 50 |"):
        assert row in md
