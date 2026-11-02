# NidhiGuard V2.2 - V1 Engine Evaluation Report

_Controlled synthetic evaluation. Not real MPLADS ground truth. Predictions are from the unmodified V1 engine; nothing was tuned._

## 1. Dataset summary

- Projects: **150** (49 anomalous, 101 normal; prevalence 0.327)
- Scenario counts: NORMAL 60, ADVERSARIAL_NORMAL 41, COST_ANOMALY 8, BILLING_ANOMALY 8, CONTRACTOR_PATTERN 9, SIMILAR_PROJECT 8, GEOGRAPHIC_PATTERN 8, MULTI_SIGNAL 8
- Predicted risk levels: LOW 129, MEDIUM 21
- Risk score: min 11.8, median 17.65, mean 21.85, max 55.5
- Labels match frozen hash: **True**; predictions made from frozen engine input: **True**

## 2. Overall metrics

| Metric | Value |
|---|--:|
| PR-AUC (average precision) | **0.845** (random baseline 0.327) |
| PR-AUC (trapezoid, for transparency) | 0.843 |
| Precision@5 / @10 / @20 | 1.00 / 0.90 / 0.85 |
| Recall@20 (top-20 captures) | 17 of 49 = 0.347 |
| Precision@49 (R-precision) | 0.796 |
| Recall at risk_score >= 40 | 0.184 |
| Bootstrap 95% CI, average precision | [0.741, 0.934] (optimistic) |

## 3. Precision@K (ranked by risk_score desc, project_id asc for ties)

| K | Anomalous in top K | Precision@K | Recall@K |
|--:|--:|--:|--:|
| 5 | 5 | 1.00 | 0.102 |
| 10 | 9 | 0.90 | 0.184 |
| 20 | 17 | 0.85 | 0.347 |

Random-ranking baseline precision = prevalence = 0.327.

## 4. Thresholded confusion matrix

**Thresholded classification at risk_score >= 40**

| | Predicted anomaly | Predicted normal |
|---|--:|--:|
| Actual anomalous | TP 9 | FN 40 |
| Actual normal | FP 1 | TN 100 |

Precision 0.900, recall 0.184, F1 0.305, false-positive rate 0.010

**Reference: V1 investigation-queue cutoff (non-LOW) at risk_score >= 30**

| | Predicted anomaly | Predicted normal |
|---|--:|--:|
| Actual anomalous | TP 18 | FN 31 |
| Actual normal | FP 3 | TN 98 |

Precision 0.857, recall 0.367, F1 0.514, false-positive rate 0.030

_The primary threshold (40) is the one specified for V2.2. V1 code defines levels at 30/60/80 and builds its queue from every non-LOW project (>= 30); 40 does not appear in V1. Both are fixed in advance; neither was chosen from these results._

## 5. PR-AUC

Average precision **0.845** vs random baseline 0.327; trapezoid 0.843. Computed from the continuous risk_score, not risk_level.

## 6. Scenario-level results

| Scenario | n | Anom/Norm | Mean | Median | Max | >=40 | Rate >=40 | >=30 | Rate >=30 | Rate means |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| NORMAL | 60 | 0/60 | 16.3 | 16.8 | 21.3 | 0 | 0.00 | 0 | 0.00 | false_positive_rate |
| ADVERSARIAL_NORMAL | 41 | 0/41 | 19.5 | 17.1 | 45.3 | 1 | 0.02 | 3 | 0.07 | false_positive_rate |
| COST_ANOMALY | 8 | 8/0 | 37.9 | 38.5 | 45.5 | 1 | 0.12 | 7 | 0.88 | detection_rate |
| BILLING_ANOMALY | 8 | 8/0 | 26.3 | 27.0 | 28.1 | 0 | 0.00 | 0 | 0.00 | detection_rate |
| CONTRACTOR_PATTERN | 9 | 9/0 | 26.3 | 24.8 | 34.5 | 0 | 0.00 | 3 | 0.33 | detection_rate |
| SIMILAR_PROJECT | 8 | 8/0 | 21.9 | 22.2 | 23.5 | 0 | 0.00 | 0 | 0.00 | detection_rate |
| GEOGRAPHIC_PATTERN | 8 | 8/0 | 22.9 | 27.2 | 28.6 | 0 | 0.00 | 0 | 0.00 | detection_rate |
| MULTI_SIGNAL | 8 | 8/0 | 48.4 | 48.4 | 55.5 | 8 | 1.00 | 8 | 1.00 | detection_rate |

By difficulty (anomalous scenarios):

| Scenario | Difficulty | n | Mean | Max | >=40 | >=30 |
|---|---|--:|--:|--:|--:|--:|
| COST_ANOMALY | OBVIOUS | 4 | 40.1 | 45.5 | 1 | 4 |
| COST_ANOMALY | BORDERLINE | 4 | 35.8 | 38.9 | 0 | 3 |
| BILLING_ANOMALY | OBVIOUS | 4 | 25.2 | 27.1 | 0 | 0 |
| BILLING_ANOMALY | BORDERLINE | 4 | 27.4 | 28.1 | 0 | 0 |
| CONTRACTOR_PATTERN | OBVIOUS | 5 | 28.6 | 34.5 | 0 | 3 |
| CONTRACTOR_PATTERN | BORDERLINE | 4 | 23.5 | 25.1 | 0 | 0 |
| SIMILAR_PROJECT | OBVIOUS | 4 | 22.2 | 22.5 | 0 | 0 |
| SIMILAR_PROJECT | BORDERLINE | 4 | 21.5 | 23.5 | 0 | 0 |
| GEOGRAPHIC_PATTERN | OBVIOUS | 5 | 27.8 | 28.6 | 0 | 0 |
| GEOGRAPHIC_PATTERN | BORDERLINE | 3 | 14.8 | 15.1 | 0 | 0 |
| MULTI_SIGNAL | OBVIOUS | 5 | 50.0 | 55.5 | 5 | 5 |
| MULTI_SIGNAL | BORDERLINE | 3 | 45.8 | 49.6 | 3 | 3 |

## 7. Adversarial-normal results (treated as NORMAL)

- Count 41; mean 19.5, median 17.1, max 45.3
- >= 40: 1 (false-positive rate 0.024); >= 30: 3 (false-positive rate 0.073)

| Subtype | n | Mean | Max | >=40 | >=30 |
|---|--:|--:|--:|--:|--:|
| A | 14 | 16.0 | 18.5 | 0 | 0 |
| B | 9 | 17.8 | 22.1 | 0 | 0 |
| C | 5 | 31.6 | 45.3 | 1 | 3 |
| D | 5 | 24.3 | 26.2 | 0 | 0 |
| E | 8 | 17.2 | 23.3 | 0 | 0 |

## 8. Top 20 highest-risk projects

| Rank | project_id | risk_score | risk_level | ground_truth_label | scenario_type |
|--:|---|--:|---|---|---|
| 1 | P-5062 | 55.5 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 2 | P-5044 | 50.3 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 3 | P-5135 | 49.8 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 4 | P-5035 | 49.6 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 5 | P-5066 | 47.1 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 6 | P-5116 | 47.1 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 7 | P-5131 | 45.5 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 8 | P-5106 | 45.4 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 9 | P-5040 | 45.3 | MEDIUM | NORMAL | ADVERSARIAL_NORMAL |
| 10 | P-5005 | 42.4 | MEDIUM | ANOMALOUS | MULTI_SIGNAL |
| 11 | P-5114 | 39.3 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 12 | P-5070 | 38.9 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 13 | P-5060 | 38.8 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 14 | P-5145 | 38.3 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 15 | P-5010 | 38.1 | MEDIUM | NORMAL | ADVERSARIAL_NORMAL |
| 16 | P-5041 | 37.2 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 17 | P-5081 | 37.2 | MEDIUM | ANOMALOUS | COST_ANOMALY |
| 18 | P-5048 | 36.9 | MEDIUM | NORMAL | ADVERSARIAL_NORMAL |
| 19 | P-5031 | 34.5 | MEDIUM | ANOMALOUS | CONTRACTOR_PATTERN |
| 20 | P-5100 | 33.4 | MEDIUM | ANOMALOUS | CONTRACTOR_PATTERN |

## 9. Limitations and interpretation notes

- Controlled synthetic dataset built by the same author as the V1 detectors; it measures agreement with that author's definition of suspicious, not real-world fraud detection.
- Scenario families mirror the detector families (README-informed). CONTRACTOR_PATTERN was written after the author saw one V1 planted-signal sentence; read that row with extra caution.
- 150 cases (49 anomalous). Bootstrap intervals use row resampling and ignore linked groups, so they are optimistic. Small differences between scenarios are not significant.
- The V1 score never reached HIGH (60) or CRITICAL (80) on this data, so risk_level carries little information here; the continuous score is used for ranking and PR-AUC.
- Primary threshold 40 was specified for V2.2; V1's own queue cutoff is non-LOW (>= 30). Both are reported; neither was selected from these results.
- ADV-C and ADV-D rely on fields (estimated cost, bill structure) the engine may not use; false positives there are findings about V1, not dataset defects.
- PR-AUC ties: tied scores form a single threshold, while Precision@K breaks ties by project_id ascending; the two can differ slightly where scores tie.
- No threshold, weight or detector was changed in response to these results.
