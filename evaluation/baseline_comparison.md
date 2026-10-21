# V2.3 Baseline Comparison

_Controlled synthetic evaluation. Nothing was tuned: NidhiGuard V1, the dataset, the labels and the V2.2 metrics are unchanged._

## Objective

Test whether NidhiGuard's multi-detector engine adds value beyond two simpler approaches, evaluated on exactly the same frozen V2.1 evaluation projects and labels as V2.2: (1) a cost-deviation score, which shows how much cost alone explains, and (2) a generic Isolation Forest, a standard unsupervised anomaly detector. The result is reported whichever way it falls.

## Dataset

150 independent evaluation projects: **49 anomalous**, **101 normal**, of which **41 are adversarial normals** (legitimate look-alikes, counted as normal). Verified from the files: labels match their frozen hash (True); baseline and V1 predictions were made from the frozen engine input (True); all three approaches cover the same 150 project IDs. Scenario counts: NORMAL 60, ADVERSARIAL_NORMAL 41, COST_ANOMALY 8, BILLING_ANOMALY 8, CONTRACTOR_PATTERN 9, SIMILAR_PROJECT 8, GEOGRAPHIC_PATTERN 8, MULTI_SIGNAL 8.

## Methods

### NidhiGuard V1

The frozen reference system: five deterministic detectors (cost, similarity, contractor, billing, geographic) combined into a 0-100 risk score. Its predictions are the unchanged V2.2 file `evaluation_predictions.csv`.

### Cost-Deviation Baseline

`score = sanctioned_amount / median(historical sanctioned_amount of the same work type)`. score = sanctioned_amount / median(historical sanctioned_amount of the same work_type); pooled across states; historical table only; one-sided (higher = more anomalous); no tuning. It is the same idea family as V1's cost detector by design (to isolate what cost alone explains), but simpler: no state adjustment, historical table only, no group-size logic beyond a sanity floor, no scaling. It does not look at estimates, bills, contractors or locations.

### Isolation Forest

Unsupervised `sklearn.ensemble.IsolationForest`, fitted on the 150 evaluation projects without any labels, V1 output or planted signal. Parameters: n_estimators=200, max_samples=auto, contamination=auto (no anomaly prevalence assumed), random_state=2303, n_jobs=1. Score = -score_samples (higher = more anomalous). No scaling or categorical encoding (tree splits are scale-invariant); no imputation (NaN/inf would raise). Features were fixed before any result was seen:

| Feature | Why it is a defensible generic feature |
|---|---|
| `log_cost_ratio` | cost level relative to the work type's historical median, on a log scale |
| `sanction_over_estimate` | sanction versus the estimate: a standard procurement red flag |
| `bill_count` | billing activity volume |
| `billed_over_sanctioned` | share of the sanction already billed |
| `payment_count` | payment activity volume |
| `contractor_project_count` | contractor workload concentration within the pool |
| `neighbors_within_5km` | local project density |
| `nearest_neighbor_km_log1p` | spatial isolation from other projects |

Deliberately excluded: work type/state/category, planned duration, approved/actual amounts, dates, contractor attributes, descriptions.

### Thresholded comparison: matched alert budgets

The baselines have no native threshold, and V1's thresholds do not transfer to other score scales. So thresholded results use a label-free matched budget taken from V1's own output: **Budget A = 21** (number of projects V1 scores at or above its LOW/MEDIUM boundary (risk_score >= 30)) and **Budget B = 10** (number of projects V1 scores at or above the V2.2 evaluation threshold (risk_score >= 40)). Each baseline flags its top-21 / top-10 projects, so every method reviews the same number of projects. No threshold was chosen from labels.

## Results

| Approach | PR-AUC (average precision) | Precision@5 | Precision@10 | Precision@20 | Recall@20 (anomalous projects in the top 20 / all anomalous) |
|---|--:|--:|--:|--:|--:|
| NidhiGuard V1 | 0.845 | 1.00 | 0.90 | 0.85 | 0.347 |
| Cost-Deviation | 0.666 | 1.00 | 0.90 | 0.80 | 0.327 |
| Isolation Forest | 0.651 | 0.80 | 0.90 | 0.80 | 0.327 |

PR-AUC is a ranking-quality measure, not accuracy. Random ranking gives precision = prevalence = 0.327. Ranking metrics compare the continuous scores directly.

| Approach | Budget | Flagged | TP | FP | FN | Precision | Recall | F1 |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| NidhiGuard V1 (V1 native cutoff 30) | A (21) | 21 | 18 | 3 | 31 | 0.857 | 0.367 | 0.514 |
| NidhiGuard V1 (V1 native cutoff 40) | B (10) | 10 | 9 | 1 | 40 | 0.900 | 0.184 | 0.305 |
| Cost-Deviation | A (21) | 21 | 16 | 5 | 33 | 0.762 | 0.327 | 0.457 |
| Cost-Deviation | B (10) | 10 | 9 | 1 | 40 | 0.900 | 0.184 | 0.305 |
| Isolation Forest | A (21) | 21 | 17 | 4 | 32 | 0.810 | 0.347 | 0.486 |
| Isolation Forest | B (10) | 10 | 9 | 1 | 40 | 0.900 | 0.184 | 0.305 |

## Precision@K

| Approach | Anomalous in top 5 | Precision@5 | Anomalous in top 10 | Precision@10 | Anomalous in top 20 | Precision@20 |
|---|--:|--:|--:|--:|--:|--:|
| NidhiGuard V1 | 5 | 1.00 | 9 | 0.90 | 17 | 0.85 |
| Cost-Deviation | 5 | 1.00 | 9 | 0.90 | 16 | 0.80 |
| Isolation Forest | 4 | 0.80 | 9 | 0.90 | 16 | 0.80 |

Ranking: risk/anomaly score descending, project_id ascending for ties.

## PR-AUC

| Approach | Average precision | Trapezoid AUC | Random baseline |
|---|--:|--:|--:|
| NidhiGuard V1 | 0.845 | 0.843 | 0.327 |
| Cost-Deviation | 0.666 | 0.663 | 0.327 |
| Isolation Forest | 0.651 | 0.638 | 0.327 |

Paired bootstrap of the difference in average precision (same resampled projects for both methods):

- NidhiGuard V1 minus Cost-Deviation: +0.177, interval [+0.086, +0.284]; first better in 100% of resamples.
- NidhiGuard V1 minus Isolation Forest: +0.184, interval [+0.037, +0.342]; first better in 100% of resamples.
- Cost-Deviation minus Isolation Forest: +0.007, interval [-0.140, +0.152]; first better in 54% of resamples.

_Supplementary optimistic bootstrap interval; row resampling does not account for linked synthetic scenario groups._

## Recall

| Approach | Recall@20 (anomalous projects in the top 20 / all anomalous) | Recall at budget A (21) | Recall at budget B (10) | Precision@49 (R-precision) |
|---|--:|--:|--:|--:|
| NidhiGuard V1 | 0.347 | 0.367 | 0.184 | 0.796 |
| Cost-Deviation | 0.327 | 0.327 | 0.184 | 0.592 |
| Isolation Forest | 0.327 | 0.347 | 0.184 | 0.551 |

## Adversarial Normal Analysis

Adversarial normals are legitimate look-alikes (ADV-A large portfolio, ADV-B nearby unrelated works, ADV-C high cost with corroborating estimate, ADV-D milestone billing, ADV-E similar wording only), counted as NORMAL. A flagged adversarial normal is a false positive. Counts are at matched budgets A (21) and B (10).

| Approach | Adversarial n | FP at A | FP rate at A | FP at B | FP rate at B | Mean percentile rank |
|---|--:|--:|--:|--:|--:|--:|
| NidhiGuard V1 | 41 | 3 | 0.073 | 1 | 0.024 | 0.44 |
| Cost-Deviation | 41 | 4 | 0.098 | 1 | 0.024 | 0.47 |
| Isolation Forest | 41 | 0 | 0.000 | 0 | 0.000 | 0.43 |

Flagged at budget A, by subtype:

| Approach | ADV-A (n=14) | ADV-B (n=9) | ADV-C (n=5) | ADV-D (n=5) | ADV-E (n=8) |
|---|--:|--:|--:|--:|--:|
| NidhiGuard V1 | 0 | 0 | 3 | 0 | 0 |
| Cost-Deviation | 0 | 0 | 4 | 0 | 0 |
| Isolation Forest | 0 | 0 | 0 | 0 | 0 |

## Scenario-level detection

Projects flagged at budget A (21) per scenario (for NORMAL and ADVERSARIAL_NORMAL these are false positives), and mean percentile rank (1.0 = top-ranked) which is comparable across score scales.

| Scenario | n | V1 flagged | Cost flagged | IF flagged | V1 mean pct | Cost mean pct | IF mean pct |
|---|--:|--:|--:|--:|--:|--:|--:|
| NORMAL | 60 | 0 | 1 | 4 | 0.33 | 0.39 | 0.39 |
| ADVERSARIAL_NORMAL | 41 | 3 | 4 | 0 | 0.44 | 0.47 | 0.43 |
| COST_ANOMALY | 8 | 7 | 8 | 4 | 0.91 | 0.94 | 0.82 |
| BILLING_ANOMALY | 8 | 0 | 0 | 0 | 0.79 | 0.55 | 0.51 |
| CONTRACTOR_PATTERN | 9 | 3 | 0 | 0 | 0.75 | 0.77 | 0.56 |
| SIMILAR_PROJECT | 8 | 0 | 0 | 0 | 0.66 | 0.38 | 0.55 |
| GEOGRAPHIC_PATTERN | 8 | 0 | 0 | 6 | 0.56 | 0.44 | 0.90 |
| MULTI_SIGNAL | 8 | 8 | 8 | 7 | 0.97 | 0.94 | 0.91 |

## Overlap between methods

Anomalous projects caught (inside the top-21 / V1's flagged set) by each method; IDs are in `baseline_comparison.json`.

| Group | Count | By scenario |
|---|--:|---|
| Cost baseline catches, V1 misses | 1 | COST_ANOMALY 1 |
| Isolation Forest catches, V1 misses | 6 | GEOGRAPHIC_PATTERN 6 |
| V1 catches, both baselines miss | 3 | CONTRACTOR_PATTERN 3 |
| All three catch | 11 | COST_ANOMALY 4, MULTI_SIGNAL 7 |
| Missed by all three | 24 | BILLING_ANOMALY 8, CONTRACTOR_PATTERN 6, GEOGRAPHIC_PATTERN 2, SIMILAR_PROJECT 8 |

Adversarial normals wrongly flagged at budget A: NidhiGuard V1: 3 (P-5010 ADV-C, P-5040 ADV-C, P-5048 ADV-C); Cost-Deviation: 4 (P-5010 ADV-C, P-5040 ADV-C, P-5043 ADV-C, P-5048 ADV-C); Isolation Forest: 0 (none).

## Score distributions and top-ranked projects

| Approach | Min | P25 | Median | Mean | P75 | Max |
|---|--:|--:|--:|--:|--:|--:|
| NidhiGuard V1 | 11.800 | 15.700 | 17.650 | 21.849 | 24.950 | 55.500 |
| Cost-Deviation | 0.656 | 0.942 | 1.050 | 1.241 | 1.265 | 3.831 |
| Isolation Forest | 0.370 | 0.409 | 0.457 | 0.460 | 0.488 | 0.686 |

Top 10 by score (full top 20 in the JSON):

| Rank | NidhiGuard V1 | Cost-Deviation | Isolation Forest |
|--:|---|---|---|
| 1 | P-5062 55.50 ANOM (MULTI_SIGNAL) | P-5081 3.83 ANOM (COST_ANOMALY) | P-5042 0.69 norm (NORMAL) |
| 2 | P-5044 50.30 ANOM (MULTI_SIGNAL) | P-5044 3.70 ANOM (MULTI_SIGNAL) | P-5044 0.63 ANOM (MULTI_SIGNAL) |
| 3 | P-5135 49.80 ANOM (MULTI_SIGNAL) | P-5062 3.47 ANOM (MULTI_SIGNAL) | P-5135 0.63 ANOM (MULTI_SIGNAL) |
| 4 | P-5035 49.60 ANOM (MULTI_SIGNAL) | P-5114 3.45 ANOM (COST_ANOMALY) | P-5103 0.62 ANOM (GEOGRAPHIC_PATTERN) |
| 5 | P-5066 47.10 ANOM (MULTI_SIGNAL) | P-5131 3.36 ANOM (COST_ANOMALY) | P-5116 0.61 ANOM (MULTI_SIGNAL) |
| 6 | P-5116 47.10 ANOM (MULTI_SIGNAL) | P-5135 3.11 ANOM (MULTI_SIGNAL) | P-5066 0.61 ANOM (MULTI_SIGNAL) |
| 7 | P-5131 45.50 ANOM (COST_ANOMALY) | P-5145 3.05 ANOM (COST_ANOMALY) | P-5081 0.60 ANOM (COST_ANOMALY) |
| 8 | P-5106 45.40 ANOM (MULTI_SIGNAL) | P-5066 2.42 ANOM (MULTI_SIGNAL) | P-5062 0.59 ANOM (MULTI_SIGNAL) |
| 9 | P-5040 45.30 norm (ADVERSARIAL_NORMAL) | P-5116 2.36 ANOM (MULTI_SIGNAL) | P-5114 0.59 ANOM (COST_ANOMALY) |
| 10 | P-5005 42.40 ANOM (MULTI_SIGNAL) | P-5040 2.27 norm (ADVERSARIAL_NORMAL) | P-5090 0.58 ANOM (GEOGRAPHIC_PATTERN) |

## Where NidhiGuard Wins

- average_precision vs Cost-Deviation: V1 0.845 vs 0.666
- average_precision vs Isolation Forest: V1 0.845 vs 0.651
- precision_at_5 vs Isolation Forest: V1 1.000 vs 0.800
- precision_at_20 vs Cost-Deviation: V1 0.850 vs 0.800
- precision_at_20 vs Isolation Forest: V1 0.850 vs 0.800
- CONTRACTOR_PATTERN: V1 flags 3/9 at budget A vs cost 0 and Isolation Forest 0

## Where NidhiGuard Loses

- COST_ANOMALY: V1 flags 7/8 at budget A vs cost 8 and Isolation Forest 4
- GEOGRAPHIC_PATTERN: V1 flags 0/8 at budget A vs cost 0 and Isolation Forest 6
- Adversarial normals flagged at budget A: V1 3 vs cost 4 and Isolation Forest 0

Tied with the best method at budget A: BILLING_ANOMALY (0/8 for the best method); SIMILAR_PROJECT (0/8 for the best method); MULTI_SIGNAL (8/8 for the best method).

V1 metrics equal to a baseline: precision_at_5 vs Cost-Deviation, precision_at_10 vs Cost-Deviation, precision_at_10 vs Isolation Forest.

## Interpretation

- Average precision ranks the approaches NidhiGuard V1 (0.845) > Cost-Deviation (0.666) > Isolation Forest (0.651); random ranking is 0.327.
- NidhiGuard V1 minus Cost-Deviation: +0.177 average precision; the optimistic interval excludes zero.
- NidhiGuard V1 minus Isolation Forest: +0.184 average precision; the optimistic interval excludes zero.
- Cost-Deviation minus Isolation Forest: +0.007 average precision; the optimistic interval includes zero, so this difference is not reliable.
- Cost deviation alone reaches 0.79x V1's average precision and flags anomalies in: COST_ANOMALY, MULTI_SIGNAL at budget A.
- The generic Isolation Forest reaches 0.77x V1's average precision and flags anomalies in: COST_ANOMALY, GEOGRAPHIC_PATTERN, MULTI_SIGNAL at budget A.
- Scenarios where only V1 flags anything at budget A (neither baseline does): CONTRACTOR_PATTERN.
- At the top of the queue the methods are close: precision@5 is 1.00 / 1.00 / 0.80 and precision@10 is 0.90 / 0.90 / 0.90 (V1 / cost / Isolation Forest). The gaps are larger lower in the ranking: R-precision (precision at K = number of anomalous projects) is 0.80 / 0.59 / 0.55.
- Mean percentile rank by anomalous scenario (V1 / cost / Isolation Forest; 1.0 = top-ranked): COST_ANOMALY 0.91/0.94/0.82; BILLING_ANOMALY 0.79/0.55/0.51; CONTRACTOR_PATTERN 0.75/0.77/0.56; SIMILAR_PROJECT 0.66/0.38/0.55; GEOGRAPHIC_PATTERN 0.56/0.44/0.90; MULTI_SIGNAL 0.97/0.94/0.91.
- V1 mean component scores by anomalous scenario (maxima: cost 25, similarity 25, contractor 20, billing 20, geographic 10), for context on what drives V1's score: COST_ANOMALY: cost 22.6, similarity 15.3, contractor 0.0, billing 0.0, geographic 0.0; BILLING_ANOMALY: cost 0.0, similarity 16.3, contractor 0.0, billing 10.0, geographic 0.0; CONTRACTOR_PATTERN: cost 5.2, similarity 16.0, contractor 5.1, billing 0.0, geographic 0.0; SIMILAR_PROJECT: cost 0.2, similarity 21.6, contractor 0.0, billing 0.0, geographic 0.0; GEOGRAPHIC_PATTERN: cost 0.0, similarity 16.7, contractor 0.0, billing 0.0, geographic 6.2; MULTI_SIGNAL: cost 22.8, similarity 18.1, contractor 0.0, billing 7.5, geographic 0.0.
- Read together: these numbers describe how the three scoring methods behave on this constructed dataset; they do not isolate which detector or feature causes a difference, and they do not show a cost-only or generic method is inadequate in general.

## Limitations

- The evaluation dataset is synthetic.
- The scenario families are designed around known red-flag patterns, and V1's detector families were designed around the same patterns; results measure agreement with that definition.
- This is not real-world fraud-detection validation and no real investigation outcomes are available.
- Isolation Forest results depend on feature selection and preprocessing; the eight features were fixed in advance, but a different defensible feature set could rank differently. No feature search was performed, and the author knew the dataset's construction rules when choosing features.
- The estimate-to-sanction ratio is a feature available to the Isolation Forest but (by construction of the cost scenarios) also the field that separates COST_ANOMALY from the ADV-C adversarial cases; V1 may not use it. Any advantage this gives a baseline reflects the dataset design as well as the method.
- All 8 of 8 MULTI_SIGNAL cases include a cost-inflation component by construction, so a cost-only method is expected to rank them highly; the strong cost-baseline MULTI_SIGNAL and COST_ANOMALY rows partly reflect that design, as do V1's.
- The Isolation Forest feature set includes two spatial-density features (neighbours within 5 km, nearest-neighbour distance) and GEOGRAPHIC_PATTERN cases are tight spatial clusters, so that scenario matches these generic features well; which features drive the forest's ranking was not analysed.
- Matched-budget thresholds depend on V1's output volume (A and B); they are label-free but are not natural thresholds for the baselines.
- 150 projects (49 anomalous) in linked scenario groups; small differences are within noise, and the bootstrap intervals are optimistic.
- A baseline comparison does not establish production effectiveness.

## Conclusion

On this independent synthetic evaluation set, NidhiGuard V1 had the highest average precision (0.845). Against the cost-deviation baseline, V1 ranked better than the cost-deviation baseline by more than the optimistic bootstrap noise; against the Isolation Forest, V1 ranked better than the Isolation Forest by more than the optimistic bootstrap noise. At the top of the queue, precision@10 was V1 0.90, cost 0.90, Isolation Forest 0.90. These results are specific to this constructed dataset and do not establish real-world effectiveness.

