"""
V2.3 baseline tests.

Leakage is checked three independent ways:
  1. SOURCE inspection (AST): the baseline modules, and the two prediction-stage functions of the runner, contain
     no reference to labels, planted signals, V1 outputs, or the V2.2 metrics module.
  2. RUNTIME file access: while baselines are produced, only the five documented engine_input tables are read.
  3. BEHAVIOUR: predictions are identical when computed from a bare copy of engine_input/ that has no labels,
     no V1 predictions and no planted signals anywhere beside it; and fit() receives only the feature matrix.

Frozen-file checks compare current hashes with hashes recorded outside this stage (the V1 prediction metadata, the
V2.1 metadata, the V2.2 report). The "unchanged since the baseline run" check compares with the manifest written by
the V2.3 run, so it detects any later edit; it cannot by itself prove the files equal an earlier git commit.
"""
import ast
import hashlib
import json
import os
import shutil
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest

from backend.v2_6_integrity import frozen_diff as v2_6_frozen_diff
from evaluation import evaluation_metrics as M
from evaluation.baselines import cost_baseline as CB
from evaluation.baselines import isolation_forest_baseline as IFB
from evaluation.baselines import run_baselines as RB

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(EVAL_DIR)
BASE_DIR = os.path.join(EVAL_DIR, "baselines")
ENGINE_DIR = os.path.join(EVAL_DIR, "engine_input")

FORBIDDEN = ["ground_truth", "evaluation_labels", "anomaly_signals", "risk_score", "risk_level", "evaluation_predictions",
             "cost_anomaly_score", "project_similarity_score", "contractor_pattern_score", "billing_anomaly_score",
             "geographic_signal_score", "scenario_type", "difficulty", "injected_signals", "group_id",
             "adversarial_subtype", "rationale", "intelligence", "evaluation_metrics", "y_true"]


def _code_tokens(tree):
    """Imports, identifiers, attribute names and non-docstring string constants of an AST."""
    doc_ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) \
                and isinstance(n.body[0].value.value, str):
            doc_ids.add(id(n.body[0].value))
    toks = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            toks += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            toks.append(n.module or "")
            toks += [a.name for a in n.names]
        elif isinstance(n, ast.Name):
            toks.append(n.id)
        elif isinstance(n, ast.Attribute):
            toks.append(n.attr)
        elif isinstance(n, ast.arg):
            toks.append(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids:
            toks.append(n.value)
    return toks


def _hits(toks):
    return sorted({f for f in FORBIDDEN for t in toks if f.lower() in str(t).lower()})


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


@pytest.fixture(scope="module")
def committed():
    return pd.read_csv(os.path.join(EVAL_DIR, "baseline_predictions.csv"), dtype={"project_id": str})


# ------------------------------ output sanity ------------------------------ #
def test_prediction_file_rows_ids_and_scores(committed):
    labels = pd.read_csv(os.path.join(EVAL_DIR, "evaluation_labels.csv"), dtype=str, keep_default_na=False)
    v1 = pd.read_csv(os.path.join(EVAL_DIR, "evaluation_predictions.csv"), dtype={"project_id": str})
    proj = pd.read_csv(os.path.join(ENGINE_DIR, "projects.csv"), dtype=str)
    assert len(committed) == 150 and committed.project_id.is_unique
    assert set(committed.project_id) == set(labels.project_id) == set(v1.project_id) == set(proj.project_id)
    assert list(committed.columns) == ["project_id", CB.SCORE_COLUMN, IFB.SCORE_COLUMN]
    for c in (CB.SCORE_COLUMN, IFB.SCORE_COLUMN):
        assert pd.api.types.is_numeric_dtype(committed[c])
        assert np.isfinite(committed[c].to_numpy()).all() and committed[c].notna().all()
    assert committed.project_id.is_monotonic_increasing, "rows must be in project_id order, not score order"


def test_same_labels_and_projects_as_v2_2():
    rep = json.load(open(os.path.join(EVAL_DIR, "baseline_comparison.json"), encoding="utf-8"))
    d = rep["dataset"]
    assert (d["projects"], d["anomalous"], d["normal"], d["adversarial_normal"]) == (150, 49, 101, 41)
    assert d["same_projects_and_labels_as_v2_2"] is True
    assert d["provenance"]["labels_match_frozen_hash"] and d["provenance"]["predictions_made_from_frozen_engine_input"]
    v22 = json.load(open(os.path.join(EVAL_DIR, "evaluation_report.json"), encoding="utf-8"))
    v1 = rep["approaches"]["NidhiGuard V1"]
    # the V1 numbers inside V2.3 are exactly the V2.2 numbers: same predictions, same labels, same methodology
    assert v1["average_precision"] == pytest.approx(v22["pr_auc"]["average_precision"], abs=1e-6)
    for k in (5, 10, 20):
        assert v1["precision_at_k"][str(k)]["precision"] == pytest.approx(v22["ranking"][f"precision_at_{k}"]["precision"], abs=1e-6)
    assert v1["budgets"]["B"]["tp"] == v22["thresholded_classification"]["primary"]["tp"]
    assert v1["budgets"]["A"]["fp"] == v22["thresholded_classification"]["v1_queue_reference"]["fp"]


# ------------------------------ leakage: source ---------------------------- #
@pytest.mark.parametrize("module", ["cost_baseline.py", "isolation_forest_baseline.py"])
def test_baseline_modules_reference_no_labels_signals_or_v1_outputs(module):
    tree = ast.parse(open(os.path.join(BASE_DIR, module), encoding="utf-8").read())
    assert _hits(_code_tokens(tree)) == [], f"{module} references forbidden inputs"


def test_prediction_stage_functions_reference_no_labels_signals_or_v1_outputs():
    tree = ast.parse(open(os.path.join(BASE_DIR, "run_baselines.py"), encoding="utf-8").read())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("load_engine_tables", "generate_predictions"):
        assert _hits(_code_tokens(fns[name])) == [], name
    # and the stage that DOES read labels is a different function
    assert "evaluation_labels.csv" in " ".join(map(str, _code_tokens(fns["compare"])))


def test_baseline_modules_import_only_label_free_packages():
    for module in ("cost_baseline.py", "isolation_forest_baseline.py"):
        tree = ast.parse(open(os.path.join(BASE_DIR, module), encoding="utf-8").read())
        mods = {t.split(".")[0] for n in ast.walk(tree) for t in (
            [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else [])}
        assert mods <= {"__future__", "numpy", "pandas", "sklearn", "evaluation"}, mods
        evaluation_imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("evaluation")}
        assert evaluation_imports <= {"evaluation.baselines.cost_baseline"}


# ------------------------------ leakage: runtime --------------------------- #
def test_runtime_reads_only_the_five_engine_tables():
    seen, opened = [], []
    real_read, real_open = pd.read_csv, open

    def spy_read(path, *a, **k):
        seen.append(os.path.basename(str(path)))
        return real_read(path, *a, **k)

    def spy_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    with mock.patch("pandas.read_csv", spy_read), mock.patch("builtins.open", spy_open):
        RB.generate_predictions(EVAL_DIR)
    assert sorted(seen) == sorted(f"{t}.csv" for t in RB.ENGINE_TABLES)
    bad = [o for o in opened if any(w in o for w in ("evaluation_labels", "evaluation_predictions", "anomaly_signals", "baseline_predictions"))]
    assert bad == []


def test_predictions_identical_from_bare_engine_input_copy(tmp_path, committed):
    """No labels, no V1 predictions, no planted signals, no metadata exist beside the engine input."""
    shutil.copytree(ENGINE_DIR, tmp_path / "engine_input")
    assert sorted(os.listdir(tmp_path)) == ["engine_input"]
    out = RB.generate_predictions(str(tmp_path))
    pd.testing.assert_frame_equal(out, committed.round(10), check_exact=False, atol=1e-9)


def test_isolation_forest_fit_receives_only_the_feature_matrix():
    t = RB.load_engine_tables(EVAL_DIR)
    feats = IFB.build_features(t["projects"], t["historical_projects"], t["bills"], t["payments"], t["locations"])
    orig = IsolationForest.fit
    with mock.patch.object(IsolationForest, "fit", autospec=True, side_effect=orig) as fit:
        IFB.score(feats)
    assert fit.call_count == 1
    args, kwargs = fit.call_args
    assert len(args) == 2 and kwargs == {}, "fit(self, X) only: no y, no sample_weight"
    X = args[1]
    assert X.shape == (150, len(IFB.FEATURES)) and np.allclose(X, feats.to_numpy())
    assert list(feats.columns) == IFB.FEATURES and len(IFB.FEATURES) == 8
    assert _hits(IFB.FEATURES) == []


def test_isolation_forest_parameters_are_documented_and_label_free():
    p = IFB.IF_PARAMS
    assert p["random_state"] == 2303 and p["contamination"] == "auto" and p["n_estimators"] == 200 and p["n_jobs"] == 1
    meta = json.load(open(os.path.join(EVAL_DIR, "baseline_predictions_meta.json"), encoding="utf-8"))
    assert meta["isolation_forest_baseline"]["parameters"] == p
    assert meta["isolation_forest_baseline"]["random_state"] == 2303
    assert meta["isolation_forest_baseline"]["features"] == IFB.FEATURES
    assert "evaluation_labels.csv" in meta["inputs_never_read_in_this_stage"]
    assert sorted(meta["inputs_read"]) == sorted(f"engine_input/{t}.csv" for t in RB.ENGINE_TABLES)


# ------------------------------ determinism -------------------------------- #
def test_isolation_forest_is_deterministic_with_fixed_random_state():
    t = RB.load_engine_tables(EVAL_DIR)
    feats = IFB.build_features(t["projects"], t["historical_projects"], t["bills"], t["payments"], t["locations"])
    a, b = IFB.score(feats), IFB.score(feats)
    pd.testing.assert_frame_equal(a, b)
    with mock.patch.dict(IFB.IF_PARAMS, {"random_state": 1}):
        c = IFB.score(feats)
    assert not np.allclose(a[IFB.SCORE_COLUMN], c[IFB.SCORE_COLUMN]), "random_state must actually be what controls the result"


def _copy_eval(tmp_path, name):
    dst = tmp_path / name / "evaluation"
    shutil.copytree(EVAL_DIR, dst, ignore=shutil.ignore_patterns("__pycache__", "tests", "baselines"))
    return str(dst)


def test_repeated_execution_is_byte_identical_and_matches_committed(tmp_path):
    d1, d2 = _copy_eval(tmp_path, "run1"), _copy_eval(tmp_path, "run2")
    for d in (d1, d2):
        RB.write_predictions(d)
        RB.compare(d)
    for f in ("baseline_predictions.csv", "baseline_predictions_meta.json", "baseline_comparison.json", "baseline_comparison.md"):
        b1, b2, ref = (open(os.path.join(x, f), "rb").read() for x in (d1, d2, EVAL_DIR))
        assert b1 == b2, f"{f} differs between two runs"
        assert b1 == ref, f"{f} differs from the committed copy"


def test_outputs_are_lf_even_when_text_mode_defaults_to_crlf(tmp_path):
    """Emulates Windows, where open(..., 'w') without newline= translates \\n to \\r\\n."""
    real_open = open

    def windows_like_open(file, mode="r", *args, **kwargs):
        text_write = "w" in mode and "b" not in mode
        explicit = len(args) >= 4 or kwargs.get("newline") is not None or "newline" in kwargs
        if text_write and not explicit:
            kwargs["newline"] = "\r\n"            # os.linesep translation that Python applies on Windows
        return real_open(file, mode, *args, **kwargs)

    d = _copy_eval(tmp_path, "winsim")
    with mock.patch("builtins.open", windows_like_open):
        RB.write_predictions(d)
        RB.compare(d)
    for f in ("baseline_predictions.csv", "baseline_predictions_meta.json", "baseline_comparison.json", "baseline_comparison.md"):
        assert b"\r" not in open(os.path.join(d, f), "rb").read(), f"{f} contains CR bytes: output is not newline-deterministic"


def test_comparison_metrics_reproducible_from_the_saved_predictions():
    rep = json.load(open(os.path.join(EVAL_DIR, "baseline_comparison.json"), encoding="utf-8"))
    labels = pd.read_csv(os.path.join(EVAL_DIR, "evaluation_labels.csv"), dtype=str, keep_default_na=False)
    base = pd.read_csv(os.path.join(EVAL_DIR, "baseline_predictions.csv"), dtype={"project_id": str})
    for name, col in (("Cost-Deviation", CB.SCORE_COLUMN), ("Isolation Forest", IFB.SCORE_COLUMN)):
        df = M.prepare(pd.DataFrame({"project_id": base.project_id, "risk_score": base[col], "risk_level": "n/a"}), labels)
        assert M.pr_auc(df)["average_precision"] == pytest.approx(rep["approaches"][name]["average_precision"], abs=1e-6)
        r = M.rank(df)
        for k in (5, 10, 20):
            assert M.precision_at_k(r, k)["precision"] == pytest.approx(rep["approaches"][name]["precision_at_k"][str(k)]["precision"])


# ------------------------------ frozen files ------------------------------- #
def test_v1_intelligence_unmodified_against_v2_2_recorded_hashes():
    recorded = json.load(open(os.path.join(EVAL_DIR, "evaluation_predictions_meta.json"), encoding="utf-8"))["engine_source_sha256"]
    current = {f: _sha(os.path.join(ROOT, "intelligence", f)) for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py")}
    assert current == recorded


def test_v2_1_dataset_and_labels_unmodified_against_frozen_hashes():
    frozen = json.load(open(os.path.join(EVAL_DIR, "evaluation_metadata.json"), encoding="utf-8"))["file_sha256"]
    assert {k: _sha(os.path.join(EVAL_DIR, k)) for k in frozen} == frozen


def test_v2_2_reference_predictions_unmodified_against_v2_2_report():
    prov = json.load(open(os.path.join(EVAL_DIR, "evaluation_report.json"), encoding="utf-8"))["dataset_summary"]["provenance"]
    assert _sha(os.path.join(EVAL_DIR, "evaluation_predictions.csv")) == prov["predictions_sha256"]
    assert _sha(os.path.join(EVAL_DIR, "evaluation_labels.csv")) == prov["labels_sha256"]


def test_nothing_frozen_changed_since_the_v2_3_run():
    """V1 engine + backend + frontend source, V2.1 dataset/spec, V2.2 metrics/reference outputs.

    The recorded manifest must have been produced by running the V2.3 command in THIS repository; a manifest produced
    on another machine hashes that machine's copies of files such as evaluation_predictions_meta.json (which embeds the
    git commit of the run) and can never match.

    V2.6 note: the recorded V1 backend/frontend group is a historical snapshot and is never regenerated. V2.6 is an
    intentional application-code change after this run, so the files it declares in backend/v2_6_source_manifest.json
    are tolerated in that group only; every other difference (and every other group) is still reported.
    """
    recorded = json.load(open(os.path.join(EVAL_DIR, "baseline_predictions_meta.json"), encoding="utf-8"))["frozen_manifest"]
    now = RB.manifest(EVAL_DIR)
    assert set(recorded) == {"v1_intelligence_source", "v1_backend_and_frontend_source", "v2_1_dataset_and_spec",
                             "v2_2_metrics_and_reference_outputs"}
    differing = v2_6_frozen_diff(recorded, now)
    assert not differing, ("frozen assets differ from the manifest recorded by the V2.3 run; if (and only if) the current files are the "
                           f"intended frozen state, regenerate with `python -m evaluation.baselines.run_baselines --dir evaluation`: {differing}")
    assert any(k.startswith("backend/app/intelligence/") for k in recorded["v1_backend_and_frontend_source"])


def test_manifest_covers_exactly_the_intended_frozen_assets():
    from evaluation.generate_evaluation_data import ENGINE_FILES
    m = RB.manifest(EVAL_DIR)
    intel = sorted(f"intelligence/{f}" for f in os.listdir(os.path.join(ROOT, "intelligence")) if f.endswith(".py"))
    assert sorted(m["v1_intelligence_source"]) == intel and len(intel) >= 10
    walked = sorted(os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, "/")
                    for base in ("backend/app", "src") for dp, _dn, fn in os.walk(os.path.join(ROOT, base))
                    if "__pycache__" not in dp for f in fn)
    assert sorted(m["v1_backend_and_frontend_source"]) == walked and walked
    assert sorted(m["v2_1_dataset_and_spec"]) == sorted(
        [f"evaluation/engine_input/{f}" for f in ENGINE_FILES] + [f"evaluation/{f}" for f in (
            "evaluation_labels.csv", "evaluation_metadata.json", "spec_constants.py", "SCENARIO_SPEC.md",
            "generate_evaluation_data.py", "run_v1_predictions.py")])
    assert sorted(m["v2_2_metrics_and_reference_outputs"]) == [
        "evaluation/evaluation_metrics.py", "evaluation/evaluation_predictions.csv", "evaluation/evaluation_predictions_meta.json"]
    assert not [k for g in m.values() for k in g if "baseline" in k], "V2.3 outputs are not frozen assets"


def test_compare_refuses_if_labels_differ_from_frozen_hash(tmp_path):
    d = _copy_eval(tmp_path, "tamper")
    RB.write_predictions(d)
    path = os.path.join(d, "evaluation_labels.csv")
    before = _sha(path)
    lab = pd.read_csv(path, dtype=str, keep_default_na=False)
    i = lab.index[lab.ground_truth_label == "ANOMALOUS"][0]            # flip a label that really is anomalous
    lab.loc[i, "ground_truth_label"], lab.loc[i, "scenario_type"] = "NORMAL", "NORMAL"
    lab.to_csv(path, index=False)
    assert _sha(path) != before, "the tamper must actually change the file"
    with pytest.raises(M.EvaluationInputError, match="provenance"):
        RB.compare(d)


# ------------------------------ unit tests (synthetic) --------------------- #
def _hist(rows):
    return pd.DataFrame(rows, columns=["work_type", "sanctioned_amount"])


def test_cost_baseline_hand_computed_one_sided_and_label_free():
    hist = _hist([("A", v) for v in (90, 100, 110, 95, 105)] + [("B", v) for v in (180, 200, 220, 190, 210)])
    proj = pd.DataFrame({"project_id": ["P2", "P1", "P3"], "work_type": ["B", "A", "A"], "sanctioned_amount": [100.0, 250.0, 100.0]})
    out = CB.score(proj, hist)
    assert list(out.project_id) == ["P1", "P2", "P3"]                       # sorted by id
    assert out[CB.SCORE_COLUMN].tolist() == pytest.approx([2.5, 0.5, 1.0])    # 250/100, 100/200, 100/100
    assert out.loc[0, CB.SCORE_COLUMN] > out.loc[2, CB.SCORE_COLUMN] > out.loc[1, CB.SCORE_COLUMN]   # cheaper => less anomalous


def test_cost_baseline_refuses_thin_or_missing_benchmarks():
    with pytest.raises(ValueError, match="too few"):
        CB.score(pd.DataFrame({"project_id": ["P1"], "work_type": ["A"], "sanctioned_amount": [1.0]}), _hist([("A", 1.0)] * 4))
    with pytest.raises(ValueError, match="no historical benchmark"):
        CB.score(pd.DataFrame({"project_id": ["P1"], "work_type": ["Z"], "sanctioned_amount": [1.0]}), _hist([("A", 100.0)] * 5))


def _hav(la1, lo1, la2, lo2):
    p1, p2, dl = np.radians(la1), np.radians(la2), np.radians(lo2 - lo1)
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(h))


def test_isolation_forest_features_hand_computed():
    hist = _hist([("A", 100.0)] * 5)
    proj = pd.DataFrame({"project_id": ["P1", "P2", "P3"], "work_type": ["A"] * 3, "contractor_id": ["C1", "C1", "C2"],
                         "sanctioned_amount": [200.0, 100.0, 50.0], "estimated_cost": [100.0, 100.0, 50.0]})
    bills = pd.DataFrame({"project_id": ["P1", "P1", "P2"], "claimed_amount": [30.0, 20.0, 90.0]})
    pays = pd.DataFrame({"project_id": ["P1", "P2", "P2", "P2"]})
    loc = pd.DataFrame({"project_id": ["P1", "P2", "P3"], "latitude": [10.0, 10.0, 11.0], "longitude": [20.0, 20.01, 20.0]})
    f = IFB.build_features(proj, hist, bills, pays, loc)
    assert list(f.index) == ["P1", "P2", "P3"] and list(f.columns) == IFB.FEATURES
    assert f["log_cost_ratio"].tolist() == pytest.approx([np.log(2.0), 0.0, np.log(0.5)])
    assert f["sanction_over_estimate"].tolist() == pytest.approx([2.0, 1.0, 1.0])
    assert f["bill_count"].tolist() == [2, 1, 0] and f["payment_count"].tolist() == [1, 3, 0]
    assert f["billed_over_sanctioned"].tolist() == pytest.approx([0.25, 0.9, 0.0])
    assert f["contractor_project_count"].tolist() == [2, 2, 1]
    assert f["neighbors_within_5km"].tolist() == [1, 1, 0]
    d12 = _hav(10.0, 20.0, 10.0, 20.01)
    d13 = _hav(10.0, 20.0, 11.0, 20.0)
    assert f["nearest_neighbor_km_log1p"].tolist() == pytest.approx([np.log1p(d12), np.log1p(d12), np.log1p(min(d13, _hav(10.0, 20.01, 11.0, 20.0)))], rel=1e-6)


def test_isolation_forest_features_reject_nan_instead_of_imputing():
    hist = _hist([("A", 100.0)] * 5)
    proj = pd.DataFrame({"project_id": ["P1", "P2"], "work_type": ["A", "A"], "contractor_id": ["C1", "C2"],
                         "sanctioned_amount": [100.0, 100.0], "estimated_cost": [np.nan, 100.0]})
    loc = pd.DataFrame({"project_id": ["P1", "P2"], "latitude": [10.0, 10.1], "longitude": [20.0, 20.1]})
    with pytest.raises(ValueError, match="non-finite"):
        IFB.build_features(proj, hist, pd.DataFrame({"project_id": [], "claimed_amount": []}), pd.DataFrame({"project_id": []}), loc)


def test_budgets_are_derived_from_v1_scores_only():
    s = pd.Series([55.5, 41.0, 40.0, 30.0, 29.9, 12.0], index=list("abcdef"))
    b = RB.budgets_from_v1(s)
    assert b["A"]["size"] == 4 and b["B"]["size"] == 3        # >= 30 and >= 40, boundary inclusive
    with pytest.raises(ValueError):
        RB.budgets_from_v1(pd.Series([10.0, 20.0]))


def test_paired_bootstrap_is_seeded_and_directional():
    rng = np.random.default_rng(0)
    y = np.array([1] * 20 + [0] * 40)
    good = y + rng.normal(0, 0.2, len(y))
    rand = rng.normal(0, 1, len(y))
    a, b = RB.paired_bootstrap_delta_ap(y, good, rand, n=300), RB.paired_bootstrap_delta_ap(y, good, rand, n=300)
    assert a == b and a["mean_delta_ap"] > 0.3 and a["ci95"][0] > 0
    assert RB.paired_bootstrap_delta_ap(y, rand, good, n=300)["mean_delta_ap"] < 0


def test_overlap_groups_hand_computed():
    ids = [f"P{i}" for i in range(1, 9)]
    ref = pd.DataFrame({"project_id": ids, "y_true": [1, 1, 1, 1, 1, 0, 0, 0],
                        "scenario_type": ["COST_ANOMALY", "COST_ANOMALY", "SIMILAR_PROJECT", "MULTI_SIGNAL", "BILLING_ANOMALY",
                                          "NORMAL", "ADVERSARIAL_NORMAL", "ADVERSARIAL_NORMAL"],
                        "adversarial_subtype": ["", "", "", "", "", "", "C", "A"]})
    dfs = {RB.V1: ref, RB.COST: ref, RB.IFO: ref}
    flagged = {RB.V1: {"A": {"P1", "P3", "P4", "P7"}}, RB.COST: {"A": {"P1", "P2", "P4", "P7", "P8"}}, RB.IFO: {"A": {"P4", "P5", "P6"}}}
    o = RB.overlap(dfs, flagged, "A")
    assert o["cost_catches_that_v1_misses"]["project_ids"] == ["P2"]
    assert o["isolation_forest_catches_that_v1_misses"]["project_ids"] == ["P5"]
    assert o["v1_catches_that_both_baselines_miss"]["project_ids"] == ["P3"]
    assert o["all_three_catch"]["project_ids"] == ["P4"]
    assert o["missed_by_all_three"]["project_ids"] == []
    assert o["adversarial_normals_flagged"][RB.V1]["project_ids"] == ["P7"]
    assert o["adversarial_normals_flagged"][RB.COST]["subtypes"] == {"P7": "C", "P8": "A"}
    assert o["adversarial_normals_flagged"][RB.IFO]["count"] == 0


# ------------------------------ report wording ----------------------------- #
def test_report_wording_and_structure():
    md = open(os.path.join(EVAL_DIR, "baseline_comparison.md"), encoding="utf-8").read()
    for h in ("# V2.3 Baseline Comparison", "## Objective", "## Dataset", "## Methods", "### NidhiGuard V1", "### Cost-Deviation Baseline",
              "### Isolation Forest", "## Results", "## Precision@K", "## PR-AUC", "## Recall", "## Adversarial Normal Analysis",
              "## Where NidhiGuard Wins", "## Where NidhiGuard Loses", "## Interpretation", "## Limitations", "## Conclusion"):
        assert h in md, h
    assert "**49 anomalous**" in md and "**101 normal**" in md and "**41 are adversarial normals**" in md
    assert "not accuracy" in md and "On this independent synthetic evaluation set," in md
    assert "proven" not in md.lower() or "not proven" in md.lower()
    for lim in ("synthetic", "not real-world fraud-detection validation", "no real investigation outcomes", "depend on feature selection",
                "does not establish production effectiveness"):
        assert lim in md
    assert "Supplementary optimistic bootstrap interval; row resampling does not account for linked synthetic scenario groups." in md
