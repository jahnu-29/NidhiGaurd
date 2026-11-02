"""
V2.2 evaluation-metrics tests.

All expected values below are derived by hand from the fixture, NOT by calling the module under test.
These tests use synthetic data only; they never read or write the real V2.1 labels or predictions,
except the final integration test, which only checks invariants (no metric values are pinned).
"""
import ast
import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

from evaluation import evaluation_metrics as M

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# pid, score, level, label, scenario, difficulty, adv_subtype
ROWS = [
    ("P01", 90.0, "HIGH",   "ANOMALOUS", "COST_ANOMALY",        "OBVIOUS",    ""),
    ("P02", 80.0, "HIGH",   "NORMAL",    "ADVERSARIAL_NORMAL",  "NA",         "C"),
    ("P03", 70.0, "HIGH",   "ANOMALOUS", "BILLING_ANOMALY",     "BORDERLINE", ""),
    ("P04", 60.0, "HIGH",   "NORMAL",    "NORMAL",              "NA",         ""),
    ("P05", 50.0, "MEDIUM", "ANOMALOUS", "MULTI_SIGNAL",        "OBVIOUS",    ""),
    ("P06", 40.0, "MEDIUM", "NORMAL",    "NORMAL",              "NA",         ""),   # exactly at threshold
    ("P07", 30.0, "MEDIUM", "ANOMALOUS", "SIMILAR_PROJECT",     "BORDERLINE", ""),
    ("P08", 20.0, "LOW",    "NORMAL",    "ADVERSARIAL_NORMAL",  "NA",         "A"),
    ("P09", 10.0, "LOW",    "ANOMALOUS", "CONTRACTOR_PATTERN",  "OBVIOUS",    ""),
    ("P10",  5.0, "LOW",    "NORMAL",    "NORMAL",              "NA",         ""),
]


def frames(rows=ROWS):
    pred = pd.DataFrame([{"project_id": r[0], "risk_score": r[1], "risk_level": r[2]} for r in rows])
    labels = pd.DataFrame([{"project_id": r[0], "ground_truth_label": r[3], "scenario_type": r[4],
                            "difficulty": r[5], "adversarial_subtype": r[6]} for r in rows])
    return pred, labels


@pytest.fixture
def df():
    return M.prepare(*frames())


# ------------------------------ labels ------------------------------------- #
def test_binary_label_conversion(df):
    got = dict(zip(df.project_id, df.y_true))
    assert got == {"P01": 1, "P02": 0, "P03": 1, "P04": 0, "P05": 1, "P06": 0, "P07": 1, "P08": 0, "P09": 1, "P10": 0}


def test_adversarial_normal_is_binary_normal(df):
    adv = df[df.scenario_type == "ADVERSARIAL_NORMAL"]
    assert len(adv) == 2 and (adv.y_true == 0).all() and (adv.ground_truth_label == "NORMAL").all()
    # a high-scoring adversarial case is a FALSE POSITIVE, not a hit
    t = M.thresholded(df, 40.0)
    fps = set(df.loc[(df.risk_score >= 40) & (df.y_true == 0), "project_id"])
    assert fps == {"P02", "P04", "P06"}      # P02 is the adversarial normal
    assert t["fp"] == 3


def test_label_vocabulary_is_exact():
    assert M.POSITIVE_LABEL == "ANOMALOUS" and M.NEGATIVE_LABEL == "NORMAL"
    assert set(M.NORMAL_SCENARIOS) == {"NORMAL", "ADVERSARIAL_NORMAL"}
    assert len(M.SCENARIO_ORDER) == 8


# ------------------------------ ranking ------------------------------------ #
def test_ranking_descending_and_deterministic(df):
    r = M.rank(df)
    assert list(r.project_id) == ["P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10"]
    for seed in range(5):   # input order must not matter
        shuffled = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        assert list(M.rank(shuffled).project_id) == list(r.project_id)


def test_tie_break_by_project_id_ascending():
    rows = [("P-B", 50.0, "MEDIUM", "ANOMALOUS", "COST_ANOMALY", "OBVIOUS", ""),
            ("P-A", 50.0, "MEDIUM", "NORMAL", "NORMAL", "NA", ""),
            ("P-C", 50.0, "MEDIUM", "NORMAL", "NORMAL", "NA", ""),
            ("P-D", 10.0, "LOW", "NORMAL", "NORMAL", "NA", "")]
    d = M.prepare(*frames(rows))
    assert list(M.rank(d).project_id) == ["P-A", "P-B", "P-C", "P-D"]
    assert M.precision_at_k(M.rank(d), 1)["precision"] == 0.0      # ascending id puts the normal first
    assert M.precision_at_k(M.rank(d), 2)["precision"] == 0.5
    shuffled = d.sample(frac=1.0, random_state=3)
    assert list(M.rank(shuffled).project_id) == ["P-A", "P-B", "P-C", "P-D"]


# ------------------------------ Precision@K / recall ----------------------- #
def test_precision_at_k_hand_computed(df):
    r = M.rank(df)
    # top5 = P01(A) P02(N) P03(A) P04(N) P05(A) -> 3 anomalous
    assert M.precision_at_k(r, 5)["anomalous_in_top_k"] == 3
    assert M.precision_at_k(r, 5)["precision"] == pytest.approx(0.6)
    assert M.precision_at_k(r, 10)["precision"] == pytest.approx(0.5)      # 5 of 10
    assert M.precision_at_k(r, 1)["precision"] == 1.0
    assert M.precision_at_k(r, 2)["precision"] == 0.5
    assert M.precision_at_k(r, 5)["recall_at_k"] == pytest.approx(3 / 5)
    assert M.precision_at_k(r, 5)["k"] == 5


def test_build_report_needs_at_least_20_projects():
    with pytest.raises(M.EvaluationInputError, match="k must be"):
        M.build_report(*frames())      # 10 projects cannot yield Precision@20


def test_precision_at_k_rejects_bad_k(df):
    r = M.rank(df)
    for k in (0, -1, 11, 2.5):
        with pytest.raises(M.EvaluationInputError):
            M.precision_at_k(r, k)


def test_recall_thresholded_and_at_k(df):
    t = M.thresholded(df, 40.0)
    assert t["recall"] == pytest.approx(3 / 5)           # TP 3 (P01,P03,P05) / 5 actual anomalous
    assert M.precision_at_k(M.rank(df), 10)["recall_at_k"] == 1.0
    # recall does not depend on risk_level
    pred, labels = frames()
    pred["risk_level"] = "LOW"
    assert M.thresholded(M.prepare(pred, labels), 40.0)["recall"] == pytest.approx(3 / 5)


# ------------------------------ confusion matrix --------------------------- #
def test_confusion_matrix_hand_computed_and_boundary_inclusive(df):
    t = M.thresholded(df, 40.0)
    # >=40 predicted anomaly: P01..P06 (P06 is exactly 40 -> positive)
    assert (t["tp"], t["fp"], t["tn"], t["fn"]) == (3, 3, 2, 2)
    assert t["precision"] == pytest.approx(0.5) and t["recall"] == pytest.approx(0.6)
    assert t["f1"] == pytest.approx(2 * 0.5 * 0.6 / 1.1)
    assert t["false_positive_rate"] == pytest.approx(3 / 5)
    assert t["tp"] + t["fp"] + t["tn"] + t["fn"] == len(df)
    t30 = M.thresholded(df, 30.0)
    assert (t30["tp"], t30["fp"], t30["tn"], t30["fn"]) == (4, 3, 2, 1)


def test_confusion_undefined_ratios_are_none_not_zero():
    rows = [("P01", 10.0, "LOW", "ANOMALOUS", "COST_ANOMALY", "OBVIOUS", ""),
            ("P02", 5.0, "LOW", "NORMAL", "NORMAL", "NA", "")]
    t = M.thresholded(M.prepare(*frames(rows)), 40.0)
    assert t["tp"] == 0 and t["fp"] == 0
    assert t["precision"] is None and t["f1"] is None and t["recall"] == 0.0


def test_thresholds_are_the_specified_constants():
    assert M.PRIMARY_THRESHOLD == 40.0 and M.V1_QUEUE_THRESHOLD == 30.0 and M.TOP_K == (5, 10, 20)


# ------------------------------ PR-AUC ------------------------------------- #
def test_pr_auc_hand_computed(df):
    # labels by descending score: 1,0,1,0,1,0,1,0,1,0 -> AP = (1 + 2/3 + 3/5 + 4/7 + 5/9) / 5
    expected = (1 + 2 / 3 + 3 / 5 + 4 / 7 + 5 / 9) / 5
    assert M.pr_auc(df)["average_precision"] == pytest.approx(expected)
    assert M.pr_auc(df)["random_baseline"] == pytest.approx(0.5)


def test_pr_auc_perfect_and_worst_ranking():
    perfect = [("P01", 90.0, "HIGH", "ANOMALOUS", "COST_ANOMALY", "OBVIOUS", ""),
               ("P02", 80.0, "HIGH", "ANOMALOUS", "BILLING_ANOMALY", "OBVIOUS", ""),
               ("P03", 20.0, "LOW", "NORMAL", "NORMAL", "NA", ""),
               ("P04", 10.0, "LOW", "NORMAL", "NORMAL", "NA", "")]
    assert M.pr_auc(M.prepare(*frames(perfect)))["average_precision"] == pytest.approx(1.0)
    worst = [(p, s, lv, l, sc, d, a) for (p, _, lv, l, sc, d, a), s in zip(perfect, (10.0, 5.0, 90.0, 80.0))]
    assert M.pr_auc(M.prepare(*frames(worst)))["average_precision"] < 0.6


def test_pr_auc_uses_score_not_risk_level(df):
    pred, labels = frames()
    base = M.pr_auc(M.prepare(pred, labels))["average_precision"]
    pred["risk_level"] = ["LOW", "CRITICAL"] * 5          # scrambled, meaningless levels
    assert M.pr_auc(M.prepare(pred, labels))["average_precision"] == pytest.approx(base)


def test_pr_auc_fails_without_positives():
    rows = [(p, s, lv, "NORMAL", "NORMAL", "NA", "") for (p, s, lv, *_r) in ROWS]
    with pytest.raises(M.EvaluationInputError, match="no ANOMALOUS"):
        M.prepare(*frames(rows))
    d = M.prepare(*frames())
    d["y_true"] = 0
    with pytest.raises(M.EvaluationInputError, match="no positive"):
        M.pr_auc(d)


# ------------------------------ scenario / adversarial --------------------- #
def test_scenario_aggregation(df):
    t = M.scenario_table(df)
    assert list(t) == list(M.SCENARIO_ORDER)
    n = t["NORMAL"]                                # P04=60, P06=40, P10=5
    assert (n["n"], n["n_anomalous"], n["n_normal"]) == (3, 0, 3)
    assert n["mean"] == pytest.approx(35.0) and n["median"] == 40.0 and n["max"] == 60.0
    assert n["n_at_or_above_primary"] == 2 and n["rate_at_or_above_primary"] == pytest.approx(2 / 3)
    assert n["n_at_or_above_v1_queue"] == 2 and n["rate_meaning"] == "false_positive_rate"
    c = t["COST_ANOMALY"]                          # P01=90
    assert (c["n"], c["n_anomalous"]) == (1, 1) and c["max"] == 90.0 and c["rate_at_or_above_primary"] == 1.0
    assert c["rate_meaning"] == "detection_rate"
    assert t["CONTRACTOR_PATTERN"]["n_at_or_above_primary"] == 0 and t["CONTRACTOR_PATTERN"]["mean"] == 10.0
    assert sum(v["n"] for v in t.values()) == len(df)
    assert t["BILLING_ANOMALY"]["by_difficulty"]["BORDERLINE"]["n"] == 1
    assert t["MULTI_SIGNAL"]["by_difficulty"]["OBVIOUS"]["max"] == 50.0
    assert t["SIMILAR_PROJECT"]["n_at_or_above_primary"] == 0 and t["SIMILAR_PROJECT"]["n_at_or_above_v1_queue"] == 1


def test_adversarial_analysis(df):
    a = M.adversarial_analysis(df)                 # P02=80 (C), P08=20 (A)
    assert a["n"] == 2 and a["treated_as"] == "NORMAL"
    assert a["mean"] == pytest.approx(50.0) and a["median"] == pytest.approx(50.0) and a["max"] == 80.0
    assert a["n_at_or_above_primary"] == 1 and a["false_positive_rate_primary"] == pytest.approx(0.5)
    assert a["false_positive_rate_v1_queue"] == pytest.approx(0.5)
    assert set(a["by_subtype"]) == {"A", "C"} and a["by_subtype"]["C"]["n_at_or_above_primary"] == 1
    assert a["by_subtype"]["A"]["n_at_or_above_primary"] == 0


def test_top_n_order_and_fields(df):
    top = M.top_n(M.rank(df), 3)
    assert [t["project_id"] for t in top] == ["P01", "P02", "P03"] and [t["rank"] for t in top] == [1, 2, 3]
    assert set(top[0]) == {"rank", "project_id", "risk_score", "risk_level", "ground_truth_label", "scenario_type"}


# ------------------------------ input validation --------------------------- #
def test_missing_predictions_for_labelled_projects():
    pred, labels = frames()
    with pytest.raises(M.EvaluationInputError, match="missing predictions"):
        M.prepare(pred[pred.project_id != "P05"], labels)


def test_predictions_without_labels():
    pred, labels = frames()
    extra = pd.concat([pred, pd.DataFrame([{"project_id": "P99", "risk_score": 1.0, "risk_level": "LOW"}])])
    with pytest.raises(M.EvaluationInputError, match="no label"):
        M.prepare(extra, labels)


def test_duplicate_project_ids():
    pred, labels = frames()
    with pytest.raises(M.EvaluationInputError, match="duplicate"):
        M.prepare(pd.concat([pred, pred.iloc[[0]]]), labels)
    with pytest.raises(M.EvaluationInputError, match="duplicate"):
        M.prepare(pred, pd.concat([labels, labels.iloc[[0]]]))


def test_missing_or_non_numeric_scores():
    pred, labels = frames()
    p2 = pred.copy(); p2.loc[2, "risk_score"] = np.nan
    with pytest.raises(M.EvaluationInputError, match="risk_score"):
        M.prepare(p2, labels)
    p3 = pred.copy(); p3["risk_score"] = p3["risk_score"].astype(object); p3.loc[1, "risk_score"] = "high"
    with pytest.raises(M.EvaluationInputError, match="risk_score"):
        M.prepare(p3, labels)
    p4 = pred.copy(); p4.loc[0, "risk_score"] = np.inf
    with pytest.raises(M.EvaluationInputError, match="risk_score"):
        M.prepare(p4, labels)


def test_invalid_labels_and_scenarios():
    pred, labels = frames()
    for bad in ("YES", "anomalous", "", "ANOMALY"):
        l2 = labels.copy(); l2.loc[0, "ground_truth_label"] = bad
        with pytest.raises(M.EvaluationInputError, match="invalid ground_truth_label"):
            M.prepare(pred, l2)
    l3 = labels.copy(); l3.loc[0, "scenario_type"] = "SOMETHING_NEW"
    with pytest.raises(M.EvaluationInputError, match="unknown scenario_type"):
        M.prepare(pred, l3)
    l4 = labels.copy(); l4.loc[1, "ground_truth_label"] = "ANOMALOUS"      # ADVERSARIAL_NORMAL labelled anomalous
    with pytest.raises(M.EvaluationInputError, match="disagrees"):
        M.prepare(pred, l4)


def test_missing_columns_and_blank_ids():
    pred, labels = frames()
    with pytest.raises(M.EvaluationInputError, match="missing required column"):
        M.prepare(pred.drop(columns=["risk_score"]), labels)
    with pytest.raises(M.EvaluationInputError, match="missing required column"):
        M.prepare(pred, labels.drop(columns=["scenario_type"]))
    l2 = labels.copy(); l2.loc[0, "project_id"] = " "
    with pytest.raises(M.EvaluationInputError, match="empty or missing"):
        M.prepare(pred, l2)


def test_empty_positive_class_fails_clearly():
    rows = [(p, s, lv, "NORMAL", "NORMAL", "NA", "") for (p, s, lv, *_r) in ROWS]
    with pytest.raises(M.EvaluationInputError, match="no ANOMALOUS"):
        M.build_report(*frames(rows))


def test_single_class_all_anomalous_fails():
    rows = [(p, s, lv, "ANOMALOUS", "COST_ANOMALY", "OBVIOUS", "") for (p, s, lv, *_r) in ROWS]
    with pytest.raises(M.EvaluationInputError, match="single class"):
        M.prepare(*frames(rows))


# ------------------------------ report / provenance ------------------------ #
def big_frames():
    """ROWS tripled (30 projects) so K=20 is computable; every count scales by 3."""
    return frames([(f"{r[0]}-{c}",) + r[1:] for c in "abc" for r in ROWS])


def _write_eval_dir(tmp_path, tamper=False):
    pred, labels = big_frames()
    labels_path = tmp_path / "evaluation_labels.csv"
    labels.to_csv(labels_path, index=False)
    pred.to_csv(tmp_path / "evaluation_predictions.csv", index=False)
    sha = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    eng = {"engine_input/projects.csv": "abc123"}
    (tmp_path / "evaluation_metadata.json").write_text(json.dumps({"file_sha256": {**eng, "evaluation_labels.csv": sha}}))
    (tmp_path / "evaluation_predictions_meta.json").write_text(json.dumps(
        {"engine_input_sha256": eng, "projects_scored": 30, "frozen_hash_check": "passed"}))
    if tamper:
        labels.loc[0, "ground_truth_label"] = "NORMAL"; labels.loc[0, "scenario_type"] = "NORMAL"
        labels.to_csv(labels_path, index=False)
    return str(tmp_path)


def test_run_writes_deterministic_json_and_markdown(tmp_path):
    d = _write_eval_dir(tmp_path)
    r1 = M.run(d)
    j1 = open(os.path.join(d, "evaluation_report.json"), "rb").read()
    m1 = open(os.path.join(d, "evaluation_report.md"), encoding="utf-8").read()
    M.run(d)
    assert open(os.path.join(d, "evaluation_report.json"), "rb").read() == j1     # deterministic
    parsed = json.loads(j1)
    for key in ("dataset_summary", "ranking", "pr_auc", "thresholded_classification", "scenario_level",
                "adversarial_normal", "top_20", "bootstrap"):
        assert key in parsed
    assert parsed["thresholded_classification"]["primary"]["tp"] == 9      # 3 per copy x 3 copies
    assert parsed["dataset_summary"]["projects"] == 30
    assert parsed["dataset_summary"]["provenance"]["labels_match_frozen_hash"] is True
    for h in ("## 1. Dataset summary", "## 2. Overall metrics", "## 3. Precision@K", "## 4. Thresholded confusion matrix",
              "## 5. PR-AUC", "## 6. Scenario-level results", "## 7. Adversarial-normal results",
              "## 8. Top 20 highest-risk projects", "## 9. Limitations and interpretation notes"):
        assert h in m1
    assert "Thresholded classification at risk_score >= 40" in m1
    assert parsed["pr_auc"]["average_precision"] == pytest.approx(r1["pr_auc"]["average_precision"], abs=1e-6)


def test_run_refuses_when_labels_differ_from_frozen_hash(tmp_path):
    d = _write_eval_dir(tmp_path, tamper=True)
    with pytest.raises(M.EvaluationInputError, match="provenance"):
        M.run(d)
    assert M.run(d, allow_changed=True)["dataset_summary"]["projects"] == 30
    assert M.verify_provenance(d)["labels_match_frozen_hash"] is False


def test_bootstrap_is_seeded_and_reproducible(df):
    a, b = M.bootstrap_intervals(df, n=200), M.bootstrap_intervals(df, n=200)
    assert a == b and a["seed"] == M.BOOTSTRAP_SEED
    lo, hi = a["average_precision_95ci"]
    assert 0.0 <= lo <= hi <= 1.0


# ------------------------------ isolation / integration -------------------- #
def test_metrics_module_does_not_touch_the_engine_or_write_labels():
    tree = ast.parse(open(os.path.join(EVAL_DIR, "evaluation_metrics.py"), encoding="utf-8").read())
    mods, attrs = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
        elif isinstance(n, ast.Attribute):
            attrs.add(n.attr)
    assert not any(m.startswith(("intelligence", "backend", "evaluation.run_v1", "evaluation.generate")) for m in mods)
    assert "to_csv" not in attrs, "metrics module must never rewrite labels or predictions"


@pytest.mark.skipif(not os.path.exists(os.path.join(EVAL_DIR, "evaluation_predictions.csv")),
                    reason="V1 predictions not generated in this checkout")
def test_real_data_invariants_only():
    pred, labels = M.load_csvs(os.path.join(EVAL_DIR, "evaluation_predictions.csv"),
                               os.path.join(EVAL_DIR, "evaluation_labels.csv"))
    rep = M.build_report(pred, labels, M.verify_provenance(EVAL_DIR))
    ds, tc = rep["dataset_summary"], rep["thresholded_classification"]["primary"]
    assert ds["projects"] == 150 and ds["anomalous"] == 49 and ds["normal"] == 101
    assert sum(ds["scenario_counts"].values()) == 150
    assert tc["tp"] + tc["fp"] + tc["tn"] + tc["fn"] == 150 and tc["threshold"] == 40.0
    assert rep["thresholded_classification"]["v1_queue_reference"]["threshold"] == 30.0
    assert 0 < rep["pr_auc"]["average_precision"] <= 1
    assert all(0 <= rep["ranking"][f"precision_at_{k}"]["precision"] <= 1 for k in (5, 10, 20))
    assert rep["adversarial_normal"]["n"] == 41
    assert ds["provenance"]["labels_match_frozen_hash"] and ds["provenance"]["predictions_made_from_frozen_engine_input"]
    assert len(rep["top_20"]) == 20
