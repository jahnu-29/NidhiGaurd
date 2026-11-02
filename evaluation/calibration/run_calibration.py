"""
NidhiGuard V2.5 - investigation queue / operating-point analysis (evaluation only).

Question: given V1's existing deterministic risk scores, how many projects must an investigator review at different
operating points, and what precision / recall / false-positive trade-offs result?

Nothing is tuned. The score thresholds (>= 20, 25, 30, 35, 40, 45, 50) and the Top-K capacities (5, 10, 20, 25, 30, 40, 50)
are fixed in advance below; no threshold is searched or selected using the labels, and V1's own queue rule is not changed.

Four concepts are kept apart throughout the outputs:
  model score               the deterministic V1 anomaly score (risk_score); not a probability
  evaluation threshold      a score cutoff used only to study performance on the frozen V2.1 set
  investigator operating point  a hypothetical workload constraint such as Top-20
  production threshold      what V1 actually does today: queue = every project with risk_level != LOW (risk_score >= 30)

Two strictly separated stages (same discipline as V2.3 / V2.4):
  Stage 1  build_calibration_predictions()  reads ONLY the frozen V1 reference predictions (project_id, risk_score, risk_level)
                                            and writes ranks, score bands and queue / Top-K membership flags.
  Stage 2  analyze()                        reads the labels (and the frozen V2.4 ablation scores for one supplementary
                                            scale-sensitivity table) and uses the V2.2 metrics (imported, not modified).

Nothing here imports or modifies V1, the dataset, the labels, the V2.2 metrics, the V2.3 baselines or the V2.4 ablation.

Usage (repo root):
    python -m evaluation.calibration.run_calibration --dir evaluation
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
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

from evaluation import evaluation_metrics as M

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_SUBDIR = "calibration"
PLOTS_SUBDIR = "plots"

THRESHOLDS = (20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0)       # predefined evaluation thresholds (>=)
CAPACITIES = (5, 10, 20, 25, 30, 40, 50)                       # predefined investigator operating points (Top-K)
V1_NATIVE_QUEUE_THRESHOLD = 30.0                               # V1: risk_level != LOW  <=>  risk_score >= 30
V2_2_EVALUATION_THRESHOLD = 40.0                               # used in V2.2; NOT a native V1 boundary
BANDS = (("<20", None, 20.0), ("20-24.9", 20.0, 25.0), ("25-29.9", 25.0, 30.0), ("30-34.9", 30.0, 35.0),
         ("35-39.9", 35.0, 40.0), ("40-44.9", 40.0, 45.0), ("45-49.9", 45.0, 50.0), (">=50", 50.0, None))   # [lo, hi)
ANOMALOUS_SCENARIOS = M.ANOMALOUS_SCENARIOS
MANDATORY_CLAIM = ("V2.5 evaluates how NidhiGuard's deterministic risk scores translate into investigation workload. Rather than arbitrarily "
                   "tuning a fraud threshold, the evaluation compares predefined score thresholds and Top-K operating points, exposing the "
                   "precision/recall and false-positive trade-offs for investigators.")
DEFINITIONS = {
    "model_score": "The deterministic anomaly/risk score produced by V1 (risk_score, 0-100 scale, in practice compressed). It is not a probability of fraud.",
    "evaluation_threshold": "A score cutoff (risk_score >= T) used only to study performance on the frozen V2.1 set. It is not calibrated for production.",
    "investigator_operating_point": "A hypothetical workload constraint such as Top-20 (review the 20 highest-scored projects). It does not represent actual staffing.",
    "production_threshold": "What V1 actually does today: the investigation queue is every project whose risk_level is not LOW (risk_score >= 30), ranked by score descending.",
}


# --------------------------------------------------------------------------- #
# Stage 1 - label-free ranking and membership flags
# --------------------------------------------------------------------------- #
def v1_risk_level(score: float) -> str:
    """V1's level boundaries (classify_risk_level): unchanged."""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def band_of(score: float) -> str:
    for name, lo, hi in BANDS:
        if (lo is None or score >= lo) and (hi is None or score < hi):
            return name
    raise ValueError(f"score {score} fits no band")


def load_scores(eval_dir: str) -> pd.DataFrame:
    """The frozen V1 outputs this stage ranks: project_id, risk_score, risk_level."""
    df = pd.read_csv(os.path.join(eval_dir, "evaluation_predictions.csv"), usecols=["project_id", "risk_score", "risk_level"],
                     dtype={"project_id": str})
    if not df["project_id"].is_unique:
        raise ValueError("duplicate project_id in the V1 reference predictions")
    s = df["risk_score"].to_numpy(dtype=float)
    if not np.isfinite(s).all() or (s < 0).any() or (s > 100).any():
        raise ValueError("risk_score outside 0..100 or non-finite")
    bad = df[df["risk_level"] != df["risk_score"].map(v1_risk_level)]
    if len(bad):
        raise ValueError(f"risk_level disagrees with V1's boundaries for {len(bad)} projects")
    return df.sort_values("project_id").reset_index(drop=True)


def build_calibration_predictions(eval_dir: str) -> pd.DataFrame:
    """One row per project: rank (score desc, project_id asc), tie size, score band, queue and Top-K membership flags."""
    sc = load_scores(eval_dir)
    order = sc.sort_values(["risk_score", "project_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    rank = dict(zip(order.project_id, range(1, len(order) + 1)))
    ties = sc["risk_score"].map(sc["risk_score"].value_counts())
    out = pd.DataFrame({"project_id": sc.project_id, "risk_score": sc.risk_score, "risk_level": sc.risk_level,
                        "rank": sc.project_id.map(rank), "tie_group_size": ties.astype(int),
                        "score_band": sc.risk_score.map(band_of)})
    native = (sc.risk_level != "LOW").astype(int)
    if not (native == (sc.risk_score >= V1_NATIVE_QUEUE_THRESHOLD).astype(int)).all():
        raise ValueError("V1 queue rule (level != LOW) is not equivalent to score >= 30 on these scores")
    out["in_v1_native_queue"] = native
    for t in THRESHOLDS:
        out[f"queued_at_ge_{t:g}"] = (sc.risk_score >= t).astype(int)
    for k in CAPACITIES:
        out[f"in_top_{k}"] = (out["rank"] <= k).astype(int)
    return out.sort_values("project_id").reset_index(drop=True)


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _write_text(path: str, text: str) -> None:
    """LF newlines and UTF-8 on every platform (Windows text mode would emit CRLF)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def manifest(eval_dir: str) -> dict:
    """Hashes of everything V2.5 must not change."""
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
        "v2_4_ablation": {rel_eval(p): _sha(p) for p in sorted(glob.glob(os.path.join(eval_dir, "ablation", "*.py"))) + [
            os.path.join(eval_dir, "ablation", f) for f in ("ablation_predictions.csv", "ablation_predictions_meta.json",
                                                            "ablation_comparison.json", "ablation_comparison.md")]},
    }


def build_meta(eval_dir: str, preds: pd.DataFrame) -> dict:
    with open(os.path.join(eval_dir, "evaluation_metadata.json"), encoding="utf-8") as fh:
        frozen = json.load(fh)["file_sha256"]
    return {
        "stage": "V2.5 calibration predictions (label-free)",
        "number_of_projects": int(len(preds)),
        "definitions": DEFINITIONS,
        "predefined_evaluation_thresholds": list(THRESHOLDS),
        "predefined_investigator_capacities": list(CAPACITIES),
        "score_bands": [{"band": n, "lower_inclusive": lo, "upper_exclusive": hi} for n, lo, hi in BANDS],
        "v1_queue_rule": "production queue = every project with risk_level != LOW, i.e. risk_score >= 30 (V1 route /api/investigation-queue), sorted by score descending",
        "v1_risk_level_boundaries": "LOW < 30 <= MEDIUM < 60 <= HIGH < 80 <= CRITICAL (unchanged)",
        "rank_definition": "risk_score descending, project_id ascending for ties; 1 = highest. The V1 production route sorts by score only (stable), so its tie order is not project_id; "
                           "the evaluation fixes project_id order so results are deterministic.",
        "no_threshold_search": "thresholds and capacities are the fixed lists above; none was chosen from the labels",
        "inputs_read": ["evaluation_predictions.csv (frozen V1 reference: project_id, risk_score, risk_level)"],
        "inputs_never_read_in_this_stage": ["evaluation_labels.csv", "engine_input/* (dataset and planted signals)", "V2.3 / V2.4 outputs"],
        "input_hashes": {"evaluation_predictions.csv": _sha(os.path.join(eval_dir, "evaluation_predictions.csv")),
                         "engine_input": {k: v for k, v in frozen.items() if k.startswith("engine_input/")}},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "frozen_manifest": manifest(eval_dir),
        "note": "No timestamp and no machine-specific path is stored so that repeated runs produce byte-identical files.",
    }


# --------------------------------------------------------------------------- #
# Stage 2 - analysis (labels are read here, and only here)
# --------------------------------------------------------------------------- #
def captured_range(ranked: pd.DataFrame, k: int) -> dict:
    """Exact fewest / most anomalous projects the Top-K queue could contain under any ordering of the tied block at the cutoff."""
    cut = ranked.risk_score.iloc[k - 1]
    above, tied = ranked[ranked.risk_score > cut], ranked[ranked.risk_score == cut]
    slots, a, t, base = k - len(above), int(tied.y_true.sum()), len(tied), int(above.y_true.sum())
    return {"tied_at_cutoff": int(t), "slots_filled_from_tie": int(slots), "tied_excluded": int(t - slots),
            "captured_if_ties_ordered_worst": base + max(0, slots - (t - a)), "captured_if_ties_ordered_best": base + min(slots, a)}


def _scenario_counts(sel: pd.DataFrame) -> dict:
    return {s: int((sel.scenario_type == s).sum()) for s in ANOMALOUS_SCENARIOS}


def _adv(sel: pd.DataFrame, n_adv_total: int) -> dict:
    a = sel[sel.scenario_type == "ADVERSARIAL_NORMAL"]
    return {"adversarial_queued": int(len(a)), "adversarial_queued_pct": len(a) / n_adv_total if n_adv_total else None,
            "adversarial_ids": sorted(a.project_id), "plain_normal_queued": int((sel.scenario_type == "NORMAL").sum())}


def threshold_rows(df: pd.DataFrame, ranked: pd.DataFrame, n_adv: int) -> list:
    rows = []
    n = len(df)
    for t in THRESHOLDS:
        c = M.thresholded(df, t)
        sel = df[df.risk_score >= t]
        q = int(c["predicted_positive"])
        top_q = set(ranked.project_id.iloc[:q]) if q else set()
        rows.append({
            "threshold": t, "kind": ("production threshold (V1 native queue boundary; MEDIUM floor)" if t == V1_NATIVE_QUEUE_THRESHOLD else
                                     "evaluation threshold (V2.2 primary; not a native V1 boundary)" if t == V2_2_EVALUATION_THRESHOLD else "evaluation threshold"),
            "projects_queued": q, "pct_of_dataset": q / n, "tp": c["tp"], "fp": c["fp"], "tn": c["tn"], "fn": c["fn"],
            "precision": c["precision"], "recall": c["recall"], "f1": c["f1"],
            "anomalous_captured": c["tp"], "normal_incorrectly_queued": c["fp"],
            **_adv(sel, n_adv), "scenario_captured": _scenario_counts(sel),
            "selection_identical_to_top_q": bool(set(sel.project_id) == top_q),
        })
    return rows


def topk_rows(df: pd.DataFrame, ranked: pd.DataFrame, n_adv: int) -> list:
    n, n_pos = len(df), int(df.y_true.sum())
    first_norm = int(np.argmax((ranked.y_true == 0).to_numpy()))
    hn = ranked.iloc[first_norm]
    rows = []
    for k in CAPACITIES:
        sel = ranked.iloc[:k]
        tp = int(sel.y_true.sum())
        cr = captured_range(ranked, k)
        rows.append({
            "capacity": k, "pct_of_dataset": k / n, "anomalous_captured": tp, "recall": tp / n_pos, "precision": tp / k,
            "false_positives": k - tp, "lowest_selected_score": float(ranked.risk_score.iloc[k - 1]),
            "highest_ranked_normal": {"rank": first_norm + 1, "project_id": hn.project_id, "risk_score": float(hn.risk_score),
                                      "scenario_type": hn.scenario_type, "inside_selection": bool(first_norm + 1 <= k)},
            **cr, "tie_sensitive": bool(cr["captured_if_ties_ordered_worst"] != cr["captured_if_ties_ordered_best"]),
            **_adv(sel, n_adv), "scenario_captured": _scenario_counts(sel),
        })
    return rows


def queue_curve(ranked: pd.DataFrame) -> list:
    n_pos = int(ranked.y_true.sum())
    cum = ranked.y_true.cumsum().to_numpy()
    return [{"k": i + 1, "tp": int(cum[i]), "precision": float(cum[i] / (i + 1)), "recall": float(cum[i] / n_pos)} for i in range(len(ranked))]


def distribution(df: pd.DataFrame) -> dict:
    s = df.risk_score
    q = s.quantile([0.25, 0.5, 0.75])
    def stats(x):
        return {"n": int(len(x)), "min": float(x.min()), "max": float(x.max()), "mean": float(x.mean()), "median": float(x.median())}
    bands = []
    for name, lo, hi in BANDS:
        g = df[(True if lo is None else df.risk_score >= lo) & (True if hi is None else df.risk_score < hi)]
        bands.append({"band": name, "n": int(len(g)), "anomalous": int(g.y_true.sum()), "normal": int((g.y_true == 0).sum()),
                      "adversarial_normal": int((g.scenario_type == "ADVERSARIAL_NORMAL").sum()),
                      "share_anomalous": float(g.y_true.mean()) if len(g) else None})
    levels = []
    for lv in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        g = df[df.risk_level == lv]
        levels.append({"risk_level": lv, "n": int(len(g)), "anomalous": int(g.y_true.sum()), "normal": int((g.y_true == 0).sum()),
                       "adversarial_normal": int((g.scenario_type == "ADVERSARIAL_NORMAL").sum())})
    vc = s.value_counts()
    return {"overall": {"min": float(s.min()), "max": float(s.max()), "mean": float(s.mean()), "median": float(s.median()),
                        "std_population": float(s.std(ddof=0)), "q25": float(q[0.25]), "q50": float(q[0.5]), "q75": float(q[0.75]),
                        "distinct_scores": int(vc.size), "largest_tie_block": int(vc.max()), "largest_tie_score": float(vc.idxmax())},
            "anomalous": stats(df[df.y_true == 1].risk_score), "normal": stats(df[df.y_true == 0].risk_score),
            "adversarial_normal": stats(df[df.scenario_type == "ADVERSARIAL_NORMAL"].risk_score),
            "bands": bands, "native_risk_levels": levels,
            "note": "risk_score is a deterministic anomaly score, not a probability; a score of 40 does not mean a 40% chance of fraud."}


def adversarial_overview(df: pd.DataFrame, ranked: pd.DataFrame) -> dict:
    adv = ranked[ranked.scenario_type == "ADVERSARIAL_NORMAL"]
    top = [{"rank": int(r) + 1, "project_id": row.project_id, "subtype": row.adversarial_subtype, "risk_score": float(row.risk_score)}
           for r, row in zip(adv.index[:8], adv.head(8).itertuples())]
    return {"n": int(len(adv)), "max_score": float(adv.risk_score.max()), "mean_score": float(adv.risk_score.mean()),
            "median_score": float(adv.risk_score.median()), "highest_ranked_eight": top,
            "by_subtype_max_score": {st: float(adv[adv.adversarial_subtype == st].risk_score.max()) for st in sorted(set(adv.adversarial_subtype))}}


def scale_sensitivity(eval_dir: str, labels_df: pd.DataFrame) -> list:
    """Supplementary: the same fixed cutoffs applied to the frozen V2.4 ablation scores. Shows how a fixed threshold's workload depends on
    the score scale, while a Top-K queue does not. Descriptive only; no variant or threshold is selected."""
    long = pd.read_csv(os.path.join(eval_dir, "ablation", "ablation_predictions.csv"), dtype={"project_id": str})
    lab = labels_df[["project_id", "y_true"]]
    out = []
    for v in list(dict.fromkeys(long.variant)):
        sub = long[long.variant == v].merge(lab, on="project_id", validate="one_to_one")
        ranked = sub.sort_values(["ablation_score", "project_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
        row = {"variant": v, "highest_score_observed": float(sub.ablation_score.max())}
        for t in (30.0, 40.0):
            sel = sub[sub.ablation_score >= t]
            row[f"queued_at_ge_{t:g}"], row[f"anomalous_at_ge_{t:g}"] = int(len(sel)), int(sel.y_true.sum())
        for k in (10, 20):
            row[f"anomalous_in_top_{k}"] = int(ranked.y_true.iloc[:k].sum())
        out.append(row)
    return out


def _round(o, nd=6):
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (float, np.floating)):
        return None if math.isnan(float(o)) else round(float(o), nd)
    if isinstance(o, np.integer):
        return int(o)
    return o


def write_predictions(eval_dir: str) -> pd.DataFrame:
    out_dir = os.path.join(eval_dir, OUT_SUBDIR)
    os.makedirs(os.path.join(out_dir, PLOTS_SUBDIR), exist_ok=True)
    preds = build_calibration_predictions(eval_dir)
    _write_text(os.path.join(out_dir, "calibration_predictions.csv"), preds.to_csv(index=False, lineterminator="\n"))
    _write_text(os.path.join(out_dir, "calibration_metadata.json"), json.dumps(build_meta(eval_dir, preds), indent=2) + "\n")
    return preds


def analyze(eval_dir: str) -> dict:
    prov = M.verify_provenance(eval_dir)
    if not (prov["labels_match_frozen_hash"] and prov["predictions_made_from_frozen_engine_input"]):
        raise M.EvaluationInputError(f"provenance check failed; refusing to evaluate: {prov}")
    out_dir = os.path.join(eval_dir, OUT_SUBDIR)
    with open(os.path.join(out_dir, "calibration_metadata.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    if meta["input_hashes"]["evaluation_predictions.csv"] != prov["predictions_sha256"]:
        raise M.EvaluationInputError("calibration was not built from the frozen V1 reference predictions")
    cal = pd.read_csv(os.path.join(out_dir, "calibration_predictions.csv"), dtype={"project_id": str})
    _, labels = M.load_csvs(os.path.join(eval_dir, "evaluation_predictions.csv"), os.path.join(eval_dir, "evaluation_labels.csv"))
    df = M.prepare(cal[["project_id", "risk_score", "risk_level"]], labels)
    ranked = M.rank(df)
    if list(ranked.project_id) != list(cal.sort_values("rank").project_id):
        raise M.EvaluationInputError("stage-1 ranking disagrees with the V2.2 ranking")
    n_adv = int((df.scenario_type == "ADVERSARIAL_NORMAL").sum())
    thr, topk = threshold_rows(df, ranked, n_adv), topk_rows(df, ranked, n_adv)
    sens = scale_sensitivity(eval_dir, df)
    report = {
        "dataset": {"projects": int(len(df)), "anomalous": int(df.y_true.sum()), "normal": int((df.y_true == 0).sum()),
                    "adversarial_normal": n_adv, "scenario_counts": {s: int((df.scenario_type == s).sum()) for s in M.SCENARIO_ORDER},
                    "same_projects_and_labels_as_v2_2_to_v2_4": True, "provenance": prov},
        "v1_facts": {"score_formula": "risk_score = round(min(100.0, cost + similarity + contractor + billing + geographic), 1); caps 25/25/20/20/10",
                     "risk_level_boundaries": meta["v1_risk_level_boundaries"], "production_queue_rule": meta["v1_queue_rule"],
                     "frozen_prediction_file": "evaluation/evaluation_predictions.csv", "score_column": "risk_score"},
        "definitions": DEFINITIONS,
        "predefined_evaluation_thresholds": list(THRESHOLDS), "predefined_investigator_capacities": list(CAPACITIES),
        "score_distribution": distribution(df),
        "threshold_table": thr, "top_k_table": topk, "queue_curve": queue_curve(ranked),
        "adversarial_normal": adversarial_overview(df, ranked),
        "scale_sensitivity_of_fixed_thresholds": sens,
        "mandatory_claim": MANDATORY_CLAIM,
    }
    report["candidate_operating_points"] = candidates(thr, topk)
    report = _round(report)
    _write_text(os.path.join(out_dir, "calibration_results.json"), json.dumps(report, indent=2) + "\n")
    _write_text(os.path.join(out_dir, "calibration_report.md"), render_markdown(report))
    for name, svg in render_plots(report).items():
        _write_text(os.path.join(out_dir, PLOTS_SUBDIR, name), svg)
    return report


def candidates(thr: list, topk: list) -> list:
    """Descriptive candidates chosen for workload reasons from the predefined lists, not because any metric is highest."""
    t = {r["threshold"]: r for r in thr}
    k = {r["capacity"]: r for r in topk}
    def pack(name, kind, row, size, why):
        return {"name": name, "kind": kind, "queue_size": size, "pct_of_dataset": row["pct_of_dataset"],
                "anomalous_captured": row["anomalous_captured"], "precision": row["precision"], "recall": row["recall"],
                "false_positives": size - row["anomalous_captured"], "adversarial_queued": row["adversarial_queued"], "why": why}
    return [
        pack("V1 native queue: risk_score >= 30", "production threshold", t[30.0], t[30.0]["projects_queued"],
             "This is what V1 does today (every non-LOW project); it is the baseline any alternative must be compared with."),
        pack("Top-10", "investigator operating point", k[10], 10,
             "A small high-priority tier for a reviewer with very little capacity; about 7% of this pool."),
        pack("Top-20", "investigator operating point", k[20], 20,
             "Roughly the same workload as the native queue, but fixed in size however the score scale moves."),
        pack("risk_score >= 40", "evaluation threshold", t[40.0], t[40.0]["projects_queued"],
             "A narrow high-score tier, shown for continuity with V2.2; not a V1 boundary."),
        pack("Top-40", "investigator operating point", k[40], 40,
             "A deliberately wide net (about 27% of the pool) to show how much precision is given up for coverage."),
    ]


# --------------------------------------------------------------------------- #
# Plots: dependency-free SVG (byte-deterministic on every platform)
# --------------------------------------------------------------------------- #
W, H, X0, X1, Y0, Y1 = 760, 440, 78, 730, 380, 56
C_ANOM, C_NORM, C_ADV, C_LINE2 = "#b03a2e", "#5d8aa8", "#d68910", "#1e8449"


def _n(x: float) -> str:
    return f"{x:.2f}"


def _frame(title: str, desc: str, xlabel: str, ylabel: str) -> list:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif" font-size="12">',
            f"<title>{escape(title)}</title>", f"<desc>{escape(desc)}</desc>", f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
            f'<text x="{_n(W / 2)}" y="28" text-anchor="middle" font-size="16" font-weight="bold">{escape(title)}</text>',
            f'<text x="{_n((X0 + X1) / 2)}" y="{H - 14}" text-anchor="middle">{escape(xlabel)}</text>',
            f'<text x="20" y="{_n((Y0 + Y1) / 2)}" text-anchor="middle" transform="rotate(-90 20 {_n((Y0 + Y1) / 2)})">{escape(ylabel)}</text>']


def _y_axis(ymin: float, ymax: float, ticks: list, fmt) -> tuple:
    sy = lambda v: Y0 - (v - ymin) / (ymax - ymin) * (Y0 - Y1)
    parts = []
    for t in ticks:
        parts.append(f'<line x1="{X0}" y1="{_n(sy(t))}" x2="{X1}" y2="{_n(sy(t))}" stroke="#dddddd"/>')
        parts.append(f'<text x="{X0 - 8}" y="{_n(sy(t) + 4)}" text-anchor="end">{escape(fmt(t))}</text>')
    parts.append(f'<line x1="{X0}" y1="{Y0}" x2="{X1}" y2="{Y0}" stroke="#333333"/><line x1="{X0}" y1="{Y0}" x2="{X0}" y2="{Y1}" stroke="#333333"/>')
    return sy, parts


def _legend(items: list, x: float, y: float) -> list:
    out = []
    for i, (name, color) in enumerate(items):
        out.append(f'<rect x="{_n(x)}" y="{_n(y + i * 18)}" width="12" height="12" fill="{color}"/>')
        out.append(f'<text x="{_n(x + 18)}" y="{_n(y + i * 18 + 10)}">{escape(name)}</text>')
    return out


def _legend_h(items: list, x_right: float, y: float) -> list:
    """Horizontal legend in the top margin, right-aligned, so it never covers data."""
    widths = [30 + 7 * len(name) for name, _ in items]
    x = x_right - sum(widths)
    out = []
    for (name, color), wd in zip(items, widths):
        out.append(f'<rect x="{_n(x)}" y="{_n(y)}" width="12" height="12" fill="{color}"/>')
        out.append(f'<text x="{_n(x + 18)}" y="{_n(y + 10)}">{escape(name)}</text>')
        x += wd
    return out


def _line_chart(title, desc, xlabel, ylabel, xlim, ylim, xticks, yticks, xfmt, yfmt, series) -> str:
    sx = lambda v: X0 + (v - xlim[0]) / (xlim[1] - xlim[0]) * (X1 - X0)
    sy, parts = _y_axis(ylim[0], ylim[1], yticks, yfmt)
    out = _frame(title, desc, xlabel, ylabel) + parts
    for t in xticks:
        out.append(f'<line x1="{_n(sx(t))}" y1="{Y0}" x2="{_n(sx(t))}" y2="{Y0 + 5}" stroke="#333333"/>')
        out.append(f'<text x="{_n(sx(t))}" y="{Y0 + 20}" text-anchor="middle">{escape(xfmt(t))}</text>')
    for s in series:
        pts = " ".join(f"{_n(sx(x))},{_n(sy(y))}" for x, y in s["points"])
        out.append(f'<polyline fill="none" stroke="{s["color"]}" stroke-width="2" points="{pts}"/>')
        for x, y in s.get("markers", []):
            out.append(f'<circle cx="{_n(sx(x))}" cy="{_n(sy(y))}" r="4" fill="{s["color"]}" stroke="#ffffff"/>')
    out += _legend_h([(s["name"], s["color"]) for s in series], X1, 36)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _bar_chart(title, desc, xlabel, ylabel, cats, stacks, ymax, yticks) -> str:
    sy, parts = _y_axis(0.0, ymax, yticks, lambda v: f"{v:g}")
    out = _frame(title, desc, xlabel, ylabel) + parts
    slot = (X1 - X0) / len(cats)
    bw = slot * 0.6
    for i, c in enumerate(cats):
        x = X0 + i * slot + (slot - bw) / 2
        base = 0.0
        for st in stacks:
            v = st["values"][i]
            if v:
                out.append(f'<rect x="{_n(x)}" y="{_n(sy(base + v))}" width="{_n(bw)}" height="{_n(sy(base) - sy(base + v))}" fill="{st["color"]}"/>')
            base += v
        out.append(f'<text x="{_n(x + bw / 2)}" y="{_n(sy(base) - 6)}" text-anchor="middle">{int(base)}</text>')
        out.append(f'<text x="{_n(x + bw / 2)}" y="{Y0 + 20}" text-anchor="middle">{escape(c)}</text>')
    out += _legend([(s["name"], s["color"]) for s in stacks], X1 - 215, Y1 + 8)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_plots(r: dict) -> dict:
    d = r["dataset"]
    bands = r["score_distribution"]["bands"]
    plain = [b["normal"] - b["adversarial_normal"] for b in bands]
    ymax = max(b["n"] for b in bands)
    ymax = int(math.ceil(ymax / 20.0) * 20)
    plots = {"score_distribution.svg": _bar_chart(
        "V1 risk-score distribution (frozen V2.1 set)", "Projects per score band, split into anomalous, plain normal and adversarial normal.",
        "risk_score band", "projects", [b["band"] for b in bands],
        [{"name": "anomalous", "color": C_ANOM, "values": [b["anomalous"] for b in bands]},
         {"name": "normal (plain)", "color": C_NORM, "values": plain},
         {"name": "adversarial normal", "color": C_ADV, "values": [b["adversarial_normal"] for b in bands]}],
        ymax, list(range(0, ymax + 1, 20)))}
    curve = r["queue_curve"]
    caps = r["predefined_investigator_capacities"]
    n = d["projects"]
    xt = list(range(0, n + 1, 25))
    for key, name, fname, color, label in (("recall", "recall", "queue_size_vs_recall.svg", C_ANOM, "recall"),
                                           ("precision", "precision", "queue_size_vs_precision.svg", C_NORM, "precision")):
        pts = [(c["k"], c[key]) for c in curve]
        plots[fname] = _line_chart(
            f"Queue size vs {label} (Top-K by risk score)", f"{label.capitalize()} when the K highest-scored projects are reviewed; markers show the predefined capacities.",
            "projects reviewed (K)", label, (0, n), (0.0, 1.0), xt, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], lambda v: f"{v:g}", lambda v: f"{v:.1f}",
            [{"name": label, "color": color, "points": pts, "markers": [(c["k"], c[key]) for c in curve if c["k"] in caps]}])
    thr = r["threshold_table"]
    cats = [f">={t['threshold']:g}" for t in thr]
    ymax_q = int(math.ceil(max(t["projects_queued"] for t in thr) / 10.0) * 10)
    plots["threshold_vs_queued.svg"] = _bar_chart(
        "Projects queued by score threshold", "Projects queued at each predefined threshold, split into anomalous captured, adversarial normals and other normals.",
        "evaluation threshold (risk_score >=)", "projects queued", cats,
        [{"name": "anomalous captured", "color": C_ANOM, "values": [t["tp"] for t in thr]},
         {"name": "adversarial normal queued", "color": C_ADV, "values": [t["adversarial_queued"] for t in thr]},
         {"name": "other normal queued", "color": C_NORM, "values": [t["plain_normal_queued"] for t in thr]}],
        ymax_q, list(range(0, ymax_q + 1, 10)))
    tv = [t["threshold"] for t in thr]
    plots["threshold_vs_precision_recall.svg"] = _line_chart(
        "Precision and recall by score threshold", "Precision and recall at each predefined evaluation threshold.",
        "evaluation threshold (risk_score >=)", "precision / recall", (20.0, 50.0), (0.0, 1.0), tv, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        lambda v: f"{v:g}", lambda v: f"{v:.1f}",
        [{"name": "precision", "color": C_NORM, "points": [(t["threshold"], t["precision"]) for t in thr if t["precision"] is not None],
          "markers": [(t["threshold"], t["precision"]) for t in thr if t["precision"] is not None]},
         {"name": "recall", "color": C_ANOM, "points": [(t["threshold"], t["recall"]) for t in thr],
          "markers": [(t["threshold"], t["recall"]) for t in thr]}])
    return plots


# --------------------------------------------------------------------------- #
# Markdown report (all numbers and prose are generated from the computed results)
# --------------------------------------------------------------------------- #
def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def _p(x, nd=1):
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def _and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _or(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def render_markdown(r: dict) -> str:
    ds, sd, thr, tk = r["dataset"], r["score_distribution"], r["threshold_table"], r["top_k_table"]
    ov, adv, sens = r["v1_facts"], r["adversarial_normal"], r["scale_sensitivity_of_fixed_thresholds"]
    T = {t["threshold"]: t for t in thr}
    K = {k["capacity"]: k for k in tk}
    o = sd["overall"]
    L = []
    w = L.append
    w("# V2.5 Investigation Queue and Operating-Point Analysis\n")
    w(f"_{MANDATORY_CLAIM}_\n")
    w("## 1. Objective, scope and vocabulary\n")
    w("Show how V1's existing deterministic risk scores translate into investigation workload on the frozen V2.1 evaluation set: how many projects "
      "must be reviewed at each operating point, and what precision, recall and false-positive trade-offs follow. This stage is evaluation only. "
      "V1, its thresholds, weights and queue rule, the dataset, the labels and the V2.2 to V2.4 implementations are unchanged. No threshold was searched or "
      "chosen using the labels: the thresholds and capacities below were fixed in advance.\n")
    w("Four concepts are kept separate:\n")
    for k, v in DEFINITIONS.items():
        w(f"- **{k.replace('_', ' ').capitalize()}**: {v}")
    w("")
    w("## 2. Frozen inputs and V1 facts\n")
    w(f"- Score formula: `{ov['score_formula']}`.")
    w(f"- Risk-level boundaries: {ov['risk_level_boundaries']}.")
    w(f"- Production queue rule: {ov['production_queue_rule']}.")
    w(f"- Dataset: **{ds['projects']} projects**, **{ds['anomalous']} anomalous**, **{ds['normal']} normal** (including **{ds['adversarial_normal']} adversarial normals**); "
      f"the same projects and labels as V2.2 to V2.4 (labels match their frozen hash: {ds['provenance']['labels_match_frozen_hash']}).")
    w(f"- Scores come from the frozen `{ov['frozen_prediction_file']}` (column `{ov['score_column']}`). Ranking: score descending, project_id ascending for ties; "
      "V1's production route sorts by score only, so its tie order can differ from this evaluation ordering.\n")
    w("## 3. Score distribution\n")
    w(f"Minimum {_f(o['min'], 1)}, maximum {_f(o['max'], 1)}, mean {_f(o['mean'], 2)}, median {_f(o['median'], 2)}, standard deviation {_f(o['std_population'], 2)} (population), "
      f"quartiles {_f(o['q25'], 2)} / {_f(o['q50'], 2)} / {_f(o['q75'], 2)}. There are {o['distinct_scores']} distinct scores; the largest tie block is "
      f"{o['largest_tie_block']} projects at {_f(o['largest_tie_score'], 1)}.\n")
    w("| Score band | Projects | Anomalous | Normal | of which adversarial | Share anomalous |\n|---|--:|--:|--:|--:|--:|")
    for b in sd["bands"]:
        w(f"| {b['band']} | {b['n']} | {b['anomalous']} | {b['normal']} | {b['adversarial_normal']} | {_p(b['share_anomalous'])} |")
    w("")
    w("| V1 risk level | Projects | Anomalous | Normal | of which adversarial |\n|---|--:|--:|--:|--:|")
    for lv in sd["native_risk_levels"]:
        w(f"| {lv['risk_level']} | {lv['n']} | {lv['anomalous']} | {lv['normal']} | {lv['adversarial_normal']} |")
    empty = [lv["risk_level"] for lv in sd["native_risk_levels"] if lv["n"] == 0]
    w(f"\nWhat this means for queue sizing: the observed scores occupy only {_f(o['min'], 1)}-{_f(o['max'], 1)} of the theoretical 0-100 scale"
      + (f", and no project reaches {_or(empty)}" if empty else "") + f". Mean score is {_f(sd['anomalous']['mean'], 1)} for anomalous and {_f(sd['normal']['mean'], 1)} for normal projects. "
      "Because the scale is compressed, a cutoff expressed in points moves the queue size by a lot per few points (see section 4), and a score is a deterministic anomaly score, "
      "not a probability: a score of 40 does not mean a 40% chance of fraud.\n")
    w("## 4. Fixed-score evaluation thresholds\n")
    w("Evaluation thresholds, fixed in advance. Only 30 is V1's own boundary (the production queue floor); 40 was the V2.2 evaluation threshold and is not a native V1 boundary.\n")
    w("| Threshold | Queued | % of dataset | TP | FP | TN | FN | Precision | Recall | F1 | Adversarial queued | % of adversarial | Plain normals queued |\n|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for t in thr:
        tag = " (V1 production queue)" if t["threshold"] == V1_NATIVE_QUEUE_THRESHOLD else " (V2.2 eval. threshold)" if t["threshold"] == V2_2_EVALUATION_THRESHOLD else ""
        w(f"| >= {t['threshold']:g}{tag} | {t['projects_queued']} | {_p(t['pct_of_dataset'])} | {t['tp']} | {t['fp']} | {t['tn']} | {t['fn']} | "
          f"{_f(t['precision'])} | {_f(t['recall'])} | {_f(t['f1'])} | {t['adversarial_queued']} | {_p(t['adversarial_queued_pct'])} | {t['plain_normal_queued']} |")
    w("\nAnomalous projects captured = TP; normal projects incorrectly queued = FP. Precision is n/a when nothing is queued.\n")
    w("## 5. Investigator-capacity operating points (Top-K)\n")
    w("Hypothetical workload constraints, labelled as evaluation operating points; they do not represent real staffing levels.\n")
    w("| Top-K | % of dataset | Anomalous captured | Recall | Precision | False positives | Lowest selected score | Tie at cutoff | Adversarial in queue | Highest-ranked normal |\n|--:|--:|--:|--:|--:|--:|--:|---|--:|---|")
    for k in tk:
        tie = ("none" if k["tied_at_cutoff"] == 1 else f"{k['tied_at_cutoff']} tied at {_f(k['lowest_selected_score'], 1)}; {k['tied_excluded']} outside the queue"
               + (f"; captured could be {k['captured_if_ties_ordered_worst']}-{k['captured_if_ties_ordered_best']}" if k["tie_sensitive"] else "; label mix does not matter"))
        w(f"| {k['capacity']} | {_p(k['pct_of_dataset'])} | {k['anomalous_captured']} | {_f(k['recall'])} | {_f(k['precision'])} | {k['false_positives']} | "
          f"{_f(k['lowest_selected_score'], 1)} | {tie} | {k['adversarial_queued']} | "
          f"{k['highest_ranked_normal']['project_id']} at rank {k['highest_ranked_normal']['rank']} ({'in' if k['highest_ranked_normal']['inside_selection'] else 'not in'} queue) |")
    hn = tk[0]["highest_ranked_normal"]
    w(f"\nThe highest-ranked normal project overall is {hn['project_id']} ({hn['scenario_type']}), at rank {hn['rank']} with score {_f(hn['risk_score'], 1)}; "
      f"every project ranked above it is anomalous. Ties are broken by project_id ascending, which is deterministic but arbitrary; the tie column shows where it could change a count.\n")
    w("## 6. Fixed threshold versus Top-K\n")
    ident = [t for t in thr if t["selection_identical_to_top_q"]]
    w(f"**A. Fixed-score queue** (`risk_score >= T`) versus **B. Top-K queue**. At the same queue size the two select the same projects whenever there is no tie at the cutoff: "
      f"this holds for {len(ident)} of {len(thr)} thresholds here. The difference is therefore not which projects are chosen but how the size is decided: a fixed threshold lets the "
      "score scale decide the workload, while a Top-K queue fixes the workload and lets the scale decide how deep the list goes.\n")
    nat, t20, t25 = T[30.0], K[20], K[25]
    w(f"- V1's native queue (>= 30) holds {nat['projects_queued']} projects with {nat['tp']} anomalous captured (precision {_f(nat['precision'])}, recall {_f(nat['recall'])}); "
      f"Top-20 captures {t20['anomalous_captured']} (precision {_f(t20['precision'])}, recall {_f(t20['recall'])}) and Top-25 captures {t25['anomalous_captured']} "
      f"(precision {_f(t25['precision'])}, recall {_f(t25['recall'])}).")
    drops = [(thr[i]["threshold"], thr[i + 1]["threshold"], thr[i]["projects_queued"] - thr[i + 1]["projects_queued"]) for i in range(len(thr) - 1)]
    big = max(drops, key=lambda x: x[2])
    w(f"- Workload is sensitive to a few points of score: moving the cutoff from {big[0]:g} to {big[1]:g} changes the queue by {big[2]} projects, "
      f"whereas {drops[2][0]:g} to {drops[2][1]:g} changes it by {drops[2][2]}.")
    full = [s for s in sens if s["variant"] == "FULL"][0]
    others = [s for s in sens if s["variant"] != "FULL"]
    sizes = [s["queued_at_ge_30"] for s in sens]
    w(f"- Score-scale sensitivity (supplementary, from the frozen V2.4 ablation scores; no variant or threshold is selected): applying the same `>= 30` cutoff to the six "
      f"scoring variants queues between {min(sizes)} and {max(sizes)} projects, whereas a Top-20 queue is {20} projects in every variant.")
    w("")
    w("| Scoring variant | Highest score observed | Queued at >= 30 | Anomalous at >= 30 | Queued at >= 40 | Anomalous at >= 40 | Anomalous in Top-10 | Anomalous in Top-20 |\n|---|--:|--:|--:|--:|--:|--:|--:|")
    for s in sens:
        w(f"| {s['variant']} | {_f(s['highest_score_observed'], 1)} | {s['queued_at_ge_30']} | {s['anomalous_at_ge_30']} | {s['queued_at_ge_40']} | {s['anomalous_at_ge_40']} | "
          f"{s['anomalous_in_top_10']} | {s['anomalous_in_top_20']} |")
    w("\nTrade-off. A fixed threshold is simple to state and audit and does not force a review when nothing scores high, but its workload moves with the score scale and with a few points "
      "of score. A Top-K queue gives a predictable workload and is unaffected by score-scale shifts, but it forces K reviews even when fewer projects look suspicious, and it hides "
      "that the K-th project may score barely above the (K+1)-th. V1's production queue already combines both: a ranked list with a score floor, so an investigator can stop at any rank.\n")
    w("## 7. Adversarial normals\n")
    w(f"The {adv['n']} adversarial normals are deliberately difficult legitimate cases. Their maximum score is {_f(adv['max_score'], 1)} (mean {_f(adv['mean_score'], 1)}, median {_f(adv['median_score'], 1)}).\n")
    w("| Operating point | Queue size | Adversarial queued | % of the 41 | Plain normals queued | Adversarial share of all false positives |\n|---|--:|--:|--:|--:|--:|")
    for t in thr:
        fp = t["fp"]
        w(f"| >= {t['threshold']:g} | {t['projects_queued']} | {t['adversarial_queued']} | {_p(t['adversarial_queued_pct'])} | {t['plain_normal_queued']} | {_p(t['adversarial_queued'] / fp if fp else None)} |")
    for k in tk:
        fp = k["false_positives"]
        w(f"| Top-{k['capacity']} | {k['capacity']} | {k['adversarial_queued']} | {_p(k['adversarial_queued_pct'])} | {k['plain_normal_queued']} | {_p(k['adversarial_queued'] / fp if fp else None)} |")
    w("\nHighest-scored adversarial normals (rank among all 150): " + "; ".join(
        f"{a['project_id']} ADV-{a['subtype']} score {_f(a['risk_score'], 1)} rank {a['rank']}" for a in adv["highest_ranked_eight"][:5]) + ".\n")
    w("## 8. Scenario capture\n")
    w("Anomalous projects captured per scenario, by evaluation threshold and by Top-K (denominators are the V2.1 scenario sizes).\n")
    sizes_s = {s: ds["scenario_counts"][s] for s in ANOMALOUS_SCENARIOS}
    w("| Operating point | " + " | ".join(f"{s} ({sizes_s[s]})" for s in ANOMALOUS_SCENARIOS) + " |\n|---|" + "--:|" * len(ANOMALOUS_SCENARIOS))
    for t in thr:
        w(f"| >= {t['threshold']:g} | " + " | ".join(str(t["scenario_captured"][s]) for s in ANOMALOUS_SCENARIOS) + " |")
    for k in tk:
        w(f"| Top-{k['capacity']} | " + " | ".join(str(k["scenario_captured"][s]) for s in ANOMALOUS_SCENARIOS) + " |")
    w("")
    w("## 9. Plots\n")
    for f, cap in (("score_distribution.svg", "Risk-score distribution"), ("queue_size_vs_recall.svg", "Queue size vs recall"),
                   ("queue_size_vs_precision.svg", "Queue size vs precision"), ("threshold_vs_queued.svg", "Threshold vs number queued"),
                   ("threshold_vs_precision_recall.svg", "Threshold vs precision and recall")):
        w(f"- [{cap}](plots/{f})")
    w("\nPlain SVG files generated without plotting libraries, so they are byte-identical on every run. The queue-size curves show every K for shape; markers are the predefined capacities, and no point is selected.\n")

    w("## 10. Answers to the required questions\n")
    w("**Q1. What happens to investigator workload as the score threshold increases?** It falls steadily, but unevenly: " +
      ", ".join(f">= {t['threshold']:g}: {t['projects_queued']} ({_p(t['pct_of_dataset'])})" for t in thr) +
      f". The largest single step is {big[0]:g} to {big[1]:g} (-{big[2]} projects); the step from 30 to 35 removes only {drops[2][2]}. Workload is therefore very sensitive to where a cutoff sits on this compressed scale.\n")
    prec = [t["precision"] for t in thr]
    rec = [t["recall"] for t in thr]
    prec_mono = all(prec[i] <= prec[i + 1] + 1e-12 for i in range(len(prec) - 1))
    prec_k = [k["precision"] for k in tk]
    k_mono = all(prec_k[i] >= prec_k[i + 1] - 1e-12 for i in range(len(prec_k) - 1))
    w(f"**Q2. What happens to precision and recall?** Recall falls from {_f(rec[0])} at >= 20 to {_f(rec[-1])} at >= 50 (it cannot rise as the cutoff rises). "
      f"Precision goes from {_f(prec[0])} to {_f(prec[-1])} and is {'non-decreasing' if prec_mono else 'not monotonic'} across the seven thresholds. "
      f"At V1's production boundary (>= 30): precision {_f(T[30.0]['precision'])}, recall {_f(T[30.0]['recall'])} ({T[30.0]['tp']} of {ds['anomalous']} anomalous). "
      f"At >= 40: precision {_f(T[40.0]['precision'])}, recall {_f(T[40.0]['recall'])} ({T[40.0]['tp']} of {ds['anomalous']}). "
      f"In the Top-K view the trade-off appears as K grows: recall rises from {_f(tk[0]['recall'], 2)} (Top-{tk[0]['capacity']}) to {_f(tk[-1]['recall'], 2)} (Top-{tk[-1]['capacity']}) while precision goes from "
      f"{_f(tk[0]['precision'], 2)} to {_f(tk[-1]['precision'], 2)} and is {'non-increasing' if k_mono else 'not monotonic'} across the seven capacities: "
      + ", ".join(f"Top-{k['capacity']} recall {_f(k['recall'], 2)} / precision {_f(k['precision'], 2)}" for k in tk) + ".\n")
    fixed_sizes = f"{min(sizes)}-{max(sizes)}"
    w(f"**Q3. Is a fixed threshold or Top-K more appropriate for an investigation workflow?** On this evaluation set, a Top-K (capacity-bounded, ranked) queue is the more predictable workflow: "
      f"fixed cutoffs gave queue sizes of {fixed_sizes} across the six scoring variants and moved by up to {big[2]} projects for a five-point change, while Top-K stays at its capacity. "
      f"A fixed floor is easier to explain and avoids forced reviews. Because V1's production queue is already ranked by score with a floor of 30, the practical difference is whether the investigator "
      f"stops at the floor ({nat['projects_queued']} projects) or at a chosen capacity; this study does not show that either rule should replace the other.\n")
    a30, a40 = T[30.0], T[40.0]
    free = [t for t in thr if t["adversarial_queued"] == 0]
    top_adv = adv["highest_ranked_eight"][0]
    reached = [f">= {t['threshold']:g}" for t in thr if adv["max_score"] >= t["threshold"] and t["adversarial_queued"] > 0]
    w(f"**Q4. How vulnerable are the queues to adversarial normals?** At >= 30, {a30['adversarial_queued']} of the {adv['n']} adversarial normals are queued ({_p(a30['adversarial_queued_pct'])}) and they are "
      f"{_p(a30['adversarial_queued'] / a30['fp'] if a30['fp'] else None)} of the false positives; at >= 40, {a40['adversarial_queued']} ({_p(a40['adversarial_queued_pct'])}). "
      f"At >= 25 the count rises to {T[25.0]['adversarial_queued']} and at >= 20 to {T[20.0]['adversarial_queued']}. The highest-scored adversarial normal ({top_adv['project_id']}, ADV-{top_adv['subtype']}) scores "
      f"{_f(adv['max_score'], 1)} and ranks {top_adv['rank']} of {ds['projects']}, so it is queued at {_and(reached)}; " +
      (f"the first predefined cutoff that excludes every adversarial normal is >= {free[0]['threshold']:g}, at a recall of {_f(free[0]['recall'])}" if free else "no predefined cutoff excludes every adversarial normal") +
      f". In Top-K terms, the Top-10 contains {K[10]['adversarial_queued']} adversarial normal{'' if K[10]['adversarial_queued'] == 1 else 's'} and the Top-20 contains {K[20]['adversarial_queued']}.\n")
    w("**Q5. Which operating points give useful trade-offs without claiming to be production-calibrated?** The following are evaluation operating points chosen for workload reasons from the predefined lists, not because they maximise any metric:\n")
    w("| Candidate | Kind | Queue | % of dataset | Anomalous captured | Precision | Recall | Adversarial queued | Why (operational) |\n|---|---|--:|--:|--:|--:|--:|--:|---|")
    for c in r["candidate_operating_points"]:
        w(f"| {c['name']} | {c['kind']} | {c['queue_size']} | {_p(c['pct_of_dataset'])} | {c['anomalous_captured']} | {_f(c['precision'])} | {_f(c['recall'])} | {c['adversarial_queued']} | {c['why']} |")
    w("")
    c25 = T[25.0]
    w(f"**Q6. Does V2.5 justify changing the V1 production queue?** **No.** (1) V1's production queue is already a ranked list with a score floor, so an investigator can already work top-down and stop at any "
      f"capacity; nothing here shows that rule is wrong. (2) The evidence is one synthetic, author-designed set of 150 projects, with scores that are not calibrated to any real outcome. "
      f"(3) The descriptive observation that the 25-29.9 band is dense with anomalies (a cutoff of 25 would queue {c25['projects_queued']} projects instead of {nat['projects_queued']}, "
      f"capturing {c25['tp']} instead of {nat['tp']} anomalous at the cost of {c25['fp']} instead of {nat['fp']} false positives) describes a trade-off on these labels; adopting it would be exactly the "
      "label-driven threshold tuning this stage excludes. (4) A score is a deterministic anomaly score, not a probability. Any change to the production queue should wait for calibration against real review outcomes.\n")
    w("## 11. Limitations\n")
    for x in [
        "The dataset is synthetic (150 projects, 49 anomalous) and its scenarios were designed around the same red-flag patterns as V1's detectors; these results measure agreement with that design, not real-world fraud detection.",
        "The thresholds and capacities are predefined evaluation operating points, not production-calibrated thresholds, and Top-K sizes do not represent actual investigator staffing.",
        "With 150 projects, differences of one or two projects between operating points are within noise; no confidence intervals are computed here.",
        "Tied scores are ordered by project_id ascending for determinism; V1's production route does not break ties that way, so its exact Top-K membership at a tie may differ.",
        "The score-scale sensitivity table reuses the frozen V2.4 ablation scores purely as an illustration of how fixed cutoffs depend on the score scale; the variants are not alternative production systems.",
        "Precision and recall here depend on the V2.1 prevalence (32.7% anomalous), which is far higher than any realistic fraud rate; absolute precision values should not be transferred to production.",
    ]:
        w(f"- {x}")
    w("\n## 12. Conclusion\n")
    first_adv = adv["highest_ranked_eight"][0]
    w(f"On this frozen synthetic evaluation set, raising the score threshold shrinks the queue from {T[20.0]['projects_queued']} to {T[50.0]['projects_queued']} projects while recall falls from "
      f"{_f(T[20.0]['recall'])} to {_f(T[50.0]['recall'])}. The head of the ranking is dense with anomalies ({K[10]['anomalous_captured']} of the Top-10), but recall at V1's production cutoff is limited "
      f"({_f(T[30.0]['recall'])}), and the first adversarial normal appears at rank {first_adv['rank']}" +
      (", accounting for every false positive at >= 30" if a30["adversarial_queued"] == a30["fp"] else "") +
      ". V2.5 does not justify changing V1's production queue; it supplies a transparent description of the operating-point trade-offs, to be revisited when real review outcomes are available.\n")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="V2.5 operating-point analysis")
    ap.add_argument("--dir", default="evaluation")
    a = ap.parse_args()
    try:
        preds = write_predictions(a.dir)
        rep = analyze(a.dir)
    except (M.EvaluationInputError, FileNotFoundError, ValueError) as e:
        print(f"V2.5 FAILED: {e}", file=sys.stderr)
        return 2
    print(f"Wrote {OUT_SUBDIR}/calibration_predictions.csv ({len(preds)} projects), calibration_results.json, calibration_report.md and {len(os.listdir(os.path.join(a.dir, OUT_SUBDIR, PLOTS_SUBDIR)))} plots")
    for t in rep["threshold_table"]:
        print(f">= {t['threshold']:g}: queued {t['projects_queued']:3d}  TP {t['tp']:2d}  FP {t['fp']:2d}  precision {_f(t['precision'])}  recall {_f(t['recall'])}  adversarial {t['adversarial_queued']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
