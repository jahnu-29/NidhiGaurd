# NidhiGuard V2.1 - Scenario Specification

Status: **DRAFT for author review. Not frozen.** Nothing in this folder has been run through the V1 engine.

This document defines how every evaluation case is built and what makes it `ANOMALOUS` or `NORMAL`.
The numbers below live in `spec_constants.py`; the tests in `tests/test_evaluation_dataset.py` re-derive every
rule from the raw CSVs, so a label cannot silently disagree with its data.

## 0. Provenance and honest limits of independence

* Not read: any detector source file, `ANOMALY_SCENARIOS.md`, V1 risk outputs. Not used: any V1 CSV.
* Read: CSV schemas, `DATA_SCHEMA.md`, `RELATIONSHIPS.md`, the loader and entry-point scripts, and the V1 README,
  which describes each detector in plain language. The scenario families therefore mirror the detector families
  (cost vs. a comparable-group median, contractor concentration, bill timing, proximity plus shared attributes,
  description similarity). That is a design choice, but it means this dataset tests *the author's definition of
  suspicious*, not an external truth.
* Exposure incident: a `head` command printed the first two rows of V1 `anomaly_signals.csv` (one contractor-pattern
  sentence, one cost sentence). They were not used, but CONT-1 resembles that sentence. Treat CONTRACTOR_PATTERN
  results with extra caution in V2.2.
* Everything is synthetic. A label says how a case was *constructed*, not what a detector reports.

## 1. Global conventions

* Pool: 150 projects, 100 contractors, 1,200 historical projects (an independent baseline drawn from the same cost model), snapshot date 2025-12-31.
* **Group median** = generative median of (work type, state) = `BASE_MEDIAN[work_type] x STATE_FACTOR[state]`.
  Labels use this generative median, not an empirical one. `ratio` = sanctioned amount / group median.
* **Corroborated estimate**: estimated cost within 6% of the sanctioned amount (sanction/estimate <= 1.06).
  **Unsupported estimate**: estimated cost near the group median while the sanction is far above it.
* Project IDs are assigned after a random shuffle. The label file and engine input carry no ordering signal.
* The engine sees only `engine_input/`. `anomaly_signals.csv` there is header-only (0 rows).

## 2. Anomaly rules

| ID | Rule | Obvious | Borderline |
|---|---|---|---|
| COST-1 | ratio >= 1.7 AND sanction/estimate >= 1.6 AND no scope text explains it | ratio 3.0-4.0 | ratio 1.8-2.2 |
| BILL-1 compression | k bills dated within a short burst mid-project; no end-loading | 4 bills in <= 5 days | 3 bills in <= 10 days |
| BILL-2 end-loading | >= 60% of claimed amount billed after the last 15% of start-to-completion; earlier bills few and small; no compression | final bill 72-85% | final bill 60-66% |
| CONT-1 | one contractor, >= 4 same-work-type projects, work orders within 45 days, each ratio >= 1.15 (and < 1.7), districts >= 10 km apart; the contractor's other projects are cheaper and >= 150 days away | 5 projects, 16-day window, 1.30-1.55x | 4 projects, 38-day window, 1.15-1.30x |
| SIM-1 | pair: same work type, district and village; sanction gap <= 60 days; <= 2 km apart; amounts within 10% | near-identical wording, 5-20 days, 0.1-0.5 km, +-3%, same contractor | paraphrased wording, 40-60 days, 1.0-1.8 km, +-8%, different contractors |
| GEO-1 | >= 3 projects within 2 km of their centroid, same contractor and work type, amounts within +-15% of cluster mean, sanctioned >= 60 days apart, different villages and templates | 5 projects <= 0.8 km, +-7% | 3 projects <= 1.8 km, +-12% |
| MULTI-1 | at least two of the above on one case, each at its own rule level | cost+billing (3), duplicate pair + cost (2) | cost+billing (3) |

## 3. Normal rules

* **NORM-1 (plain normal)**: ratio within +-1.2 sigma of the median (<= 1.43x), corroborated estimate, bills >= 21 days apart with a final bill of 12-25%, at least 6 km from every other project, contractor has <= 3 plain projects >= 120 days apart.
* **ADV-A large legitimate portfolio**: contractor with 7 projects over ~22 months, >= 95 days between awards, >= 4 work types, districts >= 10 km apart, ratio 0.79-1.27.
* **ADV-B nearby legitimate projects**: 3 projects within 1.6 km of each other, 3 work types, 3 contractors, >= 60 days apart, ratio 0.84-1.16.
* **ADV-C high-cost but justified**: ratio 1.8-2.4, estimate corroborates (<= 1.06), description documents extra scope.
* **ADV-D milestone billing**: advance + two evenly spaced running bills (>= 25 days apart) + final bill of 38-48%.
* **ADV-E similar wording only**: same template and district, different villages, >= 8 km apart, >= 150 days apart, amounts differ >= 20%, different contractors.

Deliberate overlaps (so V2.2 can measure real discrimination): COST-1 borderline (1.8-2.2x) overlaps ADV-C (1.8-2.4x) in ratio and differs only in estimate support and scope text; BILL-2 borderline (60-66%) sits 12+ points above ADV-D (38-48%); SIM-1 borderline and ADV-E share description templates.

## 4. Composition (150 cases)

| Scenario | Cases | Obvious / borderline |
|---|--:|---|
| NORMAL | 60 | - |
| ADVERSARIAL_NORMAL | 41 | A 14, B 9, C 5, D 5, E 8 |
| COST_ANOMALY | 8 | 4 / 4 |
| BILLING_ANOMALY | 8 | 4 / 4 |
| CONTRACTOR_PATTERN | 9 | 5 / 4 |
| SIMILAR_PROJECT | 8 | 4 / 4 |
| GEOGRAPHIC_PATTERN | 8 | 5 / 3 |
| MULTI_SIGNAL | 8 | 4 / 4 |

Anomalous 49 (32.7%), normal 101, adversarial normals 41 (40.6% of normals).

## 5. Label file

`evaluation_labels.csv`: `project_id, ground_truth_label, scenario_type, difficulty (OBVIOUS|BORDERLINE|NA), injected_signals, group_id, severity, adversarial_subtype, rationale`.
`injected_signals` is multi-valued (`COST_INFLATION`, `BILLING_COMPRESSION`, `BILLING_ENDLOAD`, `CONTRACTOR_CONCENTRATION`, `DUPLICATE_LIKE`, `GEO_CLUSTER`) so V2.2 can score detectors separately. `group_id` links members of a pair/cluster/portfolio.

## 6. Known threats to validity

See `known_limitations` in `evaluation_metadata.json`. Main ones: same-author design, README-informed families, small n (wide confidence intervals), binary labels, adversarial cases relying on fields the engine may ignore (ADV-C estimate, ADV-D bill structure).
