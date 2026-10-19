# NidhiGuard V2.1 - Independent Evaluation Dataset

**This dataset is intentionally separated from the V1 planted-signal dataset and is used only for evaluation.**
**The labels are generated from independently defined evaluation scenarios and are not derived from NidhiGuard risk scores.**

It is a *controlled synthetic evaluation dataset*. It is not real MPLADS ground truth, and results on it do not
show real-world fraud detection performance. Read `SCENARIO_SPEC.md` (construction rules and the honest limits of
independence) and `evaluation_metadata.json` (counts, hashes, limitations) first.

## Layout

| Path | Purpose |
|---|---|
| `engine_input/` | The only files the V1 engine may see (same schema as `data-source/data`; `anomaly_signals.csv` is header-only) |
| `evaluation_labels.csv` | Ground truth. Used only after predictions exist. Never passed to any detector |
| `evaluation_metadata.json` | Counts, scenario construction, leakage controls, limitations, SHA-256 hashes |
| `evaluation_predictions.csv` | Unmodified V1 engine outputs (written by the runner; no labels inside) |
| `SCENARIO_SPEC.md`, `spec_constants.py` | Rules and thresholds behind every label |
| `generate_evaluation_data.py`, `run_v1_predictions.py`, `tests/` | Reproduction and validation |
| `CHANGELOG.md` | Any change made after the hashes were frozen |

## Reproduce (from the repository root)

    python -m evaluation.generate_evaluation_data --out evaluation
    pytest evaluation/tests -q
    python -m evaluation.run_v1_predictions --dir evaluation     # predictions only, no metrics

Generation is deterministic (seed 7919); the test suite regenerates twice and compares hashes.
No metrics (Precision@K, recall, PR-AUC) are computed in V2.1.
