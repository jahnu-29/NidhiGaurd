"""
V2.4 ablation tests.

Leakage is checked three independent ways (source, runtime file access, behaviour on a bare input directory).
Formula fidelity is checked against the REAL V1 source (risk_engine.py and each detector's MAX_SCORE) and against a
fresh run of the unmodified V1 engine. Ablation semantics use hand-computed synthetic values, including a case where
"recompute without the component" differs from "FULL minus the component".

Frozen-file checks compare with hashes recorded outside this stage (V1 prediction metadata, V2.1 metadata, V2.2 report,
V2.3 manifest). The "unchanged since the V2.4 run" check compares with the manifest written by the V2.4 run, so it detects
any later edit; it cannot by itself prove the files equal an earlier git commit.
"""
import ast
import hashlib
import json
import os
import re
import shutil
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from backend.v2_6_integrity import frozen_diff as v2_6_frozen_diff
from evaluation import evaluation_metrics as M
from evaluation.ablation import run_ablation as RA
from evaluation.baselines import run_baselines as RB

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(EVAL_DIR)
ABL_DIR = os.path.join(EVAL_DIR, "ablation")
OUT_FILES = ("ablation_predictions.csv", "ablation_predictions_meta.json", "ablation_comparison.json", "ablation_comparison.md")

FORBIDDEN = ["ground_truth", "evaluation_labels", "anomaly_signals", "scenario_type", "difficulty", "injected_signals",
             "group_id", "adversarial_subtype", "rationale", "y_true", "evaluation_metrics", "engine_input", "intelligence"]
STAGE1_FUNCTIONS = ("v1_aggregate", "v1_risk_level", "ablation_score", "load_components", "build_ablation_predictions")


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _tokens(tree):
    doc_ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            doc_ids.add(id(n.body[0].value))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out += [n.module or ""] + [a.name for a in n.names]
        elif isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
        elif isinstance(n, ast.arg):
            out.append(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids:
            out.append(n.value)
    return out


def _hits(toks):
    return sorted({f for f in FORBIDDEN for t in toks if f.lower() in str(t).lower()})


def _copy_eval(tmp_path, name):
    dst = tmp_path / name / "evaluation"
    shutil.copytree(EVAL_DIR, dst, ignore=shutil.ignore_patterns("__pycache__", "ablation"))
    return str(dst)


def _tree_hashes(root, skip=("ablation", "__pycache__")):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in skip]
        for f in fn:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = _sha(p)
    return out


@pytest.fixture(scope="module")
def committed():
    return pd.read_csv(os.path.join(ABL_DIR, "ablation_predictions.csv"), dtype={"project_id": str})


@pytest.fixture(scope="module")
def frozen_v1():
    return pd.read_csv(os.path.join(EVAL_DIR, "evaluation_predictions.csv"), dtype={"project_id": str})


# ------------------------------ V1 formula fidelity ------------------------ #
def test_v1_aggregation_in_source_matches_the_replica():
    src = open(os.path.join(ROOT, "intelligence", "risk_engine.py"), encoding="utf-8").read()
    assert RA.V1_EXPRESSIONS["raw_total"] in src and RA.V1_EXPRESSIONS["risk_score"] in src
    # the addition order in V1's source is the replica's component order
    line = next(ln for ln in src.splitlines() if "raw_total =" in ln)
    order = re.findall(r"(\w+)\.score", line)
    assert order == ["cost", "similarity", "contractor", "billing", "geographic"]
    assert [c[0] for c in RA.COMPONENTS] == ["cost_anomaly", "project_similarity", "contractor_pattern", "billing_anomaly", "geographic_signal"]
    # level boundaries are V1's
    fn = re.search(r"def classify_risk_level.*?return \"LOW\"", src, re.S).group(0)
    assert re.findall(r"score >= (\d+)", fn) == ["80", "60", "30"]
    for score, level in ((80, "CRITICAL"), (79.9, "HIGH"), (60, "HIGH"), (59.9, "MEDIUM"), (30, "MEDIUM"), (29.9, "LOW")):
        assert RA.v1_risk_level(score) == level


def test_component_caps_match_each_detector_source():
    files = {"cost_anomaly": "cost_anomaly.py", "project_similarity": "project_similarity.py", "contractor_pattern": "contractor_analysis.py",
             "billing_anomaly": "billing_analysis.py", "geographic_signal": "geographic_analysis.py"}
    for comp, f in files.items():
        src = open(os.path.join(ROOT, "intelligence", f), encoding="utf-8").read()
        assert int(re.search(r"^MAX_SCORE = (\d+)", src, re.M).group(1)) == RA.CAPS[comp], comp
    assert sum(RA.CAPS.values()) == 100


def test_detectors_are_independent_so_zeroing_one_removes_only_it():
    """No detector module imports another detector or the risk engine."""
    for f in ("cost_anomaly", "project_similarity", "contractor_analysis", "billing_analysis", "geographic_analysis"):
        tree = ast.parse(open(os.path.join(ROOT, "intelligence", f"{f}.py"), encoding="utf-8").read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level > 0}
        assert mods == set() or mods <= {"data_loader"}, (f, mods)


def test_full_variant_reproduces_every_frozen_v1_risk_score(committed, frozen_v1):
    full = committed[committed.variant == "FULL"].set_index("project_id").ablation_score
    ref = frozen_v1.set_index("project_id").risk_score
    assert len(full) == 150 and (full.reindex(ref.index) == ref).all()


def test_frozen_components_equal_a_fresh_run_of_the_unmodified_v1_engine(frozen_v1):
    """The ablation input is V1's real output, not a stale or edited copy."""
    from intelligence.data_loader import load_dataset
    from intelligence.risk_engine import build_engine
    res = build_engine(load_dataset(os.path.join(EVAL_DIR, "engine_input"))).score_all()
    fresh = pd.DataFrame([{"project_id": r.project_id, "risk_score": r.risk_score,
                           **{f"{k}_score": v["score"] for k, v in r.components.items()}} for r in res]).sort_values("project_id").reset_index(drop=True)
    ref = frozen_v1.sort_values("project_id").reset_index(drop=True)
    for c in ["risk_score", *RA.COMPONENT_COLUMNS]:
        assert (fresh[c] == ref[c]).all(), c


# ------------------------------ ablation semantics ------------------------- #
def _c(cost, sim, contr, bill, geo):
    return {"cost_anomaly": cost, "project_similarity": sim, "contractor_pattern": contr, "billing_anomaly": bill, "geographic_signal": geo}


def test_ablation_hand_computed():
    c = _c(10.0, 5.0, 3.0, 2.0, 1.0)
    assert RA.ablation_score(c, None) == 21.0
    assert RA.ablation_score(c, "cost_anomaly") == 11.0
    assert RA.ablation_score(c, "project_similarity") == 16.0
    assert RA.ablation_score(c, "contractor_pattern") == 18.0
    assert RA.ablation_score(c, "billing_anomaly") == 19.0
    assert RA.ablation_score(c, "geographic_signal") == 20.0


def test_ablation_recomputes_not_subtracts():
    over = _c(30.0, 25.0, 20.0, 20.0, 10.0)                 # out-of-range on purpose: raw 105, capped to 100.0 by V1's formula
    assert RA.ablation_score(over, None) == 100.0
    assert RA.ablation_score(over, "cost_anomaly") == 75.0   # recomputed: 25+20+20+10
    assert 100.0 - 30.0 == 70.0 != RA.ablation_score(over, "cost_anomaly")   # "FULL minus component" would be wrong


def test_ablation_keeps_v1_rounding_semantics():
    assert RA.ablation_score(_c(0.1, 0.2, 0.0, 0.0, 0.0), None) == 0.3          # round(0.30000000000000004, 1)
    assert RA.ablation_score(_c(0.1, 0.2, 0.0, 0.0, 0.0), "project_similarity") == 0.1
    assert RA.v1_aggregate(10.1, 10.2, 5.3, 4.4, 1.0) == round(min(100.0, 10.1 + 10.2 + 5.3 + 4.4 + 1.0), 1)


def test_unknown_component_is_rejected():
    with pytest.raises(ValueError):
        RA.ablation_score(_c(1, 1, 1, 1, 1), "nope")


def test_prediction_file_structure_and_ablation_definition(committed, frozen_v1):
    assert len(committed) == 900 and list(committed.variant.unique()) == list(RA.VARIANT_NAMES)
    ids = sorted(frozen_v1.project_id)
    full = committed[committed.variant == "FULL"].set_index("project_id")
    for v, ablated in RA.VARIANTS:
        sub = committed[committed.variant == v].set_index("project_id")
        assert sorted(sub.index) == ids and (sub.ablated_component == (ablated or "none")).all()
        for name, col, _cap in RA.COMPONENTS:
            if name == ablated:
                assert (sub[col] == 0.0).all(), f"{v}: {col} must be zero"
            else:
                assert (sub[col] == full[col].reindex(sub.index)).all(), f"{v}: {col} must be untouched"
        # independent recomputation of the score and level
        for pid, r in sub.iterrows():
            expect = RA.v1_aggregate(*(r[c] for c in RA.COMPONENT_COLUMNS))
            assert r.ablation_score == expect and r.risk_level == RA.v1_risk_level(expect)
        # rank = score descending, project_id ascending, a permutation of 1..150
        order = sub.reset_index().sort_values(["ablation_score", "project_id"], ascending=[False, True])
        assert list(order["rank"]) == list(range(1, 151))
    caps = {v: int(sum(c for k, c in RA.CAPS.items() if k != a)) for v, a in RA.VARIANTS}
    assert caps == {"FULL": 100, "NO_COST": 75, "NO_SIMILARITY": 75, "NO_CONTRACTOR": 80, "NO_BILLING": 80, "NO_GEOGRAPHIC": 90}
    for v in RA.VARIANT_NAMES:
        assert committed[committed.variant == v].ablation_score.max() <= caps[v]


# ------------------------------ leakage ------------------------------------ #
def test_stage_one_source_references_no_labels_signals_or_dataset():
    tree = ast.parse(open(os.path.join(ABL_DIR, "run_ablation.py"), encoding="utf-8").read())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in STAGE1_FUNCTIONS:
        assert _hits(_tokens(fns[name])) == [], name
    assert "evaluation_labels.csv" in " ".join(map(str, _tokens(fns["compare"]))), "labels are read only in the separate metrics stage"
    mods = {t.split(".")[0] for t in _tokens(tree) if False} | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "intelligence" not in mods | imports and "backend" not in mods | imports, "the ablation must not import V1 code"


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
        RA.build_ablation_predictions(EVAL_DIR)
    assert seen == ["evaluation_predictions.csv"]
    assert [o for o in opened if any(w in o for w in ("evaluation_labels", "anomaly_signals", "engine_input"))] == []


def test_stage_one_output_identical_from_a_bare_directory(tmp_path, committed):
    """Only the V1 reference predictions exist: no labels, no planted signals, no dataset, no metadata."""
    shutil.copy(os.path.join(EVAL_DIR, "evaluation_predictions.csv"), tmp_path / "evaluation_predictions.csv")
    assert sorted(os.listdir(tmp_path)) == ["evaluation_predictions.csv"]
    out = RA.build_ablation_predictions(str(tmp_path))
    pd.testing.assert_frame_equal(out.reset_index(drop=True), committed.reset_index(drop=True))


# ------------------------------ determinism -------------------------------- #
def test_repeated_execution_is_byte_identical_and_matches_committed(tmp_path):
    d1, d2 = _copy_eval(tmp_path, "run1"), _copy_eval(tmp_path, "run2")
    for d in (d1, d2):
        RA.write_predictions(d)
        RA.compare(d)
    for f in OUT_FILES:
        b1, b2, ref = (open(os.path.join(x, "ablation" if x != EVAL_DIR else "ablation", f) if x != EVAL_DIR else os.path.join(ABL_DIR, f), "rb").read()
                       for x in (d1, d2, EVAL_DIR))
        assert b1 == b2, f"{f} differs between two runs"
        assert b1 == ref, f"{f} differs from the committed copy"


def test_outputs_are_lf_even_when_text_mode_defaults_to_crlf(tmp_path):
    """Emulates Windows, where open(..., 'w') without newline= translates \\n to \\r\\n."""
    real_open = open

    def windows_like_open(file, mode="r", *args, **kwargs):
        if "w" in mode and "b" not in mode and not (len(args) >= 4 or kwargs.get("newline") is not None or "newline" in kwargs):
            kwargs["newline"] = "\r\n"
        return real_open(file, mode, *args, **kwargs)

    d = _copy_eval(tmp_path, "winsim")
    with mock.patch("builtins.open", windows_like_open):
        RA.write_predictions(d)
        RA.compare(d)
    for f in OUT_FILES:
        assert b"\r" not in open(os.path.join(d, "ablation", f), "rb").read(), f"{f} contains CR bytes"


def test_run_writes_only_inside_the_ablation_folder_and_changes_nothing_else(tmp_path):
    d = _copy_eval(tmp_path, "scope")
    before = _tree_hashes(d)
    intel_before = {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py")}
    writes, real_open = [], open

    def spy_open(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            writes.append(os.path.abspath(str(file)))
        return real_open(file, mode, *a, **k)

    with mock.patch("builtins.open", spy_open):
        RA.write_predictions(d)
        RA.compare(d)
    out_dir = os.path.abspath(os.path.join(d, "ablation"))
    assert writes and all(w.startswith(out_dir + os.sep) for w in writes), writes
    assert _tree_hashes(d) == before, "dataset, labels, V2.2 and V2.3 files must be byte-identical after a run"
    assert {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in intel_before} == intel_before


def test_comparison_metrics_reproducible_from_saved_predictions(committed):
    rep = json.load(open(os.path.join(ABL_DIR, "ablation_comparison.json"), encoding="utf-8"))
    labels = pd.read_csv(os.path.join(EVAL_DIR, "evaluation_labels.csv"), dtype=str, keep_default_na=False)
    for v in RA.VARIANT_NAMES:
        sub = committed[committed.variant == v]
        df = M.prepare(pd.DataFrame({"project_id": sub.project_id, "risk_score": sub.ablation_score, "risk_level": sub.risk_level}), labels)
        r = rep["results"][v]
        assert M.pr_auc(df)["average_precision"] == pytest.approx(r["average_precision"], abs=1e-6)
        ranked = M.rank(df)
        for k in (5, 10, 20):
            assert M.precision_at_k(ranked, k)["precision"] == pytest.approx(r["precision_at_k"][str(k)]["precision"], abs=1e-6)
        assert M.precision_at_k(ranked, 20)["recall_at_k"] == pytest.approx(r["precision_at_k"]["20"]["recall_at_k"], abs=1e-6)   # JSON is rounded to 6 dp
    # deltas are ABLATION - FULL
    f = rep["results"]["FULL"]
    for v in RA.VARIANT_NAMES[1:]:
        assert rep["deltas_vs_full"][v]["delta_pr_auc"] == pytest.approx(rep["results"][v]["average_precision"] - f["average_precision"], abs=1e-6)
        assert rep["deltas_vs_full"][v]["delta_precision_at_20"] == pytest.approx(
            rep["results"][v]["precision_at_k"]["20"]["precision"] - f["precision_at_k"]["20"]["precision"], abs=1e-6)


def test_full_variant_equals_v2_2_and_v2_3_results():
    rep = json.load(open(os.path.join(ABL_DIR, "ablation_comparison.json"), encoding="utf-8"))
    v22 = json.load(open(os.path.join(EVAL_DIR, "evaluation_report.json"), encoding="utf-8"))
    v23 = json.load(open(os.path.join(EVAL_DIR, "baseline_comparison.json"), encoding="utf-8"))
    full = rep["results"]["FULL"]
    assert full["average_precision"] == pytest.approx(v22["pr_auc"]["average_precision"], abs=1e-6)
    assert full["average_precision"] == pytest.approx(v23["approaches"]["NidhiGuard V1"]["average_precision"], abs=1e-6)
    for k in (5, 10, 20):
        assert full["precision_at_k"][str(k)]["precision"] == pytest.approx(v22["ranking"][f"precision_at_{k}"]["precision"], abs=1e-6)
    d = rep["dataset"]
    assert (d["projects"], d["anomalous"], d["normal"], d["adversarial_normal"]) == (150, 49, 101, 41)
    assert full["thresholds"]["40"]["anomalous_detected"] == v22["thresholded_classification"]["primary"]["tp"]
    assert full["thresholds"]["30"]["anomalous_detected"] == v22["thresholded_classification"]["v1_queue_reference"]["tp"]
    assert rep["v1_scoring_formula"]["full_variant_reproduces_frozen_v1_risk_score"] is True


# ------------------------------ frozen files ------------------------------- #
def test_v1_intelligence_unmodified_against_v2_2_recorded_hashes():
    recorded = json.load(open(os.path.join(EVAL_DIR, "evaluation_predictions_meta.json"), encoding="utf-8"))["engine_source_sha256"]
    current = {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py")}
    assert current == recorded


def test_v2_1_dataset_and_labels_byte_identical_to_frozen_hashes():
    frozen = json.load(open(os.path.join(EVAL_DIR, "evaluation_metadata.json"), encoding="utf-8"))["file_sha256"]
    assert {k: _sha(os.path.join(EVAL_DIR, k)) for k in frozen} == frozen


def test_v2_2_reference_predictions_and_labels_match_the_v2_2_report():
    prov = json.load(open(os.path.join(EVAL_DIR, "evaluation_report.json"), encoding="utf-8"))["dataset_summary"]["provenance"]
    assert _sha(os.path.join(EVAL_DIR, "evaluation_predictions.csv")) == prov["predictions_sha256"]
    assert _sha(os.path.join(EVAL_DIR, "evaluation_labels.csv")) == prov["labels_sha256"]


def test_v2_3_frozen_manifest_still_matches_current_files():
    """The V2.3 recorded manifest is historical and unchanged; only the V2.6-declared application files may differ (see v2_6_integrity)."""
    recorded = json.load(open(os.path.join(EVAL_DIR, "baseline_predictions_meta.json"), encoding="utf-8"))["frozen_manifest"]
    now = RB.manifest(EVAL_DIR)
    assert not v2_6_frozen_diff(recorded, now), v2_6_frozen_diff(recorded, now)


def test_nothing_frozen_changed_since_the_v2_4_run():
    """V1 engine/backend/frontend, V2.1 dataset+spec, V2.2 metrics+outputs, V2.3 baselines.

    The recorded manifest must have been produced by running the V2.4 command in THIS repository; a manifest produced
    elsewhere hashes that machine's copies of files such as evaluation_predictions_meta.json (which embeds a git commit).

    V2.6 note: the recorded V1 backend/frontend group is a historical snapshot and is never regenerated. V2.6 is an
    intentional application-code change after this run, so the files it declares in backend/v2_6_source_manifest.json
    are tolerated in that group only; every other difference (and every other group) is still reported.
    """
    recorded = json.load(open(os.path.join(ABL_DIR, "ablation_predictions_meta.json"), encoding="utf-8"))["frozen_manifest"]
    now = RA.manifest(EVAL_DIR)
    assert set(recorded) == {"v1_intelligence_source", "v1_backend_and_frontend_source", "v2_1_dataset_and_spec",
                             "v2_2_metrics_and_reference_outputs", "v2_3_baselines"}
    differing = v2_6_frozen_diff(recorded, now)
    assert not differing, ("frozen assets differ from the manifest recorded by the V2.4 run; if (and only if) the current files are the intended "
                           f"frozen state, regenerate with `python -m evaluation.ablation.run_ablation --dir evaluation`: {differing}")


def test_manifest_covers_exactly_the_intended_frozen_assets():
    from evaluation.generate_evaluation_data import ENGINE_FILES
    m = RA.manifest(EVAL_DIR)
    intel = sorted(f"intelligence/{f}" for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py"))
    assert sorted(m["v1_intelligence_source"]) == intel and len(intel) >= 10
    walked = sorted(os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/") for base in ("backend/app", "src")
                    for dp, _dn, fn in os.walk(os.path.join(ROOT, base)) if "__pycache__" not in dp for f in fn)
    assert sorted(m["v1_backend_and_frontend_source"]) == walked and walked
    assert sorted(m["v2_1_dataset_and_spec"]) == sorted([f"evaluation/engine_input/{f}" for f in ENGINE_FILES] + [f"evaluation/{f}" for f in (
        "evaluation_labels.csv", "evaluation_metadata.json", "spec_constants.py", "SCENARIO_SPEC.md", "generate_evaluation_data.py", "run_v1_predictions.py")])
    assert sorted(m["v2_2_metrics_and_reference_outputs"]) == sorted(f"evaluation/{f}" for f in (
        "evaluation_metrics.py", "evaluation_predictions.csv", "evaluation_predictions_meta.json", "evaluation_report.json", "evaluation_report.md"))
    v23 = sorted(f"evaluation/baselines/{f}" for f in os.listdir(os.path.join(EVAL_DIR, "baselines")) if f.endswith(".py")) + [
        f"evaluation/{f}" for f in ("baseline_predictions.csv", "baseline_predictions_meta.json", "baseline_comparison.json", "baseline_comparison.md")]
    assert sorted(m["v2_3_baselines"]) == sorted(v23)
    assert not [k for g in m.values() for k in g if "ablation" in k], "V2.4 outputs are not frozen assets"


def test_compare_refuses_if_labels_differ_from_frozen_hash(tmp_path):
    d = _copy_eval(tmp_path, "tamper")
    RA.write_predictions(d)
    path = os.path.join(d, "evaluation_labels.csv")
    before = _sha(path)
    lab = pd.read_csv(path, dtype=str, keep_default_na=False)
    i = lab.index[lab.ground_truth_label == "ANOMALOUS"][0]
    lab.loc[i, "ground_truth_label"], lab.loc[i, "scenario_type"] = "NORMAL", "NORMAL"
    lab.to_csv(path, index=False)
    assert _sha(path) != before
    with pytest.raises(M.EvaluationInputError, match="provenance"):
        RA.compare(d)


def test_stage_one_refuses_if_the_frozen_predictions_disagree_with_the_formula(tmp_path):
    shutil.copy(os.path.join(EVAL_DIR, "evaluation_predictions.csv"), tmp_path / "evaluation_predictions.csv")
    df = pd.read_csv(tmp_path / "evaluation_predictions.csv")
    df.loc[0, "risk_score"] = df.loc[0, "risk_score"] + 0.1          # a V1 score that its components do not explain
    df.to_csv(tmp_path / "evaluation_predictions.csv", index=False)
    with pytest.raises(ValueError, match="FULL recomputation differs"):
        RA.build_ablation_predictions(str(tmp_path))


# ------------------------------ statistics helpers ------------------------- #
def test_tie_sensitivity_range_is_exact():
    rows = []
    for i, s in enumerate((90, 89, 88, 87)):                                   # ranks 1-4: anomalous, strictly above the tie
        rows.append((f"P{i:02d}", float(s), "ANOMALOUS", "COST_ANOMALY"))
    for i, (s, lab) in enumerate(((50, "ANOMALOUS"), (50, "NORMAL"), (50, "ANOMALOUS"), (50, "NORMAL"))):   # ranks 5-8: 4-way tie, 2 anomalous
        rows.append((f"P{10 + i:02d}", float(s), lab, "COST_ANOMALY" if lab == "ANOMALOUS" else "NORMAL"))
    for i in range(22):                                                         # distinct low-scoring normals
        rows.append((f"P{20 + i:02d}", 40.0 - i, "NORMAL", "ADVERSARIAL_NORMAL" if i == 0 else "NORMAL"))
    pred = pd.DataFrame([{"project_id": r[0], "risk_score": r[1], "risk_level": "LOW"} for r in rows])
    labels = pd.DataFrame([{"project_id": r[0], "ground_truth_label": r[2], "scenario_type": r[3], "difficulty": "NA", "adversarial_subtype": "A" if r[3] == "ADVERSARIAL_NORMAL" else ""} for r in rows])
    res, _ = RA.evaluate_variant("X", None, pred, labels)
    k5 = res["ties"]["precision_at_k_tie_range"]["5"]
    # K=5: 4 definite anomalous + 1 slot from a block of 4 with 2 anomalous -> worst 4/5, best 5/5
    assert (k5["p_at_k_if_ties_ordered_worst"], k5["p_at_k_if_ties_ordered_best"], k5["tied_block_at_cutoff"], k5["tie_sensitive"]) == (0.8, 1.0, 4, True)
    k10 = res["ties"]["precision_at_k_tie_range"]["10"]
    assert k10["tie_sensitive"] is False and k10["tied_block_at_cutoff"] == 1


def test_paired_bootstrap_is_seeded_and_directional():
    rng = np.random.default_rng(1)
    y = np.array([1] * 20 + [0] * 40)
    good, rand = y + rng.normal(0, 0.2, len(y)), rng.normal(0, 1, len(y))
    a, b = RA.paired_bootstrap_delta_ap(y, rand, good, n=300), RA.paired_bootstrap_delta_ap(y, rand, good, n=300)
    assert a == b and a["mean_delta_ap"] < -0.3 and a["ci95"][1] < 0
    assert RA.paired_bootstrap_delta_ap(y, good, rand, n=300)["mean_delta_ap"] > 0.3


def _fake(ap, p5, p10, p20, r20, d30=0, d40=0):
    return {"ablated_component": "x", "average_precision": ap,
            "precision_at_k": {"5": {"precision": p5, "recall_at_k": 0}, "10": {"precision": p10, "recall_at_k": 0},
                               "20": {"precision": p20, "recall_at_k": r20}},
            "thresholds": {"30": {"anomalous_detected": d30}, "40": {"anomalous_detected": d40}},
            "adversarial_normal": {"flagged_at_30": 0, "flagged_at_40": 0, "max_score": 10.0, "in_top_20": 2}}


def test_contribution_analysis_classification_hand_computed():
    res = {"FULL": _fake(0.80, 1.0, 0.9, 0.85, 0.35)}
    spec = {"NO_COST": (0.74, 1.0, 1.0, 0.90, 0.37), "NO_SIMILARITY": (0.70, 0.8, 0.8, 0.80, 0.33),
            "NO_CONTRACTOR": (0.80, 1.0, 0.9, 0.85, 0.35), "NO_BILLING": (0.79, 1.0, 0.9, 0.85, 0.35), "NO_GEOGRAPHIC": (0.82, 1.0, 0.9, 0.85, 0.35)}
    for v, vals in spec.items():
        res[v] = _fake(*vals)
    dl = RA.deltas(res)
    boot = {v: {"ci95": [-0.2, 0.1]} for v in spec}
    boot["NO_SIMILARITY"] = {"ci95": [-0.20, -0.02]}
    boot["NO_GEOGRAPHIC"] = {"ci95": [0.01, 0.05]}
    ca = RA.contribution_analysis(res, dl, boot)
    rk = {e["variant"]: e for e in ca["ranking_by_ap_contribution"]}
    assert [e["variant"] for e in ca["ranking_by_ap_contribution"]][:2] == ["NO_SIMILARITY", "NO_COST"]
    assert rk["NO_SIMILARITY"]["removal_reliably_hurts"] and not rk["NO_COST"]["removal_reliably_hurts"]
    assert rk["NO_GEOGRAPHIC"]["removal_improves_ap"] and rk["NO_GEOGRAPHIC"]["removal_reliably_helps"]
    assert rk["NO_BILLING"]["small_change"] and not rk["NO_COST"]["small_change"]
    assert rk["NO_COST"]["removal_improves_top_of_queue"].keys() == {"delta_precision_at_10", "delta_precision_at_20", "delta_recall_at_20"}
    assert rk["NO_CONTRACTOR"]["no_headline_metric_changed"] and not rk["NO_BILLING"]["no_headline_metric_changed"]


# ------------------------------ report ------------------------------------- #
def test_report_wording_and_structure():
    md = open(os.path.join(ABL_DIR, "ablation_comparison.md"), encoding="utf-8").read()
    for h in ("## 1. Objective", "## 2. Experimental design", "## 3. V1 scoring formula", "## 4. Dataset", "## 5. Variants", "## 6. Metrics",
              "## 7. Main results", "## 8. Detector contribution analysis", "## 9. Adversarial-normal analysis", "## 10. Scenario-level analysis",
              "## 11. Limitations", "## 12. Conclusion"):
        assert h in md, h
    assert RA.MANDATORY_STATEMENT in md and md.count(RA.MANDATORY_STATEMENT) >= 2
    assert "This ablation study evaluates detector contribution on the frozen V2.1 synthetic evaluation set. It does not establish real-world fraud-detection effectiveness." in md
    assert "raw_total  = cost.score + similarity.score + contractor.score + billing.score + geographic.score" in md
    assert "risk_score = round(min(100.0, raw_total), 1)" in md
    assert "negative delta means removing the detector lowered the metric" in md or "negative = removing the detector reduced the metric" in md
    assert "not accuracy" in md and "ABLATION - FULL" in md
    for banned in ("useless", "worthless", "proves", "proven"):
        assert banned not in md.lower(), banned
    assert "150 projects" in md and "**49 anomalous**" in md and "**41 are adversarial normals**" in md
    assert "Supplementary optimistic bootstrap interval; row resampling does not account for linked synthetic scenario groups." in md
    assert "\\* Tie-sensitive" in md        # the tie-dependent cell is disclosed in the report itself
