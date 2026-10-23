"""
NidhiGuard V2.4 - one-detector-at-a-time ablation study (evaluation only).

V1's actual aggregation, read from intelligence/risk_engine.py (RiskEngine.score_project):

    raw_total  = cost.score + similarity.score + contractor.score + billing.score + geographic.score
    risk_score = round(min(100.0, raw_total), 1)

Each detector already scales itself to its own cap (25 / 25 / 20 / 20 / 10), so there are no separate weights.
An ablation sets exactly one detector's score to 0.0 and re-applies this same expression (same left-to-right
order, same cap, same rounding). It is NOT "FULL minus the component", which differs whenever the cap or the
rounding matters. Nothing is rescaled, so a variant's maximum possible score falls by the removed cap.

Two strictly separated stages (same discipline as V2.3):
  Stage 1  build_ablation_predictions()  reads ONLY the frozen V1 reference predictions (evaluation_predictions.csv:
                                         project_id, the five component scores, risk_score) and writes the six variants.
                                         It never opens the labels, the planted signals or the dataset.
  Stage 2  compare()                     reads the labels and uses the V2.2 metrics (imported, not modified).

Nothing here imports or modifies the V1 engine, the dataset, the labels, the V2.2 metrics or the V2.3 baselines.

Usage (repo root):
    python -m evaluation.ablation.run_ablation --dir evaluation
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_SUBDIR = "ablation"

# (name, column in the frozen V1 predictions, cap = the detector's MAX_SCORE in V1), in V1's addition order
COMPONENTS = (("cost_anomaly", "cost_anomaly_score", 25),
              ("project_similarity", "project_similarity_score", 25),
              ("contractor_pattern", "contractor_pattern_score", 20),
              ("billing_anomaly", "billing_anomaly_score", 20),
              ("geographic_signal", "geographic_signal_score", 10))
COMPONENT_NAMES = tuple(c[0] for c in COMPONENTS)
COMPONENT_COLUMNS = tuple(c[1] for c in COMPONENTS)
CAPS = {c[0]: c[2] for c in COMPONENTS}
VARIANTS = (("FULL", None), ("NO_COST", "cost_anomaly"), ("NO_SIMILARITY", "project_similarity"),
            ("NO_CONTRACTOR", "contractor_pattern"), ("NO_BILLING", "billing_anomaly"), ("NO_GEOGRAPHIC", "geographic_signal"))
VARIANT_NAMES = tuple(v[0] for v in VARIANTS)
THRESHOLDS = (30.0, 40.0)          # V1 LOW/MEDIUM boundary, and the V2.2 evaluation threshold
SMALL_AP_DELTA = 0.02              # operational label only (declared before results): |change in average precision| below this = "small"
BOOTSTRAP_SEED = 20262404
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_LABEL = ("Supplementary optimistic bootstrap interval; row resampling does not account for "
                   "linked synthetic scenario groups.")
V1_EXPRESSIONS = {
    "raw_total": "cost.score + similarity.score + contractor.score + billing.score + geographic.score",
    "risk_score": "round(min(100.0, raw_total), 1)",
    "risk_level": "CRITICAL if score >= 80; HIGH if >= 60; MEDIUM if >= 30; else LOW",
}
MANDATORY_STATEMENT = ("This ablation study evaluates detector contribution on the frozen V2.1 synthetic evaluation set. "
                       "It does not establish real-world fraud-detection effectiveness.")


# --------------------------------------------------------------------------- #
# Stage 1 - label-free ablation scores
# --------------------------------------------------------------------------- #
def v1_aggregate(cost: float, similarity: float, contractor: float, billing: float, geographic: float) -> float:
    """V1's exact aggregation (risk_engine.py), same operation order, cap and rounding."""
    raw_total = cost + similarity + contractor + billing + geographic
    return round(min(100.0, raw_total), 1)


def v1_risk_level(score: float) -> str:
    """V1's level boundaries (classify_risk_level); unchanged for every variant."""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def ablation_score(components: dict, ablated: str | None) -> float:
    """Zero exactly one component, then re-apply V1's aggregation unchanged. x + 0.0 == x, so the remaining
    additions are bit-for-bit what V1 would compute with that detector contributing nothing."""
    if ablated is not None and ablated not in CAPS:
        raise ValueError(f"unknown component {ablated!r}")
    v = {k: (0.0 if k == ablated else float(components[k])) for k in COMPONENT_NAMES}
    return v1_aggregate(v["cost_anomaly"], v["project_similarity"], v["contractor_pattern"],
                        v["billing_anomaly"], v["geographic_signal"])


def load_components(eval_dir: str) -> pd.DataFrame:
    """The frozen V1 outputs this study ablates: project_id, five component scores, and V1's own risk_score."""
    cols = ["project_id", *COMPONENT_COLUMNS, "risk_score"]
    df = pd.read_csv(os.path.join(eval_dir, "evaluation_predictions.csv"), usecols=cols, dtype={"project_id": str})
    if not df["project_id"].is_unique:
        raise ValueError("duplicate project_id in the V1 reference predictions")
    num = df[list(COMPONENT_COLUMNS) + ["risk_score"]].to_numpy(dtype=float)
    if not np.isfinite(num).all():
        raise ValueError("non-finite component score")
    for name, col, cap in COMPONENTS:
        if (df[col] < 0).any() or (df[col] > cap).any():
            raise ValueError(f"{col} outside 0..{cap}: not V1 output")
    return df.sort_values("project_id").reset_index(drop=True)


def build_ablation_predictions(eval_dir: str) -> pd.DataFrame:
    """Long format: one row per (variant, project) with the components as used, ablated component, score, level, rank."""
    comp = load_components(eval_dir)
    rows = []
    for variant, ablated in VARIANTS:
        scored = []
        for r in comp.itertuples(index=False):
            c = {name: getattr(r, col) for name, col, _ in COMPONENTS}
            used = {k: (0.0 if k == ablated else float(v)) for k, v in c.items()}
            scored.append((r.project_id, used, ablation_score(c, ablated)))
        if variant == "FULL":      # fidelity guard: the replica must reproduce V1's own risk_score exactly
            frozen = dict(zip(comp.project_id, comp.risk_score))
            bad = [pid for pid, _, s in scored if s != frozen[pid]]
            if bad:
                raise ValueError(f"FULL recomputation differs from V1 risk_score for {len(bad)} projects: {bad[:5]}")
        order = sorted(scored, key=lambda t: (-t[2], t[0]))          # score descending, project_id ascending
        rank = {pid: i + 1 for i, (pid, _, _) in enumerate(order)}
        for pid, used, s in scored:
            rows.append({"variant": variant, "ablated_component": ablated or "none", "project_id": pid,
                         **{col: used[name] for name, col, _ in COMPONENTS},
                         "ablation_score": s, "risk_level": v1_risk_level(s), "rank": rank[pid]})
    out = pd.DataFrame(rows)
    out["_v"] = out["variant"].map({v: i for i, v in enumerate(VARIANT_NAMES)})
    out = out.sort_values(["_v", "project_id"]).drop(columns="_v").reset_index(drop=True)
    return out


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _write_text(path: str, text: str) -> None:
    """LF newlines and UTF-8 on every platform (Windows text mode would emit CRLF)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def manifest(eval_dir: str) -> dict:
    """Hashes of everything V2.4 must not change."""
    rel_root = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")
    rel_eval = lambda p: "evaluation/" + os.path.relpath(p, eval_dir).replace(os.sep, "/")
    walk = lambda pattern: sorted(f for f in glob.glob(os.path.join(ROOT, pattern), recursive=True)
                                  if "__pycache__" not in f and os.path.isfile(f))
    ev = lambda names: [os.path.join(eval_dir, f) for f in names]
    return {
        "v1_intelligence_source": {rel_root(p): _sha(p) for p in walk("intelligence/*.py")},
        "v1_backend_and_frontend_source": {rel_root(p): _sha(p) for pat in ("backend/app/**/*", "src/**/*") for p in walk(pat)},
        "v2_1_dataset_and_spec": {rel_eval(p): _sha(p) for p in sorted(glob.glob(os.path.join(eval_dir, "engine_input", "*.csv"))) + ev(
            ("evaluation_labels.csv", "evaluation_metadata.json", "spec_constants.py", "SCENARIO_SPEC.md",
             "generate_evaluation_data.py", "run_v1_predictions.py"))},
        "v2_2_metrics_and_reference_outputs": {rel_eval(p): _sha(p) for p in ev(
            ("evaluation_metrics.py", "evaluation_predictions.csv", "evaluation_predictions_meta.json",
             "evaluation_report.json", "evaluation_report.md"))},
        "v2_3_baselines": {rel_eval(p): _sha(p) for p in sorted(glob.glob(os.path.join(eval_dir, "baselines", "*.py"))) + ev(
            ("baseline_predictions.csv", "baseline_predictions_meta.json", "baseline_comparison.json", "baseline_comparison.md"))},
    }


def build_meta(eval_dir: str, preds: pd.DataFrame) -> dict:
    with open(os.path.join(eval_dir, "evaluation_metadata.json"), encoding="utf-8") as fh:
        frozen = json.load(fh)["file_sha256"]
    return {
        "stage": "V2.4 ablation predictions (label-free)",
        "number_of_projects": int(preds["project_id"].nunique()),
        "rows": int(len(preds)),
        "variants": [{"variant": v, "ablated_component": a or "none",
                      "max_possible_score": int(sum(c for k, c in CAPS.items() if k != a))} for v, a in VARIANTS],
        "v1_scoring_formula": V1_EXPRESSIONS,
        "component_caps": CAPS,
        "component_order_in_sum": list(COMPONENT_NAMES),
        "ablation_definition": "the ablated component is set to 0.0 and V1's aggregation expression is re-applied unchanged; "
                               "remaining components keep their original values and caps; nothing is rescaled",
        "rank_definition": "ablation_score descending, project_id ascending for ties; 1 = highest",
        "risk_level_boundaries": "unchanged V1 boundaries 30/60/80 for every variant",
        "inputs_read": ["evaluation_predictions.csv (frozen V1 reference: project_id, five component scores, risk_score)"],
        "inputs_never_read_in_this_stage": ["evaluation_labels.csv", "engine_input/anomaly_signals.csv", "engine_input/* (dataset)"],
        "input_hashes": {"evaluation_predictions.csv": _sha(os.path.join(eval_dir, "evaluation_predictions.csv")),
                         "engine_input": {k: v for k, v in frozen.items() if k.startswith("engine_input/")}},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                        "scikit_learn": sklearn.__version__},
        "frozen_manifest": manifest(eval_dir),
        "note": "No timestamp is stored so that repeated runs produce byte-identical files.",
    }


def write_predictions(eval_dir: str) -> pd.DataFrame:
    out_dir = os.path.join(eval_dir, OUT_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)
    preds = build_ablation_predictions(eval_dir)
    _write_text(os.path.join(out_dir, "ablation_predictions.csv"), preds.to_csv(index=False, lineterminator="\n"))
    _write_text(os.path.join(out_dir, "ablation_predictions_meta.json"), json.dumps(build_meta(eval_dir, preds), indent=2) + "\n")
    return preds


# --------------------------------------------------------------------------- #
# Stage 2 - metrics (labels are read here, and only here)
# --------------------------------------------------------------------------- #
def _rank_agreement(df: pd.DataFrame, full: pd.DataFrame) -> dict:
    a = full.set_index("project_id").risk_score
    b = df.set_index("project_id").risk_score.reindex(a.index)
    ra, rb = a.rank(method="average").to_numpy(), b.rank(method="average").to_numpy()
    rho = float(np.corrcoef(ra, rb)[0, 1]) if ra.std() > 0 and rb.std() > 0 else None
    top = lambda d, k: set(M.rank(d).project_id.iloc[:k])
    return {"spearman_with_full": rho, "top10_overlap_with_full": len(top(df, 10) & top(full, 10)),
            "top20_overlap_with_full": len(top(df, 20) & top(full, 20))}


def evaluate_variant(name: str, ablated: str | None, pred: pd.DataFrame, labels: pd.DataFrame) -> tuple:
    df = M.prepare(pred, labels)
    ranked = M.rank(df)
    n_pos = int(df.y_true.sum())
    ap = M.pr_auc(df)
    pk = {k: M.precision_at_k(ranked, k) for k in M.TOP_K}
    df = df.assign(pct_rank=df.risk_score.rank(pct=True, method="average"))
    thr = {}
    for t in THRESHOLDS:
        c = M.thresholded(df, t)
        thr[f"{t:g}"] = {"flagged_total": c["predicted_positive"], "anomalous_detected": c["tp"], "normal_flagged": c["fp"],
                         "anomalous_missed": c["fn"], "precision": c["precision"], "recall": c["recall"], "f1": c["f1"]}
    adv = M.adversarial_analysis(df, threshold=40.0, q_threshold=30.0)
    adv_pos = [i + 1 for i, st in enumerate(ranked.scenario_type) if st == "ADVERSARIAL_NORMAL"]     # 1 = top-ranked
    adv_out = {"n": adv["n"], "max_score": adv["max"], "mean_score": adv["mean"], "median_score": adv["median"],
               "in_top_10": int(sum(p <= 10 for p in adv_pos)), "in_top_20": int(sum(p <= 20 for p in adv_pos)),
               "best_rank": int(min(adv_pos)),
               "flagged_at_30": adv["n_at_or_above_v1_queue"], "flagged_at_40": adv["n_at_or_above_primary"],
               "by_subtype": {s: {"n": e["n"], "flagged_at_30": e["n_at_or_above_v1_queue"], "flagged_at_40": e["n_at_or_above_primary"],
                                  "max_score": e["max"]} for s, e in adv.get("by_subtype", {}).items()}}
    sc = M.scenario_table(df, threshold=40.0, q_threshold=30.0)
    scen = {}
    for s, e in sc.items():
        g = df[df.scenario_type == s]
        scen[s] = {"n": e["n"], "n_anomalous": e["n_anomalous"], "mean_score": e["mean"], "max_score": e["max"],
                   "mean_percentile_rank": float(g.pct_rank.mean()) if len(g) else None,
                   "flagged_at_30": e["n_at_or_above_v1_queue"], "rate_at_30": e["rate_at_or_above_v1_queue"],
                   "flagged_at_40": e["n_at_or_above_primary"], "rate_at_40": e["rate_at_or_above_primary"],
                   "rate_meaning": e["rate_meaning"]}
    vc = ranked.risk_score.value_counts()
    ties = {"distinct_scores": int(vc.size), "largest_tie_block": int(vc.max()), "largest_tie_score": float(vc.idxmax()),
            "tie_straddles_top_20": bool(ranked.risk_score.iloc[19] == ranked.risk_score.iloc[20]),
            "tie_straddles_top_10": bool(ranked.risk_score.iloc[9] == ranked.risk_score.iloc[10]),
            "tie_straddles_top_5": bool(ranked.risk_score.iloc[4] == ranked.risk_score.iloc[5])}
    rng_k = {}
    for k in M.TOP_K:
        cut = ranked.risk_score.iloc[k - 1]
        above, tied = ranked[ranked.risk_score > cut], ranked[ranked.risk_score == cut]
        slots, a, t = k - len(above), int(tied.y_true.sum()), len(tied)
        base = int(above.y_true.sum())
        lo, hi = base + max(0, slots - (t - a)), base + min(slots, a)
        rng_k[str(k)] = {"p_at_k_if_ties_ordered_worst": lo / k, "p_at_k_if_ties_ordered_best": hi / k, "tied_block_at_cutoff": int(t),
                         "tie_sensitive": bool(lo != hi)}
    ties["precision_at_k_tie_range"] = rng_k
    summary = {"ablated_component": ablated or "none", "ties": ties,
               "max_possible_score": int(sum(c for k, c in CAPS.items() if k != ablated)),
               "average_precision": ap["average_precision"], "trapezoid_auc": ap["trapezoid_auc"],
               "precision_at_k": {str(k): v for k, v in pk.items()}, "r_precision": M.precision_at_k(ranked, n_pos),
               "thresholds": thr, "adversarial_normal": adv_out, "scenario_level": scen,
               "score_distribution": {"min": float(df.risk_score.min()), "median": float(df.risk_score.median()),
                                      "mean": float(df.risk_score.mean()), "max": float(df.risk_score.max())},
               "top_20": M.top_n(ranked, 20)}
    return summary, df


def paired_bootstrap_delta_ap(y: np.ndarray, variant: np.ndarray, full: np.ndarray, n: int = BOOTSTRAP_RESAMPLES,
                              seed: int = BOOTSTRAP_SEED) -> dict:
    """Distribution of AP(variant) - AP(FULL) over the same resampled projects."""
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        yb = y[idx]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        d.append(average_precision_score(yb, variant[idx]) - average_precision_score(yb, full[idx]))
    d = np.asarray(d)
    return {"mean_delta_ap": float(d.mean()), "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "share_resamples_variant_better": float((d > 0).mean()), "share_resamples_variant_worse": float((d < 0).mean()),
            "resamples_used": int(len(d)), "label": BOOTSTRAP_LABEL}


def deltas(res: dict) -> dict:
    """ABLATION - FULL for every headline metric (negative = removing the detector lowered it)."""
    f = res["FULL"]
    out = {}
    for v in VARIANT_NAMES[1:]:
        r = res[v]
        out[v] = {
            "delta_pr_auc": r["average_precision"] - f["average_precision"],
            "delta_precision_at_5": r["precision_at_k"]["5"]["precision"] - f["precision_at_k"]["5"]["precision"],
            "delta_precision_at_10": r["precision_at_k"]["10"]["precision"] - f["precision_at_k"]["10"]["precision"],
            "delta_precision_at_20": r["precision_at_k"]["20"]["precision"] - f["precision_at_k"]["20"]["precision"],
            "delta_recall_at_20": r["precision_at_k"]["20"]["recall_at_k"] - f["precision_at_k"]["20"]["recall_at_k"],
            "delta_anomalous_detected_at_30": r["thresholds"]["30"]["anomalous_detected"] - f["thresholds"]["30"]["anomalous_detected"],
            "delta_anomalous_detected_at_40": r["thresholds"]["40"]["anomalous_detected"] - f["thresholds"]["40"]["anomalous_detected"],
            "delta_adversarial_flagged_at_30": r["adversarial_normal"]["flagged_at_30"] - f["adversarial_normal"]["flagged_at_30"],
            "delta_adversarial_flagged_at_40": r["adversarial_normal"]["flagged_at_40"] - f["adversarial_normal"]["flagged_at_40"],
            "delta_adversarial_max_score": r["adversarial_normal"]["max_score"] - f["adversarial_normal"]["max_score"],
            "delta_adversarial_in_top_20": r["adversarial_normal"]["in_top_20"] - f["adversarial_normal"]["in_top_20"],
        }
    return out


def contribution_analysis(res: dict, dl: dict, boot: dict) -> dict:
    """Mechanical classification; operational rules are declared here and in the report, not tuned afterwards."""
    rows = []
    for i, v in enumerate(VARIANT_NAMES[1:]):
        d, b = dl[v], boot[v]
        lo, hi = b["ci95"]
        rows.append({"variant": v, "component": res[v]["ablated_component"],
                     "contribution_ap": -d["delta_pr_auc"], "contribution_p20": -d["delta_precision_at_20"],
                     "contribution_recall20": -d["delta_recall_at_20"],
                     "ci95_delta_ap": b["ci95"], "removal_reliably_hurts": bool(hi < 0), "removal_reliably_helps": bool(lo > 0),
                     "small_change": bool(abs(d["delta_pr_auc"]) < SMALL_AP_DELTA),
                     "removal_improves_ap": bool(d["delta_pr_auc"] > 1e-12),
                     "removal_improves_top_of_queue": {k: d[k] for k in ("delta_precision_at_5", "delta_precision_at_10",
                                                                         "delta_precision_at_20", "delta_recall_at_20") if d[k] > 1e-12},
                     "removal_lowers_adversarial_top_20": bool(d["delta_adversarial_in_top_20"] < 0),
                     "no_headline_metric_changed": bool(all(abs(d[k]) < 1e-12 for k in (
                         "delta_pr_auc", "delta_precision_at_5", "delta_precision_at_10", "delta_precision_at_20", "delta_recall_at_20",
                         "delta_anomalous_detected_at_30", "delta_anomalous_detected_at_40",
                         "delta_adversarial_flagged_at_30", "delta_adversarial_flagged_at_40"))),
                     "_order": i})
    rows.sort(key=lambda r: (-round(r["contribution_ap"], 12), -round(r["contribution_p20"], 12),
                             -round(r["contribution_recall20"], 12), r["_order"]))
    for r in rows:
        r.pop("_order")
    return {"ranking_by_ap_contribution": rows,
            "rules": {"contribution_ap": "AP(FULL) - AP(variant); positive = the detector helped on this set",
                      "removal_reliably_hurts": "optimistic paired-bootstrap 95% interval of AP(variant)-AP(FULL) lies entirely below 0",
                      "small_change": f"|AP(variant) - AP(FULL)| < {SMALL_AP_DELTA} (operational label, not a statistical test)",
                      "removal_improves_top_of_queue": "a positive delta in P@5, P@10, P@20 or Recall@20 even if PR-AUC fell",
                      "no_headline_metric_changed": "AP, P@5/10/20, Recall@20, detections and adversarial flags at 30/40 all identical to FULL"}}


def scenario_carriers(cm: dict, min_points: float = 1.0) -> dict:
    """Per anomalous scenario: components whose mean score exceeds the NORMAL-scenario mean by at least min_points."""
    out = {}
    for sname in ("COST_ANOMALY", "BILLING_ANOMALY", "CONTRACTOR_PATTERN", "SIMILAR_PROJECT", "GEOGRAPHIC_PATTERN", "MULTI_SIGNAL"):
        ex = {c: cm[sname][c] - cm["NORMAL"][c] for c in COMPONENT_COLUMNS}
        out[sname] = [{"component": c, "mean_points_above_normal": v} for c, v in sorted(ex.items(), key=lambda kv: -kv[1]) if v >= min_points]
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
        raise M.EvaluationInputError(f"provenance check failed; refusing to evaluate: {prov}")
    out_dir = os.path.join(eval_dir, OUT_SUBDIR)
    with open(os.path.join(out_dir, "ablation_predictions_meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    if meta["input_hashes"]["evaluation_predictions.csv"] != prov["predictions_sha256"]:
        raise M.EvaluationInputError("ablation was not built from the frozen V1 reference predictions")
    long = pd.read_csv(os.path.join(out_dir, "ablation_predictions.csv"), dtype={"project_id": str})
    _, labels = M.load_csvs(os.path.join(eval_dir, "evaluation_predictions.csv"), os.path.join(eval_dir, "evaluation_labels.csv"))

    res, dfs = {}, {}
    for v, a in VARIANTS:
        sub = long[long.variant == v]
        pred = pd.DataFrame({"project_id": sub.project_id.to_numpy(), "risk_score": sub.ablation_score.to_numpy(dtype=float),
                             "risk_level": sub.risk_level.to_numpy()})
        res[v], dfs[v] = evaluate_variant(v, a, pred, labels)
    ids = sorted(dfs["FULL"].project_id)
    if any(sorted(dfs[v].project_id) != ids for v in VARIANT_NAMES):
        raise M.EvaluationInputError("variants were not evaluated on identical project sets")
    for v in VARIANT_NAMES[1:]:
        res[v].update(_rank_agreement(dfs[v], dfs["FULL"]))
    res["FULL"].update(_rank_agreement(dfs["FULL"], dfs["FULL"]))

    ref = dfs["FULL"].set_index("project_id").loc[ids]
    y = ref.y_true.to_numpy()
    sc = {v: dfs[v].set_index("project_id").loc[ids, "risk_score"].to_numpy() for v in VARIANT_NAMES}
    boot = {v: paired_bootstrap_delta_ap(y, sc[v], sc["FULL"]) for v in VARIANT_NAMES[1:]}
    dl = deltas(res)
    full_frozen = pd.read_csv(os.path.join(eval_dir, "evaluation_predictions.csv"), usecols=["project_id", "risk_score"], dtype={"project_id": str})
    d = dfs["FULL"]
    full_long = long[long.variant == "FULL"][["project_id", *COMPONENT_COLUMNS]]
    joined = full_long.merge(labels[["project_id", "scenario_type", "ground_truth_label"]], on="project_id", validate="one_to_one")
    comp_means = {s: {c: float(joined.loc[joined.scenario_type == s, c].mean()) for c in COMPONENT_COLUMNS} for s in M.SCENARIO_ORDER}
    comp_means_label = {g: {c: float(joined.loc[joined.ground_truth_label == g, c].mean()) for c in COMPONENT_COLUMNS}
                        for g in ("ANOMALOUS", "NORMAL")}
    report = {
        "dataset": {"projects": int(len(d)), "anomalous": int(d.y_true.sum()), "normal": int((d.y_true == 0).sum()),
                    "adversarial_normal": int((d.scenario_type == "ADVERSARIAL_NORMAL").sum()),
                    "scenario_counts": {k: v["n"] for k, v in res["FULL"]["scenario_level"].items()},
                    "same_projects_and_labels_as_v2_2_v2_3": True, "provenance": prov},
        "v1_scoring_formula": {**V1_EXPRESSIONS, "component_caps": CAPS, "component_order_in_sum": list(COMPONENT_NAMES),
                               "weights": "no separate weights: each detector scales itself to its own cap, so the caps are the weights",
                               "full_variant_reproduces_frozen_v1_risk_score": bool(
                                   (dfs["FULL"].set_index("project_id").risk_score.reindex(full_frozen.project_id).to_numpy()
                                    == full_frozen.risk_score.to_numpy()).all())},
        "variants": {v: {"ablated_component": a or "none", "max_possible_score": res[v]["max_possible_score"]} for v, a in VARIANTS},
        "full_mean_component_scores_by_scenario": comp_means,
        "full_mean_component_scores_by_label": comp_means_label,
        "scenario_carrier_components": scenario_carriers(comp_means),
        "results": res,
        "comparison_table": [{"variant": v, "average_precision": res[v]["average_precision"],
                              "precision_at_5": res[v]["precision_at_k"]["5"]["precision"],
                              "precision_at_10": res[v]["precision_at_k"]["10"]["precision"],
                              "precision_at_20": res[v]["precision_at_k"]["20"]["precision"],
                              "recall_at_20": res[v]["precision_at_k"]["20"]["recall_at_k"]} for v in VARIANT_NAMES],
        "delta_definition": "delta = ABLATION - FULL. A negative value means removing the detector LOWERED the metric.",
        "deltas_vs_full": dl,
        "paired_bootstrap_delta_average_precision_vs_full": boot,
        "contribution_analysis": contribution_analysis(res, dl, boot),
        "mandatory_statement": MANDATORY_STATEMENT,
    }
    report = _round(report)
    _write_text(os.path.join(out_dir, "ablation_comparison.json"), json.dumps(report, indent=2) + "\n")
    _write_text(os.path.join(out_dir, "ablation_comparison.md"), render_markdown(report))
    return report


# --------------------------------------------------------------------------- #
# Markdown report (all prose is generated from the computed numbers)
# --------------------------------------------------------------------------- #
def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _s(x, nd=3):
    if x is None:
        return "n/a"
    return f"{(0.0 if round(x, nd) == 0 else x):+.{nd}f}"


def _effect(component: str, metric: str, d: float, nd=3) -> str:
    pretty = component.replace("_", " ")
    if abs(d) < 0.5 * 10 ** (-nd):
        return f"removing {pretty} did not change {metric}"
    verb = "reduced" if d < 0 else "increased"
    return f"removing {pretty} {verb} {metric} by {abs(d):.{nd}f}"


def _and(items: list) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _tq_text(e: dict) -> str:
    """e.g. 'precision at 10 +0.10, recall at 20 +0.020' for a variant whose removal raised top-of-queue metrics."""
    return ", ".join(f"{k.replace('delta_', '').replace('_', ' ')} {_s(v, 2 if 'precision' in k else 3)}"
                     for k, v in e["removal_improves_top_of_queue"].items())


def render_markdown(r: dict) -> str:
    res, dl, ds = r["results"], r["deltas_vs_full"], r["dataset"]
    ca, boot = r["contribution_analysis"], r["paired_bootstrap_delta_average_precision_vs_full"]
    L = []
    w = L.append
    mark = lambda v, k: "*" if res[v]["ties"]["precision_at_k_tie_range"][k]["tie_sensitive"] else ""
    sens = [(v, k) for v in VARIANT_NAMES for k in ("5", "10", "20") if res[v]["ties"]["precision_at_k_tie_range"][k]["tie_sensitive"]]
    big = [(v, res[v]["ties"]["largest_tie_block"], res[v]["ties"]["largest_tie_score"]) for v in VARIANT_NAMES if res[v]["ties"]["largest_tie_block"] >= 30]
    w("# V2.4 Detector Ablation Study\n")
    w(f"_{MANDATORY_STATEMENT}_\n")
    w("## 1. Objective\n")
    w("Determine which of NidhiGuard V1's five detectors (cost anomaly, project similarity, contractor pattern, billing anomaly, geographic signal) "
      "contribute to its measured performance, by removing one detector at a time and re-scoring the same frozen evaluation projects. "
      "This is evaluation only: V1, the dataset, the labels, the V2.2 metrics and the V2.3 baselines are unchanged.\n")
    w("## 2. Experimental design\n")
    w("- Six variants: FULL (the original V1) and five ablations that each set exactly one detector's contribution to zero.\n"
      "- Scores are produced in a label-free stage from V1's own frozen component scores (`evaluation_predictions.csv`); labels are first read in the separate metrics stage, using the V2.2 metric implementation.\n"
      "- Nothing is retuned, rescaled or re-weighted. Removing a detector lowers a variant's maximum possible score by that detector's cap, and V1's level boundaries (30/60/80) are kept.\n"
      "- Ranking metrics (average precision, Precision@K, Recall@20) use the continuous score, ties broken by project_id ascending. "
      "Threshold counts use the fixed cutoffs 30 (V1's LOW/MEDIUM boundary) and 40 (the V2.2 evaluation threshold, not a native V1 boundary); because every ablation shifts scores down, "
      "threshold counts partly change by arithmetic and the ranking metrics are the fairer comparison.\n")
    f = r["v1_scoring_formula"]
    w("## 3. V1 scoring formula\n")
    w("Read from `intelligence/risk_engine.py` (`RiskEngine.score_project`), not assumed:\n")
    w(f"```\nraw_total  = {f['raw_total']}\nrisk_score = {f['risk_score']}\n```\n")
    w("| Component | Cap (its MAX_SCORE) |\n|---|--:|")
    for k in f["component_order_in_sum"]:
        w(f"| {k} | {f['component_caps'][k]} |")
    w(f"\n{f['weights'][0].upper() + f['weights'][1:]}. Levels: {f['risk_level']}. The cap of 100 never binds with these detector caps. "
      f"Recomputing this expression from the frozen component scores reproduces every frozen V1 risk_score exactly: **{f['full_variant_reproduces_frozen_v1_risk_score']}**. "
      "An ablation re-applies the same expression with one term set to 0.0 (it is not FULL minus the component).\n")
    w("## 4. Dataset\n")
    w(f"The frozen V2.1 evaluation set: **{ds['projects']} projects**, **{ds['anomalous']} anomalous**, **{ds['normal']} normal**, of which "
      f"**{ds['adversarial_normal']} are adversarial normals**. Same projects and labels as V2.2 and V2.3 (labels match their frozen hash: {ds['provenance']['labels_match_frozen_hash']}). "
      "Scenario counts: " + ", ".join(f"{k} {v}" for k, v in ds["scenario_counts"].items()) + ".\n")
    w("## 5. Variants\n")
    w("| Variant | Detector removed | Maximum possible score |\n|---|---|--:|")
    for v, e in r["variants"].items():
        w(f"| {v} | {e['ablated_component']} | {e['max_possible_score']} |")
    w("")
    w("## 6. Metrics\n")
    w("Average precision (PR-AUC, a ranking-quality measure, not accuracy); Precision@5/10/20; Recall@20 (anomalous in the top 20 / all anomalous); "
      "anomalous projects and adversarial normals at score >= 30 and >= 40; scenario-level detection. "
      "Delta = ABLATION - FULL: a negative delta means removing the detector lowered the metric.\n")
    w("## 7. Main results\n")
    w("| Variant | PR-AUC | P@5 | P@10 | P@20 | Recall@20 |\n|---|--:|--:|--:|--:|--:|")
    for t in r["comparison_table"]:
        v_ = t["variant"]
        w(f"| {v_} | {_f(t['average_precision'])} | {_f(t['precision_at_5'], 2)}{mark(v_, '5')} | {_f(t['precision_at_10'], 2)}{mark(v_, '10')} | {_f(t['precision_at_20'], 2)}{mark(v_, '20')} | {_f(t['recall_at_20'])} |")
    if sens:
        w("\n\\* Tie-sensitive: " + "; ".join(
            f"{v} P@{k} is {_f(res[v]['precision_at_k'][k]['precision'], 2)} with ties broken by project_id, but could be anywhere from "
            f"{_f(res[v]['ties']['precision_at_k_tie_range'][k]['p_at_k_if_ties_ordered_worst'], 2)} to {_f(res[v]['ties']['precision_at_k_tie_range'][k]['p_at_k_if_ties_ordered_best'], 2)} "
            f"({res[v]['ties']['precision_at_k_tie_range'][k]['tied_block_at_cutoff']} projects tie at rank {k}, mixing anomalous and normal)" for v, k in sens) +
          ". Average precision is tie-aware and is not affected. All other Precision@K values are independent of tie order.")
    w("\nDeltas, ABLATION - FULL (negative = removing the detector reduced the metric):\n")
    w("| Variant | delta PR-AUC | delta P@20 | delta Recall@20 | delta P@5 | delta P@10 |\n|---|--:|--:|--:|--:|--:|")
    for v in VARIANT_NAMES[1:]:
        d = dl[v]
        w(f"| {v} | {_s(d['delta_pr_auc'])} | {_s(d['delta_precision_at_20'], 2)}{mark(v, '20')} | {_s(d['delta_recall_at_20'])} | {_s(d['delta_precision_at_5'], 2)}{mark(v, '5')} | {_s(d['delta_precision_at_10'], 2)}{mark(v, '10')} |")
    w("")
    for v in VARIANT_NAMES[1:]:
        w(f"- {v}: delta PR-AUC {_s(dl[v]['delta_pr_auc'])}; {_effect(res[v]['ablated_component'], 'PR-AUC', dl[v]['delta_pr_auc'])}.")
    w("\nThreshold counts (anomalous detected / total flagged), rank agreement with FULL, and tie structure:\n")
    w("| Variant | Anomalous >=30 | Flagged >=30 | Anomalous >=40 | Flagged >=40 | Spearman vs FULL | Top-20 shared with FULL | Distinct scores | Largest tie block (score) | Tie across rank 20/21? |\n|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for v in VARIANT_NAMES:
        t = res[v]["thresholds"]
        ti = res[v]["ties"]
        w(f"| {v} | {t['30']['anomalous_detected']} | {t['30']['flagged_total']} | {t['40']['anomalous_detected']} | {t['40']['flagged_total']} | "
          f"{_f(res[v]['spearman_with_full'])} | {res[v]['top20_overlap_with_full']} | {ti['distinct_scores']} | {ti['largest_tie_block']} ({_f(ti['largest_tie_score'], 1)}) | "
          f"{'yes' if ti['tie_straddles_top_20'] else 'no'} |")
    w("\nTies: average precision treats tied scores as a single threshold, so it does not depend on project_id order. Precision@K breaks ties by project_id ascending; "
      "a Precision@K value is tie-sensitive only if the tied block at rank K mixes anomalous and normal projects. Precision@K that depends on the tie-break: " +
      ("; ".join(f"{v} P@{k} (reported {_f(res[v]['precision_at_k'][k]['precision'], 2)}, possible range "
                 f"{_f(res[v]['ties']['precision_at_k_tie_range'][k]['p_at_k_if_ties_ordered_worst'], 2)}-{_f(res[v]['ties']['precision_at_k_tie_range'][k]['p_at_k_if_ties_ordered_best'], 2)})" for v, k in sens) or "none") + ". " +
      ("Large blocks of identical scores (projects with no signal from the remaining detectors): " + "; ".join(f"{v} has {n} projects tied at {_f(sc, 1)}" for v, n, sc in big) + "." if big else "") + "\n")
    w("## 8. Detector contribution analysis\n")
    w("Contribution = AP(FULL) - AP(variant); positive means the detector helped on this evaluation set. Intervals are from a paired bootstrap of AP(variant) - AP(FULL).\n")
    w("| Rank | Detector removed | Contribution (AP) | Contribution (P@20) | Contribution (Recall@20) | Interval of delta AP | Removal reliably hurts? |\n|--:|---|--:|--:|--:|---|---|")
    for i, e in enumerate(ca["ranking_by_ap_contribution"], 1):
        lo, hi = e["ci95_delta_ap"]
        w(f"| {i} | {e['component']} | {_s(e['contribution_ap'])} | {_s(e['contribution_p20'], 2)} | {_s(e['contribution_recall20'])} | [{lo:+.3f}, {hi:+.3f}] | {'yes' if e['removal_reliably_hurts'] else 'no'} |")
    w(f"\n_{BOOTSTRAP_LABEL}_\n")
    rk = ca["ranking_by_ap_contribution"]
    first, second = rk[0], rk[1]
    w(f"- **Strongest contributor on this set:** {first['component']} (removal changes PR-AUC by {_s(-first['contribution_ap'])}).")
    w(f"- **Second strongest:** {second['component']} (removal changes PR-AUC by {_s(-second['contribution_ap'])}).")
    small = [e for e in rk if e["small_change"]]
    w(f"- **Small contribution** (|change in PR-AUC| < {SMALL_AP_DELTA}, an operational label): " + (", ".join(f"{e['component']} ({_s(-e['contribution_ap'])})" for e in small) or "none") + ".")
    imp = [e for e in rk if e["removal_improves_ap"]]
    w("- **Removal improved PR-AUC:** " + ("; ".join(f"{e['component']} ({_s(-e['contribution_ap'])}, interval [{e['ci95_delta_ap'][0]:+.3f}, {e['ci95_delta_ap'][1]:+.3f}]"
                                                     f"{', reliably' if e['removal_reliably_helps'] else ', not reliably'})" for e in imp) or "none; no ablation increased PR-AUC") + ".")
    red = [e for e in rk if e["no_headline_metric_changed"]]
    tq = [e for e in rk if e["removal_improves_top_of_queue"]]
    w("- **Removal improved a top-of-queue metric (even though PR-AUC did not rise):** " + ("; ".join(
        f"{e['component']} (" + ", ".join(f"{k.replace('delta_', '').replace('_', ' ')} {_s(v, 2 if 'precision' in k else 3)}" for k, v in e["removal_improves_top_of_queue"].items()) + ")" for e in tq)
        or "none") + ". Precision@K looks only at the first K projects, whereas PR-AUC weighs the whole ranking, so the two can disagree.")
    w("- **Removal changed no headline metric** (PR-AUC, P@5/10/20, Recall@20, detections and adversarial flags at 30/40 all identical to FULL): " + (", ".join(e["component"] for e in red) or "none") + ".")
    adv_low = [e for e in rk if e["removal_lowers_adversarial_top_20"]]
    w("- **Removal lowered the number of adversarial normals in the top 20 (a scale-free measure):** " + (", ".join(e["component"] for e in adv_low) or "none") + ".")
    car = r["scenario_carrier_components"]
    w("- **Which detector's points separate each scenario from ordinary projects in V1's own scores** (mean component points above the NORMAL scenario, at least 1 point): " + "; ".join(
        f"{sn}: " + (", ".join(f"{e['component'].replace('_score', '').replace('_', ' ')} +{e['mean_points_above_normal']:.1f}" for e in lst) or "none") for sn, lst in car.items()) +
      ". A detector can matter to the ranking because it is the only one separating a scenario, even when its average gap between anomalous and normal projects is small.")
    w("- Reading: these statements describe what happened when one detector was removed from this scoring formula on this dataset; "
      "they do not establish that any detector is unnecessary in general, and one-at-a-time removal cannot show how detectors compensate for each other.\n")
    cm, cl = r["full_mean_component_scores_by_scenario"], r["full_mean_component_scores_by_label"]
    short = {"cost_anomaly_score": "cost (max 25)", "project_similarity_score": "similarity (max 25)", "contractor_pattern_score": "contractor (max 20)",
             "billing_anomaly_score": "billing (max 20)", "geographic_signal_score": "geographic (max 10)"}
    w("Context: mean V1 component score per scenario (FULL variant), i.e. how many points each detector contributes on average:\n")
    w("| Group | " + " | ".join(short.values()) + " |\n|---|" + "--:|" * len(short))
    for g, row in cl.items():
        w(f"| all {g} | " + " | ".join(_f(row[c], 1) for c in short) + " |")
    for sname, row in cm.items():
        w(f"| {sname} | " + " | ".join(_f(row[c], 1) for c in short) + " |")
    w("")
    w("## 9. Adversarial-normal analysis\n")
    w("Max score, number flagged, and rank position of the 41 adversarial normals (legitimate look-alikes); a variant can gain anomaly detections while also flagging more of them. "
      "Flag counts at fixed cutoffs fall for every ablation partly because all scores shift down, so the scale-free columns (adversarial normals in the top 10 / top 20, rank of the best-placed one) are the fairer false-positive comparison.\n")
    w("| Variant | Max adversarial score | Flagged >=30 | Flagged >=40 | In top 10 | In top 20 | Best-placed adversarial rank | delta max score | delta flagged >=30 | delta flagged >=40 | delta in top 20 |\n|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for v in VARIANT_NAMES:
        a = res[v]["adversarial_normal"]
        d = dl.get(v)
        w(f"| {v} | {_f(a['max_score'], 1)} | {a['flagged_at_30']} | {a['flagged_at_40']} | {a['in_top_10']} | {a['in_top_20']} | {a['best_rank']} | "
          f"{_s(d['delta_adversarial_max_score'], 1) if d else '-'} | {_s(d['delta_adversarial_flagged_at_30'], 0) if d else '-'} | "
          f"{_s(d['delta_adversarial_flagged_at_40'], 0) if d else '-'} | {_s(d['delta_adversarial_in_top_20'], 0) if d else '-'} |")
    subs = sorted(res["FULL"]["adversarial_normal"]["by_subtype"])
    w("\nAdversarial normals flagged at >= 30, by subtype:\n")
    w("| Variant | " + " | ".join(f"ADV-{s} (n={res['FULL']['adversarial_normal']['by_subtype'][s]['n']})" for s in subs) + " |\n|---|" + "--:|" * len(subs))
    for v in VARIANT_NAMES:
        w(f"| {v} | " + " | ".join(str(res[v]["adversarial_normal"]["by_subtype"][s]["flagged_at_30"]) for s in subs) + " |")
    w("")
    w("## 10. Scenario-level analysis\n")
    w("Anomalous projects detected at score >= 30 / >= 40 per scenario, and mean percentile rank (1.0 = top-ranked, comparable across variants). "
      "Detection at fixed cutoffs falls partly by arithmetic when a detector's points are removed; the percentile column is scale-free.\n")
    anom = ("COST_ANOMALY", "BILLING_ANOMALY", "CONTRACTOR_PATTERN", "SIMILAR_PROJECT", "GEOGRAPHIC_PATTERN", "MULTI_SIGNAL")
    w("| Scenario (n) | " + " | ".join(VARIANT_NAMES) + " |\n|---|" + "--:|" * len(VARIANT_NAMES))
    for s in anom:
        n = res["FULL"]["scenario_level"][s]["n"]
        w(f"| {s} ({n}) | " + " | ".join(f"{res[v]['scenario_level'][s]['flagged_at_30']} / {res[v]['scenario_level'][s]['flagged_at_40']}" for v in VARIANT_NAMES) + " |")
    w("\nMean percentile rank (relative: a scenario's percentile can rise when another scenario's detector is removed, because the other projects fall, "
      "without any detector detecting that scenario better):\n")
    w("| Scenario | " + " | ".join(VARIANT_NAMES) + " |\n|---|" + "--:|" * len(VARIANT_NAMES))
    for s in anom + ("NORMAL", "ADVERSARIAL_NORMAL"):
        w(f"| {s} | " + " | ".join(_f(res[v]["scenario_level"][s]["mean_percentile_rank"], 2) for v in VARIANT_NAMES) + " |")
    changed = []
    for s in anom:
        base = res["FULL"]["scenario_level"][s]["mean_percentile_rank"]
        for v in VARIANT_NAMES[1:]:
            dpr = res[v]["scenario_level"][s]["mean_percentile_rank"] - base
            if abs(dpr) >= 0.05:
                changed.append((s, v, dpr))
    w("\nScenario/variant pairs where the mean percentile rank moved by 0.05 or more versus FULL: " +
      ("; ".join(f"{s} under {v} ({dpr:+.2f})" for s, v, dpr in changed) or "none") + ".\n")
    w("## 11. Limitations\n")
    for x in [
        MANDATORY_STATEMENT,
        "The evaluation set is synthetic (150 projects, 49 anomalous) and its scenario families were designed around the same red-flag patterns as the detectors; the results measure agreement with that definition.",
        "One-at-a-time removal measures each detector's marginal effect inside V1's additive formula. It cannot show how detectors substitute for each other, and it says nothing about adding a detector to a different system.",
        "Detector scores are additive, so removing a detector also lowers every project's score by that detector's typical value (for example, project similarity contributes a near-constant baseline to most projects); fixed-cutoff counts at 30 and 40 therefore change partly by arithmetic, and the ranking metrics are the fairer comparison.",
        "Bootstrap intervals use row resampling and ignore the linked synthetic scenario groups, so they are optimistic; with this sample size small differences are not reliable.",
        "The 'small change' cutoff (0.02 in PR-AUC) is an operational label declared in advance, not a statistical test.",
        "Detector thresholds, caps and weights were not changed; nothing here recommends changing them.",
    ]:
        w(f"- {x}")
    w("\n## 12. Conclusion\n")
    rel = [e["component"].replace("_", " ") for e in rk if e["removal_reliably_hurts"]]
    unrel = [e["component"].replace("_", " ") for e in rk if not e["removal_reliably_hurts"]]
    sents = [f"On this frozen synthetic evaluation set, removing {first['component'].replace('_', ' ')} had the largest effect on PR-AUC ({_s(-first['contribution_ap'])}) and removing "
             f"{second['component'].replace('_', ' ')} the second largest ({_s(-second['contribution_ap'])})."]
    sents.append("No ablation increased PR-AUC." if not imp else f"Removing {', '.join(e['component'].replace('_', ' ') for e in imp)} increased PR-AUC.")
    if tq:
        sents.append("The ablations disagree between the top of the queue and the whole ranking: removing " +
                     " and ".join(f"{e['component'].replace('_', ' ')} ({_tq_text(e)})" for e in tq) + " raised top-of-queue precision even though PR-AUC fell.")
    sents.append("Under the optimistic paired bootstrap, the PR-AUC decrease on removal is reliable for " + (_and(rel) if rel else "none of the detectors") +
                 (", and not reliable for " + _and(unrel) if unrel else "") + ".")
    if red:
        sents.append("Removal of " + ", ".join(e["component"].replace("_", " ") for e in red) + " changed no headline metric.")
    sents.append("These are statements about detector contribution within V1's additive scoring on this dataset; they do not show that any detector is unnecessary or sufficient in general.")
    w(" ".join(sents) + "\n")
    w(f"{MANDATORY_STATEMENT}\n")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="V2.4 detector ablation")
    ap.add_argument("--dir", default="evaluation")
    a = ap.parse_args()
    try:
        preds = write_predictions(a.dir)
        rep = compare(a.dir)
    except (M.EvaluationInputError, FileNotFoundError, ValueError) as e:
        print(f"V2.4 FAILED: {e}", file=sys.stderr)
        return 2
    print(f"Wrote {OUT_SUBDIR}/ablation_predictions.csv ({len(preds)} rows) and ablation_comparison.json/.md")
    for t in rep["comparison_table"]:
        print(f"{t['variant']:14s} AP={t['average_precision']:.3f}  P@5={t['precision_at_5']:.2f}  P@10={t['precision_at_10']:.2f}  "
              f"P@20={t['precision_at_20']:.2f}  Recall@20={t['recall_at_20']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
