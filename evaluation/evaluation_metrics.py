"""
NidhiGuard V2.2 - evaluation metrics layer.

Compares the UNMODIFIED V1 engine's predictions (evaluation_predictions.csv) with the
independent V2.1 ground truth (evaluation_labels.csv). Evaluation only:

* does not import or call the V1 engine (nothing from intelligence/),
* never writes to the labels, predictions or engine input,
* never tunes a threshold or weight: both thresholds below are fixed constants.

Label vocabulary (taken from the actual V2.1 labels file):
    ground_truth_label : ANOMALOUS | NORMAL
    scenario_type      : NORMAL, ADVERSARIAL_NORMAL (both binary NORMAL) and
                         COST_ANOMALY, BILLING_ANOMALY, CONTRACTOR_PATTERN, SIMILAR_PROJECT,
                         GEOGRAPHIC_PATTERN, MULTI_SIGNAL (all binary ANOMALOUS)
scenario_type is used only AFTER prediction, for grouped reporting and a consistency check.

Usage (repo root):
    python -m evaluation.evaluation_metrics --dir evaluation
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import auc, average_precision_score, precision_recall_curve

POSITIVE_LABEL = "ANOMALOUS"
NEGATIVE_LABEL = "NORMAL"
NORMAL_SCENARIOS = ("NORMAL", "ADVERSARIAL_NORMAL")
ANOMALOUS_SCENARIOS = ("COST_ANOMALY", "BILLING_ANOMALY", "CONTRACTOR_PATTERN",
                       "SIMILAR_PROJECT", "GEOGRAPHIC_PATTERN", "MULTI_SIGNAL")
SCENARIO_ORDER = ("NORMAL", "ADVERSARIAL_NORMAL") + ANOMALOUS_SCENARIOS

PRIMARY_THRESHOLD = 40.0     # as specified for V2.2; do not change
V1_QUEUE_THRESHOLD = 30.0    # V1's own non-LOW investigation-queue cutoff (risk_engine.py: level != LOW)
TOP_K = (5, 10, 20)
BOOTSTRAP_SEED = 20261019
BOOTSTRAP_RESAMPLES = 2000

PRED_REQUIRED = ("project_id", "risk_score", "risk_level")
LABEL_REQUIRED = ("project_id", "ground_truth_label", "scenario_type")
COMPONENT_COLUMNS = ("cost_anomaly_score", "project_similarity_score", "contractor_pattern_score",
                     "billing_anomaly_score", "geographic_signal_score")


class EvaluationInputError(ValueError):
    """Raised for any input problem; evaluation must fail loudly, never guess."""


# --------------------------------------------------------------------------- #
# loading and validation
# --------------------------------------------------------------------------- #
def load_csvs(pred_path: str, labels_path: str):
    pred = pd.read_csv(pred_path, dtype={"project_id": str})
    labels = pd.read_csv(labels_path, dtype=str, keep_default_na=False)
    return pred, labels


def _check_ids(df: pd.DataFrame, name: str) -> pd.Series:
    ids = df["project_id"]
    if ids.isna().any() or (ids.astype(str).str.strip() == "").any():
        raise EvaluationInputError(f"{name}: empty or missing project_id values")
    ids = ids.astype(str).str.strip()
    dup = sorted(ids[ids.duplicated()].unique())
    if dup:
        raise EvaluationInputError(f"{name}: duplicate project_id values: {dup[:10]}")
    return ids


def prepare(pred: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Validate and join predictions to labels. Returns one row per project with y_true (1 = ANOMALOUS)."""
    for name, df, req in (("predictions", pred, PRED_REQUIRED), ("labels", labels, LABEL_REQUIRED)):
        missing = [c for c in req if c not in df.columns]
        if missing:
            raise EvaluationInputError(f"{name}: missing required column(s) {missing}")
    pred, labels = pred.copy(), labels.copy()
    pred["project_id"] = _check_ids(pred, "predictions")
    labels["project_id"] = _check_ids(labels, "labels")

    # missing / non-numeric / non-finite predictions
    scores = pd.to_numeric(pred["risk_score"], errors="coerce")
    bad = pred.loc[scores.isna() | ~np.isfinite(scores.fillna(np.nan)), "project_id"].tolist()
    if bad:
        raise EvaluationInputError(f"predictions: missing or non-numeric risk_score for {bad[:10]}")
    pred["risk_score"] = scores.astype(float)

    # ids must match exactly in both directions
    only_labels = sorted(set(labels.project_id) - set(pred.project_id))
    only_pred = sorted(set(pred.project_id) - set(labels.project_id))
    if only_labels:
        raise EvaluationInputError(f"missing predictions for {len(only_labels)} labelled project(s): {only_labels[:10]}")
    if only_pred:
        raise EvaluationInputError(f"{len(only_pred)} predicted project(s) have no label: {only_pred[:10]}")

    # label vocabulary and scenario consistency (ADVERSARIAL_NORMAL is binary NORMAL)
    badlab = sorted(set(labels.ground_truth_label) - {POSITIVE_LABEL, NEGATIVE_LABEL})
    if badlab:
        raise EvaluationInputError(f"invalid ground_truth_label value(s): {badlab} (expected {POSITIVE_LABEL}|{NEGATIVE_LABEL})")
    badsc = sorted(set(labels.scenario_type) - set(SCENARIO_ORDER))
    if badsc:
        raise EvaluationInputError(f"unknown scenario_type value(s): {badsc}")
    inconsistent = labels[(labels.scenario_type.isin(NORMAL_SCENARIOS)) != (labels.ground_truth_label == NEGATIVE_LABEL)]
    if len(inconsistent):
        raise EvaluationInputError("scenario_type disagrees with ground_truth_label for: "
                                   f"{inconsistent.project_id.tolist()[:10]}")

    keep = [c for c in pred.columns if c in ("project_id", "risk_score", "risk_level", "recommendation") + COMPONENT_COLUMNS]
    df = labels.merge(pred[keep], on="project_id", how="inner", validate="one_to_one")
    df["y_true"] = (df.ground_truth_label == POSITIVE_LABEL).astype(int)
    if df.y_true.sum() == 0:
        raise EvaluationInputError("no ANOMALOUS projects in the labels: recall and PR-AUC are undefined")
    if (df.y_true == 0).all() or df.y_true.sum() == len(df):
        raise EvaluationInputError("labels contain a single class: ranking metrics are not meaningful")
    return df


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def rank(df: pd.DataFrame) -> pd.DataFrame:
    """risk_score descending; ties broken by project_id ascending (deterministic)."""
    return df.sort_values(["risk_score", "project_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def precision_at_k(ranked: pd.DataFrame, k: int) -> dict:
    if not isinstance(k, (int, np.integer)) or k < 1 or k > len(ranked):
        raise EvaluationInputError(f"k must be an integer in [1, {len(ranked)}], got {k!r}")
    tp = int(ranked.y_true.iloc[:k].sum())
    total_pos = int(ranked.y_true.sum())
    return {"k": int(k), "anomalous_in_top_k": tp, "precision": tp / k, "recall_at_k": tp / total_pos}


def thresholded(df: pd.DataFrame, threshold: float) -> dict:
    pred_pos = df.risk_score >= threshold
    y = df.y_true == 1
    tp, fp = int((pred_pos & y).sum()), int((pred_pos & ~y).sum())
    tn, fn = int((~pred_pos & ~y).sum()), int((~pred_pos & y).sum())

    def div(a, b):
        return a / b if b else None

    precision, recall = div(tp, tp + fp), div(tp, tp + fn)
    f1 = div(2 * precision * recall, precision + recall) if precision is not None and recall is not None and (precision + recall) else None
    return {"threshold": threshold, "rule": f"risk_score >= {threshold:g} -> predicted anomaly",
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision, "recall": recall, "f1": f1,
            "false_positive_rate": div(fp, fp + tn), "predicted_positive": tp + fp,
            "note": "null = undefined (zero denominator)"}


def pr_auc(df: pd.DataFrame) -> dict:
    """PR-AUC from the continuous risk_score (never risk_level). Primary = average precision."""
    y, s = df.y_true.to_numpy(), df.risk_score.to_numpy()
    if y.sum() == 0:
        raise EvaluationInputError("PR-AUC undefined: no positive class")
    ap = float(average_precision_score(y, s))
    p, r, _ = precision_recall_curve(y, s)
    return {"average_precision": ap, "trapezoid_auc": float(auc(r, p)),
            "random_baseline": float(y.mean()),
            "note": "average_precision (step-wise, no linear interpolation) is the headline PR-AUC; "
                    "trapezoid_auc is shown for transparency. Tied scores are treated as one threshold."}


def _stats(s: pd.Series) -> dict:
    if len(s) == 0:
        return {"mean": None, "median": None, "max": None}
    return {"mean": float(s.mean()), "median": float(s.median()), "max": float(s.max())}


def _group_row(g: pd.DataFrame, threshold: float, q_threshold: float) -> dict:
    n_ge = int((g.risk_score >= threshold).sum())
    n_q = int((g.risk_score >= q_threshold).sum())
    return {"n": int(len(g)), "n_anomalous": int(g.y_true.sum()), "n_normal": int((g.y_true == 0).sum()),
            **_stats(g.risk_score),
            "n_at_or_above_primary": n_ge, "rate_at_or_above_primary": (n_ge / len(g)) if len(g) else None,
            "n_at_or_above_v1_queue": n_q, "rate_at_or_above_v1_queue": (n_q / len(g)) if len(g) else None}


def scenario_table(df: pd.DataFrame, threshold: float = PRIMARY_THRESHOLD, q_threshold: float = V1_QUEUE_THRESHOLD) -> dict:
    out = {}
    for sc in list(SCENARIO_ORDER) + sorted(set(df.scenario_type) - set(SCENARIO_ORDER)):
        g = df[df.scenario_type == sc]
        row = _group_row(g, threshold, q_threshold)
        row["rate_meaning"] = ("false_positive_rate" if sc in NORMAL_SCENARIOS else "detection_rate")
        if "difficulty" in g.columns and sc in ANOMALOUS_SCENARIOS:
            row["by_difficulty"] = {d: _group_row(g[g.difficulty == d], threshold, q_threshold)
                                    for d in ("OBVIOUS", "BORDERLINE") if (g.difficulty == d).any()}
        comps = [c for c in COMPONENT_COLUMNS if c in g.columns]
        if comps and len(g):
            row["mean_component_scores"] = {c: float(g[c].mean()) for c in comps}
        out[sc] = row
    return out


def adversarial_analysis(df: pd.DataFrame, threshold: float = PRIMARY_THRESHOLD, q_threshold: float = V1_QUEUE_THRESHOLD) -> dict:
    g = df[df.scenario_type == "ADVERSARIAL_NORMAL"]
    row = _group_row(g, threshold, q_threshold)
    row["treated_as"] = NEGATIVE_LABEL
    row["false_positive_rate_primary"] = row["rate_at_or_above_primary"]
    row["false_positive_rate_v1_queue"] = row["rate_at_or_above_v1_queue"]
    if "adversarial_subtype" in g.columns and len(g):
        row["by_subtype"] = {st: _group_row(g[g.adversarial_subtype == st], threshold, q_threshold)
                             for st in sorted(set(g.adversarial_subtype) - {""})}
    return row


def bootstrap_intervals(df: pd.DataFrame, threshold: float = PRIMARY_THRESHOLD, n: int = BOOTSTRAP_RESAMPLES,
                        seed: int = BOOTSTRAP_SEED) -> dict:
    """Seeded percentile bootstrap (row-level). Supplementary; likely too narrow because
    cases come in linked groups (pairs/clusters/portfolios), which row resampling ignores."""
    rng = np.random.default_rng(seed)
    y, s = df.y_true.to_numpy(), df.risk_score.to_numpy()
    aps, recs, precs = [], [], []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        yb, sb = y[idx], s[idx]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        aps.append(average_precision_score(yb, sb))
        pp = sb >= threshold
        recs.append((pp & (yb == 1)).sum() / yb.sum())
        if pp.sum():
            precs.append((pp & (yb == 1)).sum() / pp.sum())

    def ci(v):
        return None if not v else [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]

    return {"method": "percentile bootstrap, row-level resampling", "resamples": n, "seed": seed,
            "average_precision_95ci": ci(aps), f"recall_at_{threshold:g}_95ci": ci(recs),
            f"precision_at_{threshold:g}_95ci": ci(precs),
            "caveat": "n=150 with linked groups; treat intervals as optimistic (too narrow)."}


def top_n(ranked: pd.DataFrame, n: int = 20) -> list:
    cols = ["project_id", "risk_score", "risk_level", "ground_truth_label", "scenario_type"]
    out = ranked.head(n)[cols].copy()
    out.insert(0, "rank", range(1, len(out) + 1))
    return out.to_dict(orient="records")


# --------------------------------------------------------------------------- #
# provenance (is this really the frozen dataset + its predictions?)
# --------------------------------------------------------------------------- #
def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def verify_provenance(eval_dir: str) -> dict:
    meta_path = os.path.join(eval_dir, "evaluation_metadata.json")
    pm_path = os.path.join(eval_dir, "evaluation_predictions_meta.json")
    labels_path = os.path.join(eval_dir, "evaluation_labels.csv")
    pred_path = os.path.join(eval_dir, "evaluation_predictions.csv")
    with open(meta_path, encoding="utf-8") as fh:
        frozen = json.load(fh)["file_sha256"]
    with open(pm_path, encoding="utf-8") as fh:
        pm = json.load(fh)
    labels_sha = _sha(labels_path)
    input_ok = all(pm["engine_input_sha256"].get(k) == frozen.get(k) for k in frozen if k.startswith("engine_input/"))
    return {"labels_sha256": labels_sha,
            "labels_match_frozen_hash": labels_sha == frozen["evaluation_labels.csv"],
            "predictions_sha256": _sha(pred_path),
            "predictions_made_from_frozen_engine_input": bool(input_ok),
            "predictions_projects_scored": pm.get("projects_scored"),
            "frozen_hash_check_at_prediction_time": pm.get("frozen_hash_check")}


# --------------------------------------------------------------------------- #
# report assembly
# --------------------------------------------------------------------------- #
def build_report(pred: pd.DataFrame, labels: pd.DataFrame, provenance: dict | None = None) -> dict:
    df = prepare(pred, labels)
    ranked = rank(df)
    n_pos = int(df.y_true.sum())
    ks = {f"precision_at_{k}": precision_at_k(ranked, k) for k in TOP_K}
    return {
        "dataset_summary": {
            "projects": int(len(df)), "anomalous": n_pos, "normal": int(len(df) - n_pos),
            "prevalence": n_pos / len(df),
            "scenario_counts": {k: int(v) for k, v in df.scenario_type.value_counts().reindex(list(SCENARIO_ORDER)).fillna(0).items()},
            "predicted_risk_levels": {k: int(v) for k, v in df.risk_level.value_counts().items()},
            "risk_score": {"min": float(df.risk_score.min()), **_stats(df.risk_score)},
            "label_vocabulary": {"positive": POSITIVE_LABEL, "negative": NEGATIVE_LABEL,
                                 "binary_normal_scenarios": list(NORMAL_SCENARIOS)},
            "provenance": provenance,
        },
        "ranking": {"order": "risk_score descending, project_id ascending for ties",
                    "random_baseline_precision": n_pos / len(df), **ks,
                    "precision_at_n_positives": precision_at_k(ranked, n_pos)},
        "pr_auc": pr_auc(df),
        "thresholded_classification": {
            "primary": {"label": f"Thresholded classification at risk_score >= {PRIMARY_THRESHOLD:g}",
                        **thresholded(df, PRIMARY_THRESHOLD)},
            "v1_queue_reference": {"label": f"Reference: V1 investigation-queue cutoff (non-LOW) at risk_score >= {V1_QUEUE_THRESHOLD:g}",
                                   **thresholded(df, V1_QUEUE_THRESHOLD)},
            "threshold_note": "The primary threshold (40) is the one specified for V2.2. V1 code defines levels at 30/60/80 "
                              "and builds its queue from every non-LOW project (>= 30); 40 does not appear in V1. "
                              "Both are fixed in advance; neither was chosen from these results.",
        },
        "recall_definitions": {
            "thresholded_recall": "TP / all actual anomalous at the stated threshold (see thresholded_classification)",
            "recall_at_k": "anomalous in top K / all actual anomalous (see ranking.precision_at_*.recall_at_k)",
        },
        "bootstrap": bootstrap_intervals(df),
        "scenario_level": scenario_table(df),
        "adversarial_normal": adversarial_analysis(df),
        "top_20": top_n(ranked, 20),
    }


def _round(o, nd=6):
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) and math.isnan(o)) else round(float(o), nd)
    if isinstance(o, np.integer):
        return int(o)
    return o


# --------------------------------------------------------------------------- #
# markdown
# --------------------------------------------------------------------------- #
def _f(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def render_markdown(r: dict) -> str:
    ds, rk, pa = r["dataset_summary"], r["ranking"], r["pr_auc"]
    tc, bs = r["thresholded_classification"], r["bootstrap"]
    L = []
    L.append("# NidhiGuard V2.2 - V1 Engine Evaluation Report\n")
    L.append("_Controlled synthetic evaluation. Not real MPLADS ground truth. Predictions are from the unmodified V1 engine; "
             "nothing was tuned._\n")
    L.append("## 1. Dataset summary\n")
    L.append(f"- Projects: **{ds['projects']}** ({ds['anomalous']} anomalous, {ds['normal']} normal; prevalence {_f(ds['prevalence'])})")
    L.append("- Scenario counts: " + ", ".join(f"{k} {v}" for k, v in ds["scenario_counts"].items()))
    L.append("- Predicted risk levels: " + ", ".join(f"{k} {v}" for k, v in ds["predicted_risk_levels"].items()))
    s = ds["risk_score"]
    L.append(f"- Risk score: min {_f(s['min'], 1)}, median {_f(s['median'], 2)}, mean {_f(s['mean'], 2)}, max {_f(s['max'], 1)}")
    pv = ds.get("provenance")
    if pv:
        L.append(f"- Labels match frozen hash: **{pv['labels_match_frozen_hash']}**; predictions made from frozen engine input: "
                 f"**{pv['predictions_made_from_frozen_engine_input']}**")
    L.append("\n## 2. Overall metrics\n")
    p, q = tc["primary"], tc["v1_queue_reference"]
    L.append("| Metric | Value |\n|---|--:|")
    L.append(f"| PR-AUC (average precision) | **{_f(pa['average_precision'])}** (random baseline {_f(pa['random_baseline'])}) |")
    L.append(f"| PR-AUC (trapezoid, for transparency) | {_f(pa['trapezoid_auc'])} |")
    L.append(f"| Precision@5 / @10 / @20 | {_f(rk['precision_at_5']['precision'], 2)} / {_f(rk['precision_at_10']['precision'], 2)} / {_f(rk['precision_at_20']['precision'], 2)} |")
    L.append(f"| Recall@20 (top-20 captures) | {rk['precision_at_20']['anomalous_in_top_k']} of {ds['anomalous']} = {_f(rk['precision_at_20']['recall_at_k'])} |")
    L.append(f"| Precision@{ds['anomalous']} (R-precision) | {_f(rk['precision_at_n_positives']['precision'])} |")
    L.append(f"| Recall at risk_score >= 40 | {_f(p['recall'])} |")
    L.append(f"| Bootstrap 95% CI, average precision | {bs['average_precision_95ci'] and [round(v, 3) for v in bs['average_precision_95ci']]} (optimistic) |")
    L.append("\n## 3. Precision@K (ranked by risk_score desc, project_id asc for ties)\n")
    L.append("| K | Anomalous in top K | Precision@K | Recall@K |\n|--:|--:|--:|--:|")
    for k in (5, 10, 20):
        e = rk[f"precision_at_{k}"]
        L.append(f"| {k} | {e['anomalous_in_top_k']} | {_f(e['precision'], 2)} | {_f(e['recall_at_k'])} |")
    L.append(f"\nRandom-ranking baseline precision = prevalence = {_f(rk['random_baseline_precision'])}.\n")
    L.append("## 4. Thresholded confusion matrix\n")
    for blk in (p, q):
        L.append(f"**{blk['label']}**\n")
        L.append("| | Predicted anomaly | Predicted normal |\n|---|--:|--:|")
        L.append(f"| Actual anomalous | TP {blk['tp']} | FN {blk['fn']} |")
        L.append(f"| Actual normal | FP {blk['fp']} | TN {blk['tn']} |")
        L.append(f"\nPrecision {_f(blk['precision'])}, recall {_f(blk['recall'])}, F1 {_f(blk['f1'])}, false-positive rate {_f(blk['false_positive_rate'])}\n")
    L.append(f"_{tc['threshold_note']}_\n")
    L.append("## 5. PR-AUC\n")
    L.append(f"Average precision **{_f(pa['average_precision'])}** vs random baseline {_f(pa['random_baseline'])}; "
             f"trapezoid {_f(pa['trapezoid_auc'])}. Computed from the continuous risk_score, not risk_level.\n")
    L.append("## 6. Scenario-level results\n")
    L.append("| Scenario | n | Anom/Norm | Mean | Median | Max | >=40 | Rate >=40 | >=30 | Rate >=30 | Rate means |\n|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for sc, e in r["scenario_level"].items():
        L.append(f"| {sc} | {e['n']} | {e['n_anomalous']}/{e['n_normal']} | {_f(e['mean'], 1)} | {_f(e['median'], 1)} | {_f(e['max'], 1)} | "
                 f"{e['n_at_or_above_primary']} | {_f(e['rate_at_or_above_primary'], 2)} | {e['n_at_or_above_v1_queue']} | "
                 f"{_f(e['rate_at_or_above_v1_queue'], 2)} | {e['rate_meaning']} |")
    L.append("\nBy difficulty (anomalous scenarios):\n")
    L.append("| Scenario | Difficulty | n | Mean | Max | >=40 | >=30 |\n|---|---|--:|--:|--:|--:|--:|")
    for sc, e in r["scenario_level"].items():
        for d, de in e.get("by_difficulty", {}).items():
            L.append(f"| {sc} | {d} | {de['n']} | {_f(de['mean'], 1)} | {_f(de['max'], 1)} | {de['n_at_or_above_primary']} | {de['n_at_or_above_v1_queue']} |")
    a = r["adversarial_normal"]
    L.append("\n## 7. Adversarial-normal results (treated as NORMAL)\n")
    L.append(f"- Count {a['n']}; mean {_f(a['mean'], 1)}, median {_f(a['median'], 1)}, max {_f(a['max'], 1)}")
    L.append(f"- >= 40: {a['n_at_or_above_primary']} (false-positive rate {_f(a['false_positive_rate_primary'], 3)}); "
             f">= 30: {a['n_at_or_above_v1_queue']} (false-positive rate {_f(a['false_positive_rate_v1_queue'], 3)})")
    if a.get("by_subtype"):
        L.append("\n| Subtype | n | Mean | Max | >=40 | >=30 |\n|---|--:|--:|--:|--:|--:|")
        for st, e in a["by_subtype"].items():
            L.append(f"| {st} | {e['n']} | {_f(e['mean'], 1)} | {_f(e['max'], 1)} | {e['n_at_or_above_primary']} | {e['n_at_or_above_v1_queue']} |")
    L.append("\n## 8. Top 20 highest-risk projects\n")
    L.append("| Rank | project_id | risk_score | risk_level | ground_truth_label | scenario_type |\n|--:|---|--:|---|---|---|")
    for t in r["top_20"]:
        L.append(f"| {t['rank']} | {t['project_id']} | {_f(t['risk_score'], 1)} | {t['risk_level']} | {t['ground_truth_label']} | {t['scenario_type']} |")
    L.append("\n## 9. Limitations and interpretation notes\n")
    for note in [
        "Controlled synthetic dataset built by the same author as the V1 detectors; it measures agreement with that author's definition of suspicious, not real-world fraud detection.",
        "Scenario families mirror the detector families (README-informed). CONTRACTOR_PATTERN was written after the author saw one V1 planted-signal sentence; read that row with extra caution.",
        "150 cases (49 anomalous). Bootstrap intervals use row resampling and ignore linked groups, so they are optimistic. Small differences between scenarios are not significant.",
        "The V1 score never reached HIGH (60) or CRITICAL (80) on this data, so risk_level carries little information here; the continuous score is used for ranking and PR-AUC.",
        "Primary threshold 40 was specified for V2.2; V1's own queue cutoff is non-LOW (>= 30). Both are reported; neither was selected from these results.",
        "ADV-C and ADV-D rely on fields (estimated cost, bill structure) the engine may not use; false positives there are findings about V1, not dataset defects.",
        "PR-AUC ties: tied scores form a single threshold, while Precision@K breaks ties by project_id ascending; the two can differ slightly where scores tie.",
        "No threshold, weight or detector was changed in response to these results.",
    ]:
        L.append(f"- {note}")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def run(eval_dir: str, allow_changed: bool = False) -> dict:
    prov = verify_provenance(eval_dir)
    if not (prov["labels_match_frozen_hash"] and prov["predictions_made_from_frozen_engine_input"]) and not allow_changed:
        raise EvaluationInputError(f"provenance check failed (labels or prediction inputs differ from the frozen hashes): {prov}")
    pred, labels = load_csvs(os.path.join(eval_dir, "evaluation_predictions.csv"),
                             os.path.join(eval_dir, "evaluation_labels.csv"))
    report = _round(build_report(pred, labels, prov))
    with open(os.path.join(eval_dir, "evaluation_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(eval_dir, "evaluation_report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dir", default="evaluation")
    ap.add_argument("--allow-changed", action="store_true", help="skip the frozen-hash provenance failure (must be logged in CHANGELOG.md)")
    a = ap.parse_args()
    try:
        r = run(a.dir, a.allow_changed)
    except (EvaluationInputError, FileNotFoundError) as e:
        print(f"EVALUATION FAILED: {e}", file=sys.stderr)
        return 2
    print(f"Wrote {os.path.join(a.dir, 'evaluation_report.json')} and evaluation_report.md "
          f"(PR-AUC AP={r['pr_auc']['average_precision']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
