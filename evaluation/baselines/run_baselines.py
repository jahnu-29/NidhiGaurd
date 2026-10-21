"""
NidhiGuard V2.3 - baseline comparison runner.

Two strictly separated stages:

  Stage 1  generate_predictions()   reads ONLY engine_input/{projects,historical_projects,bills,payments,locations}.csv
                                    and writes baseline_predictions.csv + baseline_predictions_meta.json.
                                    It never opens labels, V1 predictions, V1 outputs or planted signals.
  Stage 2  compare()                reads the labels, the frozen V1 reference predictions and the stage-1 baseline
                                    predictions, and writes baseline_comparison.json / .md using the V2.2 metrics
                                    (evaluation/evaluation_metrics.py, imported, not modified).

Usage (repo root):
    python -m evaluation.baselines.run_baselines --dir evaluation

Evaluation only: nothing here modifies V1, the dataset, the labels, the V1 predictions or the V2.2 metrics.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import platform
import sys

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import average_precision_score

from evaluation import evaluation_metrics as M
from evaluation.baselines import cost_baseline, isolation_forest_baseline

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENGINE_TABLES = ("projects", "historical_projects", "bills", "payments", "locations")
V1 = "NidhiGuard V1"
COST = "Cost-Deviation"
IFO = "Isolation Forest"
APPROACHES = (V1, COST, IFO)
BOOTSTRAP_SEED = 20262303
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_LABEL = ("Supplementary optimistic bootstrap interval; row resampling does not account for "
                   "linked synthetic scenario groups.")
RECALL_LABEL = "Recall@20 (anomalous projects in the top 20 / all anomalous)"


# --------------------------------------------------------------------------- #
# Stage 1 - label-free baseline predictions
# --------------------------------------------------------------------------- #
def load_engine_tables(eval_dir: str) -> dict:
    eng = os.path.join(eval_dir, "engine_input")
    return {t: pd.read_csv(os.path.join(eng, f"{t}.csv"), dtype={"project_id": str}) for t in ENGINE_TABLES}


def generate_predictions(eval_dir: str) -> pd.DataFrame:
    """Compute both baseline scores from the engine input only. One row per project, sorted by project_id."""
    t = load_engine_tables(eval_dir)
    cost = cost_baseline.score(t["projects"], t["historical_projects"])
    feats = isolation_forest_baseline.build_features(t["projects"], t["historical_projects"], t["bills"],
                                                     t["payments"], t["locations"])
    iso = isolation_forest_baseline.score(feats)
    out = cost.merge(iso, on="project_id", how="inner", validate="one_to_one")
    if len(out) != len(t["projects"]):
        raise ValueError("baseline score tables do not cover the same projects")
    for c in (cost_baseline.SCORE_COLUMN, isolation_forest_baseline.SCORE_COLUMN):
        out[c] = out[c].astype(float).round(10)
        if not np.isfinite(out[c]).all():
            raise ValueError(f"non-finite values in {c}")
    return out.sort_values("project_id").reset_index(drop=True)


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _write_text(path: str, text: str) -> None:
    """Write generated text with LF newlines and UTF-8 on every platform (Windows text mode would emit CRLF)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def manifest(eval_dir: str) -> dict:
    """Hashes of everything V2.3 must not change: V1 engine/backend/frontend source, V2.1 dataset/spec, V2.2 metrics + reference outputs."""
    rel_root = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")
    rel_eval = lambda p: "evaluation/" + os.path.relpath(p, eval_dir).replace(os.sep, "/")
    py = lambda pattern: sorted(f for f in glob.glob(os.path.join(ROOT, pattern), recursive=True) if "__pycache__" not in f and os.path.isfile(f))
    v1_other = [f for pat in ("backend/app/**/*", "src/**/*") for f in py(pat)]
    eval_files = lambda names: [os.path.join(eval_dir, f) for f in names]
    return {
        "v1_intelligence_source": {rel_root(p): _sha(p) for p in py("intelligence/*.py")},
        "v1_backend_and_frontend_source": {rel_root(p): _sha(p) for p in v1_other},
        "v2_1_dataset_and_spec": {rel_eval(p): _sha(p) for p in sorted(glob.glob(os.path.join(eval_dir, "engine_input", "*.csv"))) + eval_files(
            ("evaluation_labels.csv", "evaluation_metadata.json", "spec_constants.py", "SCENARIO_SPEC.md",
             "generate_evaluation_data.py", "run_v1_predictions.py"))},
        "v2_2_metrics_and_reference_outputs": {rel_eval(p): _sha(p) for p in eval_files(
            ("evaluation_metrics.py", "evaluation_predictions.csv", "evaluation_predictions_meta.json"))},
    }


def build_meta(eval_dir: str, preds: pd.DataFrame) -> dict:
    with open(os.path.join(eval_dir, "evaluation_metadata.json"), encoding="utf-8") as fh:
        frozen = json.load(fh)["file_sha256"]
    return {
        "stage": "V2.3 baseline predictions (label-free)",
        "number_of_projects": int(len(preds)),
        "score_columns": {cost_baseline.SCORE_COLUMN: "higher = more anomalous",
                          isolation_forest_baseline.SCORE_COLUMN: "higher = more anomalous"},
        "evaluation_dataset_identifier": {"dataset_version": "2.1.0-eval",
                                          "engine_input_sha256": {k: v for k, v in frozen.items() if k.startswith("engine_input/")}},
        "inputs_read": [f"engine_input/{t}.csv" for t in ENGINE_TABLES],
        "inputs_never_read_in_this_stage": ["evaluation_labels.csv", "evaluation_predictions.csv (V1 reference)",
                                            "engine_input/anomaly_signals.csv", "any V1 detector output"],
        "cost_deviation_baseline": {"method": cost_baseline.METHOD_DESCRIPTION,
                                    "min_historical_per_work_type": cost_baseline.MIN_HISTORICAL_PER_WORK_TYPE},
        "isolation_forest_baseline": {
            "features": isolation_forest_baseline.FEATURES,
            "feature_purpose": isolation_forest_baseline.FEATURE_PURPOSE,
            "preprocessing": isolation_forest_baseline.PREPROCESSING,
            "missing_value_handling": "none present; NaN/inf raises (no imputation)",
            "categorical_encoding": "none",
            "parameters": isolation_forest_baseline.IF_PARAMS,
            "random_state": isolation_forest_baseline.RANDOM_STATE,
            "contamination_setting": "auto (no anomaly prevalence assumed)",
            "fit_data": "the 150 evaluation projects themselves, unsupervised (transductive); no target passed to fit()",
        },
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                        "scikit_learn": sklearn.__version__},
        "frozen_manifest": manifest(eval_dir),
        "note": "No timestamp is stored so that repeated runs produce byte-identical files.",
    }


def write_predictions(eval_dir: str) -> pd.DataFrame:
    preds = generate_predictions(eval_dir)
    _write_text(os.path.join(eval_dir, "baseline_predictions.csv"), preds.to_csv(index=False, lineterminator="\n"))
    _write_text(os.path.join(eval_dir, "baseline_predictions_meta.json"), json.dumps(build_meta(eval_dir, preds), indent=2) + "\n")
    return preds


# --------------------------------------------------------------------------- #
# Stage 2 - comparison (labels are read here, and only here)
# --------------------------------------------------------------------------- #
def _frame(scores: pd.Series, levels: pd.Series | None = None) -> pd.DataFrame:
    out = pd.DataFrame({"project_id": scores.index.astype(str), "risk_score": scores.to_numpy(dtype=float)})
    out["risk_level"] = levels.reindex(scores.index).to_numpy() if levels is not None else "n/a"
    return out


def score_distribution(s: pd.Series) -> dict:
    q = s.quantile([0.25, 0.5, 0.75])
    return {"min": float(s.min()), "p25": float(q[0.25]), "median": float(q[0.5]), "mean": float(s.mean()),
            "p75": float(q[0.75]), "max": float(s.max()), "std": float(s.std(ddof=0))}


def budgets_from_v1(v1_scores: pd.Series) -> dict:
    """Label-free alert budgets taken from V1's own output: how many projects V1 flags at its two cutoffs."""
    a, b = int((v1_scores >= M.V1_QUEUE_THRESHOLD).sum()), int((v1_scores >= M.PRIMARY_THRESHOLD).sum())
    if a < 1 or b < 1:
        raise ValueError("V1 flags no projects at one of the cutoffs; matched-budget analysis undefined")
    return {"A": {"size": a, "definition": f"number of projects V1 scores at or above its LOW/MEDIUM boundary (risk_score >= {M.V1_QUEUE_THRESHOLD:g})"},
            "B": {"size": b, "definition": f"number of projects V1 scores at or above the V2.2 evaluation threshold (risk_score >= {M.PRIMARY_THRESHOLD:g})"}}


def _cutoffs(name: str, ranked: pd.DataFrame, budgets: dict) -> dict:
    if name == V1:           # V1 uses its own native cutoffs
        return {"A": M.V1_QUEUE_THRESHOLD, "B": M.PRIMARY_THRESHOLD}
    return {k: float(ranked.risk_score.iloc[v["size"] - 1]) for k, v in budgets.items()}


def evaluate_approach(name: str, pred: pd.DataFrame, labels: pd.DataFrame, budgets: dict) -> tuple:
    df = M.prepare(pred, labels)
    ranked = M.rank(df)
    n_pos = int(df.y_true.sum())
    cut = _cutoffs(name, ranked, budgets)
    pk = {k: M.precision_at_k(ranked, k) for k in M.TOP_K}
    ap = M.pr_auc(df)
    df = df.assign(pct_rank=df.risk_score.rank(pct=True, method="average"))
    sc = M.scenario_table(df, threshold=cut["B"], q_threshold=cut["A"])
    scen = {}
    for s, e in sc.items():
        g = df[df.scenario_type == s]
        scen[s] = {"n": e["n"], "n_anomalous": e["n_anomalous"], "mean_score": e["mean"], "max_score": e["max"],
                   "mean_percentile_rank": float(g.pct_rank.mean()) if len(g) else None,
                   "flagged_at_budget_A": e["n_at_or_above_v1_queue"], "rate_at_budget_A": e["rate_at_or_above_v1_queue"],
                   "flagged_at_budget_B": e["n_at_or_above_primary"], "rate_at_budget_B": e["rate_at_or_above_primary"],
                   "rate_meaning": e["rate_meaning"]}
    adv = M.adversarial_analysis(df, threshold=cut["B"], q_threshold=cut["A"])
    adv_out = {"n": adv["n"], "mean_percentile_rank": float(df[df.scenario_type == "ADVERSARIAL_NORMAL"].pct_rank.mean()),
               "false_positives_at_budget_A": adv["n_at_or_above_v1_queue"], "fp_rate_at_budget_A": adv["false_positive_rate_v1_queue"],
               "false_positives_at_budget_B": adv["n_at_or_above_primary"], "fp_rate_at_budget_B": adv["false_positive_rate_primary"],
               "by_subtype": {st: {"n": e["n"], "flagged_at_budget_A": e["n_at_or_above_v1_queue"],
                                   "flagged_at_budget_B": e["n_at_or_above_primary"], "mean_score": e["mean"], "max_score": e["max"]}
                              for st, e in adv.get("by_subtype", {}).items()}}
    bud = {}
    for k in ("A", "B"):
        t = M.thresholded(df, cut[k])
        t.pop("rule", None); t.pop("note", None)
        bud[k] = {"cutoff_score": cut[k], "flagged": t["predicted_positive"], **t}
    summary = {
        "score_distribution": score_distribution(df.risk_score),
        "average_precision": ap["average_precision"], "trapezoid_auc": ap["trapezoid_auc"], "random_baseline": ap["random_baseline"],
        "precision_at_k": {str(k): v for k, v in pk.items()},
        "r_precision": M.precision_at_k(ranked, n_pos),
        "budgets": bud, "adversarial_normal": adv_out, "scenario_level": scen,
        "top_20": M.top_n(ranked, 20),
    }
    flagged = {k: set(df.loc[df.risk_score >= cut[k], "project_id"]) for k in ("A", "B")}
    return summary, df, flagged


def paired_bootstrap_delta_ap(y: np.ndarray, a: np.ndarray, b: np.ndarray, n: int = BOOTSTRAP_RESAMPLES,
                              seed: int = BOOTSTRAP_SEED) -> dict:
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        yb = y[idx]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        d.append(average_precision_score(yb, a[idx]) - average_precision_score(yb, b[idx]))
    d = np.asarray(d)
    return {"mean_delta_ap": float(d.mean()), "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_resamples_first_better": float((d > 0).mean()), "resamples_used": int(len(d)), "label": BOOTSTRAP_LABEL}


def overlap(dfs: dict, flagged: dict, key: str) -> dict:
    """Which anomalies each method catches at a matched alert budget; which adversarial normals each wrongly flags."""
    ref = dfs[V1].set_index("project_id")
    anom = set(ref.index[ref.y_true == 1])
    f = {n: flagged[n][key] & anom for n in APPROACHES}
    scen = ref.scenario_type

    def pack(ids):
        ids = sorted(ids)
        by = {}
        for i in ids:
            by[scen[i]] = by.get(scen[i], 0) + 1
        return {"count": len(ids), "by_scenario": dict(sorted(by.items())), "project_ids": ids}

    adv_ids = set(ref.index[ref.scenario_type == "ADVERSARIAL_NORMAL"])
    out = {
        "cost_catches_that_v1_misses": pack(f[COST] - f[V1]),
        "isolation_forest_catches_that_v1_misses": pack(f[IFO] - f[V1]),
        "v1_catches_that_both_baselines_miss": pack(f[V1] - f[COST] - f[IFO]),
        "all_three_catch": pack(f[V1] & f[COST] & f[IFO]),
        "missed_by_all_three": pack(anom - f[V1] - f[COST] - f[IFO]),
        "adversarial_normals_flagged": {}}
    for n in APPROACHES:
        ids = sorted(flagged[n][key] & adv_ids)
        out["adversarial_normals_flagged"][n] = {"count": len(ids), "project_ids": ids,
                                                 "subtypes": {i: ref.loc[i, "adversarial_subtype"] for i in ids}}
    return out


def wins_losses(res: dict) -> dict:
    """Derived mechanically from the numbers (no hand-written claims)."""
    out = {"metrics": {"v1_better": [], "v1_worse": [], "v1_equal": []},
           "scenarios_at_budget_A": {"v1_detects_more_than_both": [], "v1_ties_best": [], "v1_detects_less_than_a_baseline": []},
           "adversarial_false_positives_at_budget_A": {}}
    metrics = {"average_precision": lambda r: r["average_precision"], "precision_at_5": lambda r: r["precision_at_k"]["5"]["precision"],
               "precision_at_10": lambda r: r["precision_at_k"]["10"]["precision"], "precision_at_20": lambda r: r["precision_at_k"]["20"]["precision"]}
    for m, fn in metrics.items():
        for b in (COST, IFO):
            v, o = fn(res[V1]), fn(res[b])
            bucket = "v1_better" if v > o + 1e-12 else "v1_worse" if v < o - 1e-12 else "v1_equal"
            out["metrics"][bucket].append({"metric": m, "against": b, "v1": v, "baseline": o})
    for sc in M.ANOMALOUS_SCENARIOS:
        v = res[V1]["scenario_level"][sc]["flagged_at_budget_A"]
        c, i = res[COST]["scenario_level"][sc]["flagged_at_budget_A"], res[IFO]["scenario_level"][sc]["flagged_at_budget_A"]
        row = {"scenario": sc, V1: v, COST: c, IFO: i, "n": res[V1]["scenario_level"][sc]["n"]}
        if v > max(c, i):
            out["scenarios_at_budget_A"]["v1_detects_more_than_both"].append(row)
        elif v == max(c, i):
            out["scenarios_at_budget_A"]["v1_ties_best"].append(row)
        else:
            out["scenarios_at_budget_A"]["v1_detects_less_than_a_baseline"].append(row)
    out["adversarial_false_positives_at_budget_A"] = {n: res[n]["adversarial_normal"]["false_positives_at_budget_A"] for n in APPROACHES}
    return out


def _round(o, nd=6):
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if math.isnan(float(o)) else round(float(o), nd)
    if isinstance(o, np.integer):
        return int(o)
    return o


def compare(eval_dir: str) -> dict:
    prov = M.verify_provenance(eval_dir)
    if not (prov["labels_match_frozen_hash"] and prov["predictions_made_from_frozen_engine_input"]):
        raise M.EvaluationInputError(f"provenance check failed; refusing to compare: {prov}")
    with open(os.path.join(eval_dir, "evaluation_metadata.json"), encoding="utf-8") as fh:
        frozen = json.load(fh)["file_sha256"]
    with open(os.path.join(eval_dir, "baseline_predictions_meta.json"), encoding="utf-8") as fh:
        bmeta = json.load(fh)
    if bmeta["evaluation_dataset_identifier"]["engine_input_sha256"] != {k: v for k, v in frozen.items() if k.startswith("engine_input/")}:
        raise M.EvaluationInputError("baseline predictions were not made from the frozen engine input")

    v1_pred, labels = M.load_csvs(os.path.join(eval_dir, "evaluation_predictions.csv"), os.path.join(eval_dir, "evaluation_labels.csv"))
    base = pd.read_csv(os.path.join(eval_dir, "baseline_predictions.csv"), dtype={"project_id": str})
    v1_scores = v1_pred.set_index("project_id")["risk_score"]
    budgets = budgets_from_v1(v1_scores)
    frames = {V1: v1_pred,
              COST: _frame(base.set_index("project_id")[cost_baseline.SCORE_COLUMN]),
              IFO: _frame(base.set_index("project_id")[isolation_forest_baseline.SCORE_COLUMN])}

    res, dfs, flagged = {}, {}, {}
    for n in APPROACHES:
        res[n], dfs[n], flagged[n] = evaluate_approach(n, frames[n], labels, budgets)

    ids = sorted(dfs[V1].project_id)
    if any(sorted(dfs[n].project_id) != ids for n in APPROACHES):
        raise M.EvaluationInputError("approaches were not evaluated on identical project sets")
    y = dfs[V1].set_index("project_id").loc[ids, "y_true"].to_numpy()
    s = {n: dfs[n].set_index("project_id").loc[ids, "risk_score"].to_numpy() for n in APPROACHES}
    ds = dfs[V1]
    comp = res[V1]["scenario_level"]
    v1_comp = ds.groupby("scenario_type")[[c for c in M.COMPONENT_COLUMNS if c in ds.columns]].mean()
    report = {
        "dataset": {"projects": int(len(ds)), "anomalous": int(ds.y_true.sum()), "normal": int((ds.y_true == 0).sum()),
                    "adversarial_normal": int((ds.scenario_type == "ADVERSARIAL_NORMAL").sum()),
                    "scenario_counts": {k: v["n"] for k, v in comp.items()},
                    "multi_signal_cases": int((ds.scenario_type == "MULTI_SIGNAL").sum()),
                    "multi_signal_with_cost_inflation": int(((ds.scenario_type == "MULTI_SIGNAL") & ds.injected_signals.str.contains("COST_INFLATION")).sum()),
                    "same_projects_and_labels_as_v2_2": True, "provenance": prov},
        "alert_budgets": budgets,
        "alert_budget_note": "Budgets come from V1's own outputs (never from labels). Baselines flag their top-N projects "
                             "(score >= the N-th highest score) so each method reviews the same number of projects as V1.",
        "approaches": res,
        "comparison_table": [{"approach": n, "average_precision": res[n]["average_precision"],
                              "precision_at_5": res[n]["precision_at_k"]["5"]["precision"],
                              "precision_at_10": res[n]["precision_at_k"]["10"]["precision"],
                              "precision_at_20": res[n]["precision_at_k"]["20"]["precision"],
                              "recall_at_20": res[n]["precision_at_k"]["20"]["recall_at_k"]} for n in APPROACHES],
        "recall_definition": RECALL_LABEL,
        "paired_bootstrap_delta_average_precision": {
            f"{a} minus {b}": paired_bootstrap_delta_ap(y, s[a], s[b]) for a, b in ((V1, COST), (V1, IFO), (COST, IFO))},
        "overlap": {"budget_A": overlap(dfs, flagged, "A"), "budget_B": overlap(dfs, flagged, "B")},
        "wins_losses": wins_losses(res),
        "v1_mean_component_scores_by_scenario": {k: {c: float(v) for c, v in row.items()} for k, row in v1_comp.iterrows()},
        "baseline_metadata": {"isolation_forest_features": bmeta["isolation_forest_baseline"]["features"],
                              "isolation_forest_parameters": bmeta["isolation_forest_baseline"]["parameters"],
                              "cost_deviation_method": bmeta["cost_deviation_baseline"]["method"]},
    }
    report = _round(report)
    _write_text(os.path.join(eval_dir, "baseline_comparison.json"), json.dumps(report, indent=2) + "\n")
    _write_text(os.path.join(eval_dir, "baseline_comparison.md"), render_markdown(report))
    return report



# --------------------------------------------------------------------------- #
# Markdown report (all prose is generated from the computed numbers)
# --------------------------------------------------------------------------- #
def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_markdown(r: dict) -> str:
    ap, d, bud = r["approaches"], r["dataset"], r["alert_budgets"]
    A, B = bud["A"]["size"], bud["B"]["size"]
    L = []
    w = L.append
    w("# V2.3 Baseline Comparison\n")
    w("_Controlled synthetic evaluation. Nothing was tuned: NidhiGuard V1, the dataset, the labels and the V2.2 metrics are unchanged._\n")
    w("## Objective\n")
    w("Test whether NidhiGuard's multi-detector engine adds value beyond two simpler approaches, evaluated on exactly the same "
      "frozen V2.1 evaluation projects and labels as V2.2: (1) a cost-deviation score, which shows how much cost alone explains, and "
      "(2) a generic Isolation Forest, a standard unsupervised anomaly detector. The result is reported whichever way it falls.\n")
    w("## Dataset\n")
    w(f"{d['projects']} independent evaluation projects: **{d['anomalous']} anomalous**, **{d['normal']} normal**, of which "
      f"**{d['adversarial_normal']} are adversarial normals** (legitimate look-alikes, counted as normal). "
      f"Verified from the files: labels match their frozen hash ({d['provenance']['labels_match_frozen_hash']}); baseline and V1 predictions "
      f"were made from the frozen engine input ({d['provenance']['predictions_made_from_frozen_engine_input']}); all three approaches cover the same "
      f"{d['projects']} project IDs. Scenario counts: " + ", ".join(f"{k} {v}" for k, v in d["scenario_counts"].items()) + ".\n")
    w("## Methods\n")
    w("### NidhiGuard V1\n")
    w("The frozen reference system: five deterministic detectors (cost, similarity, contractor, billing, geographic) combined into a 0-100 risk score. "
      "Its predictions are the unchanged V2.2 file `evaluation_predictions.csv`.\n")
    w("### Cost-Deviation Baseline\n")
    w(f"`score = sanctioned_amount / median(historical sanctioned_amount of the same work type)`. {r['baseline_metadata']['cost_deviation_method']} "
      "It is the same idea family as V1's cost detector by design (to isolate what cost alone explains), but simpler: no state adjustment, "
      "historical table only, no group-size logic beyond a sanity floor, no scaling. It does not look at estimates, bills, contractors or locations.\n")
    w("### Isolation Forest\n")
    prm = r["baseline_metadata"]["isolation_forest_parameters"]
    w("Unsupervised `sklearn.ensemble.IsolationForest`, fitted on the 150 evaluation projects without any labels, V1 output or planted signal. "
      f"Parameters: n_estimators={prm['n_estimators']}, max_samples={prm['max_samples']}, contamination={prm['contamination']} "
      f"(no anomaly prevalence assumed), random_state={prm['random_state']}, n_jobs={prm['n_jobs']}. Score = -score_samples (higher = more anomalous). "
      "No scaling or categorical encoding (tree splits are scale-invariant); no imputation (NaN/inf would raise). Features were fixed before any result was seen:\n")
    w("| Feature | Why it is a defensible generic feature |\n|---|---|")
    from evaluation.baselines import isolation_forest_baseline as _ifb
    for ft in r["baseline_metadata"]["isolation_forest_features"]:
        w(f"| `{ft}` | {_ifb.FEATURE_PURPOSE[ft]} |")
    w("\nDeliberately excluded: work type/state/category, planned duration, approved/actual amounts, dates, contractor attributes, descriptions.\n")
    w("### Thresholded comparison: matched alert budgets\n")
    w(f"The baselines have no native threshold, and V1's thresholds do not transfer to other score scales. So thresholded results use a label-free matched budget taken from V1's own output: "
      f"**Budget A = {A}** ({bud['A']['definition']}) and **Budget B = {B}** ({bud['B']['definition']}). Each baseline flags its top-{A} / top-{B} projects, "
      "so every method reviews the same number of projects. No threshold was chosen from labels.\n")

    w("## Results\n")
    w(f"| Approach | PR-AUC (average precision) | Precision@5 | Precision@10 | Precision@20 | {RECALL_LABEL} |\n|---|--:|--:|--:|--:|--:|")
    for t in r["comparison_table"]:
        w(f"| {t['approach']} | {_f(t['average_precision'])} | {_f(t['precision_at_5'], 2)} | {_f(t['precision_at_10'], 2)} | {_f(t['precision_at_20'], 2)} | {_f(t['recall_at_20'])} |")
    base = ap[V1]["random_baseline"]
    w(f"\nPR-AUC is a ranking-quality measure, not accuracy. Random ranking gives precision = prevalence = {_f(base)}. Ranking metrics compare the continuous scores directly.\n")
    w("| Approach | Budget | Flagged | TP | FP | FN | Precision | Recall | F1 |\n|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for n in APPROACHES:
        for k in ("A", "B"):
            b = ap[n]["budgets"][k]
            tag = f"A ({A})" if k == "A" else f"B ({B})"
            native = f" (V1 native cutoff {_f(b['cutoff_score'], 0)})" if n == V1 else ""
            w(f"| {n}{native} | {tag} | {b['flagged']} | {b['tp']} | {b['fp']} | {b['fn']} | {_f(b['precision'])} | {_f(b['recall'])} | {_f(b['f1'])} |")
    w("")
    w("## Precision@K\n")
    w("| Approach | Anomalous in top 5 | Precision@5 | Anomalous in top 10 | Precision@10 | Anomalous in top 20 | Precision@20 |\n|---|--:|--:|--:|--:|--:|--:|")
    for n in APPROACHES:
        pk = ap[n]["precision_at_k"]
        w(f"| {n} | {pk['5']['anomalous_in_top_k']} | {_f(pk['5']['precision'], 2)} | {pk['10']['anomalous_in_top_k']} | {_f(pk['10']['precision'], 2)} | "
          f"{pk['20']['anomalous_in_top_k']} | {_f(pk['20']['precision'], 2)} |")
    w("\nRanking: risk/anomaly score descending, project_id ascending for ties.\n")
    w("## PR-AUC\n")
    w("| Approach | Average precision | Trapezoid AUC | Random baseline |\n|---|--:|--:|--:|")
    for n in APPROACHES:
        w(f"| {n} | {_f(ap[n]['average_precision'])} | {_f(ap[n]['trapezoid_auc'])} | {_f(ap[n]['random_baseline'])} |")
    w("\nPaired bootstrap of the difference in average precision (same resampled projects for both methods):\n")
    for k, v in r["paired_bootstrap_delta_average_precision"].items():
        lo, hi = v["ci95"]
        w(f"- {k}: {v['mean_delta_ap']:+.3f}, interval [{lo:+.3f}, {hi:+.3f}]; first better in {v['share_resamples_first_better']:.0%} of resamples.")
    w(f"\n_{BOOTSTRAP_LABEL}_\n")
    w("## Recall\n")
    w(f"| Approach | {RECALL_LABEL} | Recall at budget A ({A}) | Recall at budget B ({B}) | Precision@{d['anomalous']} (R-precision) |\n|---|--:|--:|--:|--:|")
    for n in APPROACHES:
        w(f"| {n} | {_f(ap[n]['precision_at_k']['20']['recall_at_k'])} | {_f(ap[n]['budgets']['A']['recall'])} | {_f(ap[n]['budgets']['B']['recall'])} | {_f(ap[n]['r_precision']['precision'])} |")
    w("")
    w("## Adversarial Normal Analysis\n")
    w(f"Adversarial normals are legitimate look-alikes (ADV-A large portfolio, ADV-B nearby unrelated works, ADV-C high cost with corroborating estimate, ADV-D milestone billing, ADV-E similar wording only), counted as NORMAL. "
      f"A flagged adversarial normal is a false positive. Counts are at matched budgets A ({A}) and B ({B}).\n")
    w("| Approach | Adversarial n | FP at A | FP rate at A | FP at B | FP rate at B | Mean percentile rank |\n|---|--:|--:|--:|--:|--:|--:|")
    for n in APPROACHES:
        a = ap[n]["adversarial_normal"]
        w(f"| {n} | {a['n']} | {a['false_positives_at_budget_A']} | {_f(a['fp_rate_at_budget_A'])} | {a['false_positives_at_budget_B']} | {_f(a['fp_rate_at_budget_B'])} | {_f(a['mean_percentile_rank'], 2)} |")
    subs = sorted(ap[V1]["adversarial_normal"]["by_subtype"])
    w("\nFlagged at budget A, by subtype:\n")
    w("| Approach | " + " | ".join(f"ADV-{s} (n={ap[V1]['adversarial_normal']['by_subtype'][s]['n']})" for s in subs) + " |\n|---|" + "--:|" * len(subs))
    for n in APPROACHES:
        w(f"| {n} | " + " | ".join(str(ap[n]["adversarial_normal"]["by_subtype"][s]["flagged_at_budget_A"]) for s in subs) + " |")
    w("")
    w("## Scenario-level detection\n")
    w(f"Projects flagged at budget A ({A}) per scenario (for NORMAL and ADVERSARIAL_NORMAL these are false positives), and mean percentile rank (1.0 = top-ranked) which is comparable across score scales.\n")
    w("| Scenario | n | V1 flagged | Cost flagged | IF flagged | V1 mean pct | Cost mean pct | IF mean pct |\n|---|--:|--:|--:|--:|--:|--:|--:|")
    for sc in M.SCENARIO_ORDER:
        e = {n: ap[n]["scenario_level"][sc] for n in APPROACHES}
        w(f"| {sc} | {e[V1]['n']} | {e[V1]['flagged_at_budget_A']} | {e[COST]['flagged_at_budget_A']} | {e[IFO]['flagged_at_budget_A']} | "
          f"{_f(e[V1]['mean_percentile_rank'], 2)} | {_f(e[COST]['mean_percentile_rank'], 2)} | {_f(e[IFO]['mean_percentile_rank'], 2)} |")
    w("")
    w("## Overlap between methods\n")
    ov = r["overlap"]["budget_A"]
    w(f"Anomalous projects caught (inside the top-{A} / V1's flagged set) by each method; IDs are in `baseline_comparison.json`.\n")
    w("| Group | Count | By scenario |\n|---|--:|---|")
    for key, label in (("cost_catches_that_v1_misses", "Cost baseline catches, V1 misses"), ("isolation_forest_catches_that_v1_misses", "Isolation Forest catches, V1 misses"),
                       ("v1_catches_that_both_baselines_miss", "V1 catches, both baselines miss"), ("all_three_catch", "All three catch"),
                       ("missed_by_all_three", "Missed by all three")):
        w(f"| {label} | {ov[key]['count']} | {', '.join(f'{s} {c}' for s, c in ov[key]['by_scenario'].items()) or '-'} |")
    w("\nAdversarial normals wrongly flagged at budget A: " + "; ".join(
        f"{n}: {ov['adversarial_normals_flagged'][n]['count']} ({', '.join(f'{i} ADV-{t}' for i, t in ov['adversarial_normals_flagged'][n]['subtypes'].items()) or 'none'})" for n in APPROACHES) + ".\n")
    w("## Score distributions and top-ranked projects\n")
    w("| Approach | Min | P25 | Median | Mean | P75 | Max |\n|---|--:|--:|--:|--:|--:|--:|")
    for n in APPROACHES:
        s_ = ap[n]["score_distribution"]
        w(f"| {n} | {_f(s_['min'])} | {_f(s_['p25'])} | {_f(s_['median'])} | {_f(s_['mean'])} | {_f(s_['p75'])} | {_f(s_['max'])} |")
    w("\nTop 10 by score (full top 20 in the JSON):\n")
    w("| Rank | " + " | ".join(f"{n}" for n in APPROACHES) + " |\n|--:|---|---|---|")
    for i in range(10):
        cells = []
        for n in APPROACHES:
            t = ap[n]["top_20"][i]
            cells.append(f"{t['project_id']} {_f(t['risk_score'], 2)} {'ANOM' if t['ground_truth_label'] == 'ANOMALOUS' else 'norm'} ({t['scenario_type']})")
        w(f"| {i + 1} | " + " | ".join(cells) + " |")
    w("")

    wl = r["wins_losses"]
    w("## Where NidhiGuard Wins\n")
    wins = [f"{x['metric']} vs {x['against']}: V1 {_f(x['v1'])} vs {_f(x['baseline'])}" for x in wl["metrics"]["v1_better"]]
    wins += [f"{x['scenario']}: V1 flags {x['NidhiGuard V1']}/{x['n']} at budget A vs cost {x['Cost-Deviation']} and Isolation Forest {x['Isolation Forest']}" for x in wl["scenarios_at_budget_A"]["v1_detects_more_than_both"]]
    fp = wl["adversarial_false_positives_at_budget_A"]
    if fp[V1] < min(fp[COST], fp[IFO]):
        wins.append(f"Adversarial normals flagged at budget A: V1 {fp[V1]} vs cost {fp[COST]} and Isolation Forest {fp[IFO]}")
    for x in (wins or ["None on these measures."]):
        w(f"- {x}")
    w("\n## Where NidhiGuard Loses\n")
    loses = [f"{x['metric']} vs {x['against']}: V1 {_f(x['v1'])} vs {_f(x['baseline'])}" for x in wl["metrics"]["v1_worse"]]
    loses += [f"{x['scenario']}: V1 flags {x['NidhiGuard V1']}/{x['n']} at budget A vs cost {x['Cost-Deviation']} and Isolation Forest {x['Isolation Forest']}" for x in wl["scenarios_at_budget_A"]["v1_detects_less_than_a_baseline"]]
    if fp[V1] > min(fp[COST], fp[IFO]):
        loses.append(f"Adversarial normals flagged at budget A: V1 {fp[V1]} vs cost {fp[COST]} and Isolation Forest {fp[IFO]}")
    for x in (loses or ["None on these measures."]):
        w(f"- {x}")
    ties = [f"{x['scenario']} ({x['NidhiGuard V1']}/{x['n']} for the best method)" for x in wl["scenarios_at_budget_A"]["v1_ties_best"]]
    w("\nTied with the best method at budget A: " + ("; ".join(ties) or "none") + ".\n")
    w(f"V1 metrics equal to a baseline: {', '.join(f'{x['metric']} vs {x['against']}' for x in wl['metrics']['v1_equal']) or 'none'}.\n")

    w("## Interpretation\n")
    order = sorted(APPROACHES, key=lambda n: -ap[n]["average_precision"])
    w(f"- Average precision ranks the approaches {' > '.join(f'{n} ({_f(ap[n]['average_precision'])})' for n in order)}; random ranking is {_f(base)}.")
    for k, v in r["paired_bootstrap_delta_average_precision"].items():
        lo, hi = v["ci95"]
        verdict = "the optimistic interval excludes zero" if (lo > 0 or hi < 0) else "the optimistic interval includes zero, so this difference is not reliable"
        w(f"- {k}: {v['mean_delta_ap']:+.3f} average precision; {verdict}.")
    only_v1 = [x for x in M.ANOMALOUS_SCENARIOS if ap[V1]["scenario_level"][x]["flagged_at_budget_A"] > 0
               and ap[COST]["scenario_level"][x]["flagged_at_budget_A"] == 0 and ap[IFO]["scenario_level"][x]["flagged_at_budget_A"] == 0]
    cost_scen = [x for x in M.ANOMALOUS_SCENARIOS if ap[COST]["scenario_level"][x]["flagged_at_budget_A"] > 0]
    if_scen = [x for x in M.ANOMALOUS_SCENARIOS if ap[IFO]["scenario_level"][x]["flagged_at_budget_A"] > 0]
    w(f"- Cost deviation alone reaches {_f(ap[COST]['average_precision'] / ap[V1]['average_precision'], 2)}x V1's average precision and flags anomalies in: {', '.join(cost_scen) or 'no scenario'} at budget A.")
    w(f"- The generic Isolation Forest reaches {_f(ap[IFO]['average_precision'] / ap[V1]['average_precision'], 2)}x V1's average precision and flags anomalies in: {', '.join(if_scen) or 'no scenario'} at budget A.")
    w(f"- Scenarios where only V1 flags anything at budget A (neither baseline does): {', '.join(only_v1) or 'none'}.")
    pk = lambda n, k: ap[n]["precision_at_k"][str(k)]["precision"]
    w(f"- At the top of the queue the methods are close: precision@5 is {_f(pk(V1, 5), 2)} / {_f(pk(COST, 5), 2)} / {_f(pk(IFO, 5), 2)} and precision@10 is "
      f"{_f(pk(V1, 10), 2)} / {_f(pk(COST, 10), 2)} / {_f(pk(IFO, 10), 2)} (V1 / cost / Isolation Forest). The gaps are larger lower in the ranking: "
      f"R-precision (precision at K = number of anomalous projects) is {_f(ap[V1]['r_precision']['precision'], 2)} / {_f(ap[COST]['r_precision']['precision'], 2)} / {_f(ap[IFO]['r_precision']['precision'], 2)}.")
    mp = "; ".join(f"{x} {ap[V1]['scenario_level'][x]['mean_percentile_rank']:.2f}/{ap[COST]['scenario_level'][x]['mean_percentile_rank']:.2f}/{ap[IFO]['scenario_level'][x]['mean_percentile_rank']:.2f}"
                   for x in M.ANOMALOUS_SCENARIOS)
    w(f"- Mean percentile rank by anomalous scenario (V1 / cost / Isolation Forest; 1.0 = top-ranked): {mp}.")
    vc = r["v1_mean_component_scores_by_scenario"]
    short = {"cost_anomaly_score": "cost", "project_similarity_score": "similarity", "contractor_pattern_score": "contractor",
             "billing_anomaly_score": "billing", "geographic_signal_score": "geographic"}
    w("- V1 mean component scores by anomalous scenario (maxima: cost 25, similarity 25, contractor 20, billing 20, geographic 10), for context on what drives V1's score: " + "; ".join(
        f"{x}: " + ", ".join(f"{short[c]} {vc[x][c]:.1f}" for c in short if c in vc[x]) for x in M.ANOMALOUS_SCENARIOS) + ".")
    w("- Read together: these numbers describe how the three scoring methods behave on this constructed dataset; they do not isolate which detector or feature causes a difference, and they do not show a cost-only or generic method is inadequate in general.\n")

    w("## Limitations\n")
    for x in [
        "The evaluation dataset is synthetic.",
        "The scenario families are designed around known red-flag patterns, and V1's detector families were designed around the same patterns; results measure agreement with that definition.",
        "This is not real-world fraud-detection validation and no real investigation outcomes are available.",
        "Isolation Forest results depend on feature selection and preprocessing; the eight features were fixed in advance, but a different defensible feature set could rank differently. No feature search was performed, and the author knew the dataset's construction rules when choosing features.",
        "The estimate-to-sanction ratio is a feature available to the Isolation Forest but (by construction of the cost scenarios) also the field that separates COST_ANOMALY from the ADV-C adversarial cases; V1 may not use it. Any advantage this gives a baseline reflects the dataset design as well as the method.",
        f"All {d['multi_signal_with_cost_inflation']} of {d['multi_signal_cases']} MULTI_SIGNAL cases include a cost-inflation component by construction, so a cost-only method is expected to rank them highly; the strong cost-baseline MULTI_SIGNAL and COST_ANOMALY rows partly reflect that design, as do V1's.",
        "The Isolation Forest feature set includes two spatial-density features (neighbours within 5 km, nearest-neighbour distance) and GEOGRAPHIC_PATTERN cases are tight spatial clusters, so that scenario matches these generic features well; which features drive the forest's ranking was not analysed.",
        "Matched-budget thresholds depend on V1's output volume (A and B); they are label-free but are not natural thresholds for the baselines.",
        "150 projects (49 anomalous) in linked scenario groups; small differences are within noise, and the bootstrap intervals are optimistic.",
        "A baseline comparison does not establish production effectiveness.",
    ]:
        w(f"- {x}")
    w("\n## Conclusion\n")
    best = order[0]
    d_c = r["paired_bootstrap_delta_average_precision"][f"{V1} minus {COST}"]
    d_i = r["paired_bootstrap_delta_average_precision"][f"{V1} minus {IFO}"]

    def rel(v, name):
        lo, hi = v["ci95"]
        if lo > 0:
            return f"V1 ranked better than the {name} by more than the optimistic bootstrap noise"
        if hi < 0:
            return f"the {name} ranked better than V1 by more than the optimistic bootstrap noise"
        return f"V1 and the {name} were not reliably different in average precision"
    w(f"On this independent synthetic evaluation set, {best} had the highest average precision ({_f(ap[best]['average_precision'])}). "
      f"Against the cost-deviation baseline, {rel(d_c, 'cost-deviation baseline')}; against the Isolation Forest, {rel(d_i, 'Isolation Forest')}. "
      f"At the top of the queue, precision@10 was V1 {_f(ap[V1]['precision_at_k']['10']['precision'], 2)}, cost {_f(ap[COST]['precision_at_k']['10']['precision'], 2)}, "
      f"Isolation Forest {_f(ap[IFO]['precision_at_k']['10']['precision'], 2)}. These results are specific to this constructed dataset and do not establish real-world effectiveness.\n")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="V2.3 baseline comparison")
    ap.add_argument("--dir", default="evaluation")
    a = ap.parse_args()
    try:
        preds = write_predictions(a.dir)
        rep = compare(a.dir)
    except (M.EvaluationInputError, FileNotFoundError, ValueError) as e:
        print(f"V2.3 FAILED: {e}", file=sys.stderr)
        return 2
    print(f"Wrote baseline_predictions.csv ({len(preds)} projects) and baseline_comparison.json/.md")
    for r in rep["comparison_table"]:
        print(f"{r['approach']:18s} AP={r['average_precision']:.3f}  P@5={r['precision_at_5']:.2f}  P@10={r['precision_at_10']:.2f}  "
              f"P@20={r['precision_at_20']:.2f}  Recall@20={r['recall_at_20']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
