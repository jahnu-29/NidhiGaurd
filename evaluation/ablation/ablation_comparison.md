# V2.4 Detector Ablation Study

_This ablation study evaluates detector contribution on the frozen V2.1 synthetic evaluation set. It does not establish real-world fraud-detection effectiveness._

## 1. Objective

Determine which of NidhiGuard V1's five detectors (cost anomaly, project similarity, contractor pattern, billing anomaly, geographic signal) contribute to its measured performance, by removing one detector at a time and re-scoring the same frozen evaluation projects. This is evaluation only: V1, the dataset, the labels, the V2.2 metrics and the V2.3 baselines are unchanged.

## 2. Experimental design

- Six variants: FULL (the original V1) and five ablations that each set exactly one detector's contribution to zero.
- Scores are produced in a label-free stage from V1's own frozen component scores (`evaluation_predictions.csv`); labels are first read in the separate metrics stage, using the V2.2 metric implementation.
- Nothing is retuned, rescaled or re-weighted. Removing a detector lowers a variant's maximum possible score by that detector's cap, and V1's level boundaries (30/60/80) are kept.
- Ranking metrics (average precision, Precision@K, Recall@20) use the continuous score, ties broken by project_id ascending. Threshold counts use the fixed cutoffs 30 (V1's LOW/MEDIUM boundary) and 40 (the V2.2 evaluation threshold, not a native V1 boundary); because every ablation shifts scores down, threshold counts partly change by arithmetic and the ranking metrics are the fairer comparison.

## 3. V1 scoring formula

Read from `intelligence/risk_engine.py` (`RiskEngine.score_project`), not assumed:

```
raw_total  = cost.score + similarity.score + contractor.score + billing.score + geographic.score
risk_score = round(min(100.0, raw_total), 1)
```

| Component | Cap (its MAX_SCORE) |
|---|--:|
| cost_anomaly | 25 |
| project_similarity | 25 |
| contractor_pattern | 20 |
| billing_anomaly | 20 |
| geographic_signal | 10 |

No separate weights: each detector scales itself to its own cap, so the caps are the weights. Levels: CRITICAL if score >= 80; HIGH if >= 60; MEDIUM if >= 30; else LOW. The cap of 100 never binds with these detector caps. Recomputing this expression from the frozen component scores reproduces every frozen V1 risk_score exactly: **True**. An ablation re-applies the same expression with one term set to 0.0 (it is not FULL minus the component).

## 4. Dataset

The frozen V2.1 evaluation set: **150 projects**, **49 anomalous**, **101 normal**, of which **41 are adversarial normals**. Same projects and labels as V2.2 and V2.3 (labels match their frozen hash: True). Scenario counts: NORMAL 60, ADVERSARIAL_NORMAL 41, COST_ANOMALY 8, BILLING_ANOMALY 8, CONTRACTOR_PATTERN 9, SIMILAR_PROJECT 8, GEOGRAPHIC_PATTERN 8, MULTI_SIGNAL 8.

## 5. Variants

| Variant | Detector removed | Maximum possible score |
|---|---|--:|
| FULL | none | 100 |
| NO_COST | cost_anomaly | 75 |
| NO_SIMILARITY | project_similarity | 75 |
| NO_CONTRACTOR | contractor_pattern | 80 |
| NO_BILLING | billing_anomaly | 80 |
| NO_GEOGRAPHIC | geographic_signal | 90 |

## 6. Metrics

Average precision (PR-AUC, a ranking-quality measure, not accuracy); Precision@5/10/20; Recall@20 (anomalous in the top 20 / all anomalous); anomalous projects and adversarial normals at score >= 30 and >= 40; scenario-level detection. Delta = ABLATION - FULL: a negative delta means removing the detector lowered the metric.

## 7. Main results

| Variant | PR-AUC | P@5 | P@10 | P@20 | Recall@20 |
|---|--:|--:|--:|--:|--:|
| FULL | 0.845 | 1.00 | 0.90 | 0.85 | 0.347 |
| NO_COST | 0.787 | 1.00 | 1.00 | 0.90 | 0.367 |
| NO_SIMILARITY | 0.735 | 0.80 | 0.60* | 0.80 | 0.327 |
| NO_CONTRACTOR | 0.819 | 1.00 | 0.90 | 0.85 | 0.347 |
| NO_BILLING | 0.795 | 1.00 | 1.00 | 0.85 | 0.347 |
| NO_GEOGRAPHIC | 0.811 | 1.00 | 0.90 | 0.85 | 0.347 |

\* Tie-sensitive: NO_SIMILARITY P@10 is 0.60 with ties broken by project_id, but could be anywhere from 0.60 to 0.90 (9 projects tie at rank 10, mixing anomalous and normal). Average precision is tie-aware and is not affected. All other Precision@K values are independent of tie order.

Deltas, ABLATION - FULL (negative = removing the detector reduced the metric):

| Variant | delta PR-AUC | delta P@20 | delta Recall@20 | delta P@5 | delta P@10 |
|---|--:|--:|--:|--:|--:|
| NO_COST | -0.058 | +0.05 | +0.020 | +0.00 | +0.10 |
| NO_SIMILARITY | -0.110 | -0.05 | -0.020 | -0.20 | -0.30* |
| NO_CONTRACTOR | -0.027 | +0.00 | +0.000 | +0.00 | +0.00 |
| NO_BILLING | -0.051 | +0.00 | +0.000 | +0.00 | +0.10 |
| NO_GEOGRAPHIC | -0.034 | +0.00 | +0.000 | +0.00 | +0.00 |

- NO_COST: delta PR-AUC -0.058; removing cost anomaly reduced PR-AUC by 0.058.
- NO_SIMILARITY: delta PR-AUC -0.110; removing project similarity reduced PR-AUC by 0.110.
- NO_CONTRACTOR: delta PR-AUC -0.027; removing contractor pattern reduced PR-AUC by 0.027.
- NO_BILLING: delta PR-AUC -0.051; removing billing anomaly reduced PR-AUC by 0.051.
- NO_GEOGRAPHIC: delta PR-AUC -0.034; removing geographic signal reduced PR-AUC by 0.034.

Threshold counts (anomalous detected / total flagged), rank agreement with FULL, and tie structure:

| Variant | Anomalous >=30 | Flagged >=30 | Anomalous >=40 | Flagged >=40 | Spearman vs FULL | Top-20 shared with FULL | Distinct scores | Largest tie block (score) | Tie across rank 20/21? |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| FULL | 18 | 21 | 9 | 10 | 1.000 | 20 | 76 | 10 (15.1) | no |
| NO_COST | 1 | 1 | 0 | 0 | 0.705 | 6 | 62 | 12 (15.1) | no |
| NO_SIMILARITY | 4 | 5 | 0 | 0 | 0.815 | 19 | 38 | 88 (0.0) | no |
| NO_CONTRACTOR | 15 | 18 | 9 | 10 | 0.984 | 18 | 74 | 10 (15.1) | no |
| NO_BILLING | 18 | 21 | 5 | 5 | 0.886 | 20 | 68 | 10 (17.1) | no |
| NO_GEOGRAPHIC | 18 | 21 | 9 | 10 | 0.970 | 20 | 73 | 10 (17.1) | no |

Ties: average precision treats tied scores as a single threshold, so it does not depend on project_id order. Precision@K breaks ties by project_id ascending; a Precision@K value is tie-sensitive only if the tied block at rank K mixes anomalous and normal projects. Precision@K that depends on the tie-break: NO_SIMILARITY P@10 (reported 0.60, possible range 0.60-0.90). Large blocks of identical scores (projects with no signal from the remaining detectors): NO_SIMILARITY has 88 projects tied at 0.0.

## 8. Detector contribution analysis

Contribution = AP(FULL) - AP(variant); positive means the detector helped on this evaluation set. Intervals are from a paired bootstrap of AP(variant) - AP(FULL).

| Rank | Detector removed | Contribution (AP) | Contribution (P@20) | Contribution (Recall@20) | Interval of delta AP | Removal reliably hurts? |
|--:|---|--:|--:|--:|---|---|
| 1 | project_similarity | +0.110 | +0.05 | +0.020 | [-0.173, -0.049] | yes |
| 2 | cost_anomaly | +0.058 | -0.05 | -0.020 | [-0.169, +0.053] | no |
| 3 | billing_anomaly | +0.051 | +0.00 | +0.000 | [-0.114, +0.006] | no |
| 4 | geographic_signal | +0.034 | +0.00 | +0.000 | [-0.076, -0.005] | yes |
| 5 | contractor_pattern | +0.027 | +0.00 | +0.000 | [-0.054, -0.006] | yes |

_Supplementary optimistic bootstrap interval; row resampling does not account for linked synthetic scenario groups._

- **Strongest contributor on this set:** project_similarity (removal changes PR-AUC by -0.110).
- **Second strongest:** cost_anomaly (removal changes PR-AUC by -0.058).
- **Small contribution** (|change in PR-AUC| < 0.02, an operational label): none.
- **Removal improved PR-AUC:** none; no ablation increased PR-AUC.
- **Removal improved a top-of-queue metric (even though PR-AUC did not rise):** cost_anomaly (precision at 10 +0.10, precision at 20 +0.05, recall at 20 +0.020); billing_anomaly (precision at 10 +0.10). Precision@K looks only at the first K projects, whereas PR-AUC weighs the whole ranking, so the two can disagree.
- **Removal changed no headline metric** (PR-AUC, P@5/10/20, Recall@20, detections and adversarial flags at 30/40 all identical to FULL): none.
- **Removal lowered the number of adversarial normals in the top 20 (a scale-free measure):** cost_anomaly.
- **Which detector's points separate each scenario from ordinary projects in V1's own scores** (mean component points above the NORMAL scenario, at least 1 point): COST_ANOMALY: cost anomaly +22.5; BILLING_ANOMALY: billing anomaly +10.0; CONTRACTOR_PATTERN: contractor pattern +5.1, cost anomaly +5.0; SIMILAR_PROJECT: project similarity +5.5; GEOGRAPHIC_PATTERN: geographic signal +6.2; MULTI_SIGNAL: cost anomaly +22.7, billing anomaly +7.5, project similarity +1.9. A detector can matter to the ranking because it is the only one separating a scenario, even when its average gap between anomalous and normal projects is small.
- Reading: these statements describe what happened when one detector was removed from this scoring formula on this dataset; they do not establish that any detector is unnecessary in general, and one-at-a-time removal cannot show how detectors compensate for each other.

Context: mean V1 component score per scenario (FULL variant), i.e. how many points each detector contributes on average:

| Group | cost (max 25) | similarity (max 25) | contractor (max 20) | billing (max 20) | geographic (max 10) |
|---|--:|--:|--:|--:|--:|
| all ANOMALOUS | 8.4 | 17.3 | 0.9 | 2.9 | 1.0 |
| all NORMAL | 1.3 | 15.7 | 0.0 | 0.5 | 0.1 |
| NORMAL | 0.1 | 16.2 | 0.0 | 0.0 | 0.0 |
| ADVERSARIAL_NORMAL | 3.0 | 15.1 | 0.0 | 1.2 | 0.2 |
| COST_ANOMALY | 22.6 | 15.3 | 0.0 | 0.0 | 0.0 |
| BILLING_ANOMALY | 0.0 | 16.3 | 0.0 | 10.0 | 0.0 |
| CONTRACTOR_PATTERN | 5.2 | 16.0 | 5.1 | 0.0 | 0.0 |
| SIMILAR_PROJECT | 0.2 | 21.6 | 0.0 | 0.0 | 0.0 |
| GEOGRAPHIC_PATTERN | 0.0 | 16.7 | 0.0 | 0.0 | 6.2 |
| MULTI_SIGNAL | 22.8 | 18.1 | 0.0 | 7.5 | 0.0 |

## 9. Adversarial-normal analysis

Max score, number flagged, and rank position of the 41 adversarial normals (legitimate look-alikes); a variant can gain anomaly detections while also flagging more of them. Flag counts at fixed cutoffs fall for every ablation partly because all scores shift down, so the scale-free columns (adversarial normals in the top 10 / top 20, rank of the best-placed one) are the fairer false-positive comparison.

| Variant | Max adversarial score | Flagged >=30 | Flagged >=40 | In top 10 | In top 20 | Best-placed adversarial rank | delta max score | delta flagged >=30 | delta flagged >=40 | delta in top 20 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| FULL | 45.3 | 3 | 1 | 1 | 3 | 9 | - | - | - | - |
| NO_COST | 26.2 | 0 | 0 | 0 | 2 | 13 | -19.1 | -3 | -1 | -1 |
| NO_SIMILARITY | 32.2 | 1 | 0 | 4 | 4 | 4 | -13.1 | -2 | -1 | +1 |
| NO_CONTRACTOR | 45.3 | 3 | 1 | 1 | 3 | 9 | +0.0 | +0 | +0 | +0 |
| NO_BILLING | 38.1 | 3 | 0 | 0 | 3 | 12 | -7.2 | +0 | -1 | +0 |
| NO_GEOGRAPHIC | 45.3 | 3 | 1 | 1 | 3 | 9 | +0.0 | +0 | +0 | +0 |

Adversarial normals flagged at >= 30, by subtype:

| Variant | ADV-A (n=14) | ADV-B (n=9) | ADV-C (n=5) | ADV-D (n=5) | ADV-E (n=8) |
|---|--:|--:|--:|--:|--:|
| FULL | 0 | 0 | 3 | 0 | 0 |
| NO_COST | 0 | 0 | 0 | 0 | 0 |
| NO_SIMILARITY | 0 | 0 | 1 | 0 | 0 |
| NO_CONTRACTOR | 0 | 0 | 3 | 0 | 0 |
| NO_BILLING | 0 | 0 | 3 | 0 | 0 |
| NO_GEOGRAPHIC | 0 | 0 | 3 | 0 | 0 |

## 10. Scenario-level analysis

Anomalous projects detected at score >= 30 / >= 40 per scenario, and mean percentile rank (1.0 = top-ranked, comparable across variants). Detection at fixed cutoffs falls partly by arithmetic when a detector's points are removed; the percentile column is scale-free.

| Scenario (n) | FULL | NO_COST | NO_SIMILARITY | NO_CONTRACTOR | NO_BILLING | NO_GEOGRAPHIC |
|---|--:|--:|--:|--:|--:|--:|
| COST_ANOMALY (8) | 7 / 1 | 0 / 0 | 0 / 0 | 7 / 1 | 7 / 1 | 7 / 1 |
| BILLING_ANOMALY (8) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| CONTRACTOR_PATTERN (9) | 3 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 3 / 0 | 3 / 0 |
| SIMILAR_PROJECT (8) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| GEOGRAPHIC_PATTERN (8) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| MULTI_SIGNAL (8) | 8 / 8 | 1 / 0 | 4 / 0 | 8 / 8 | 8 / 4 | 8 / 8 |

Mean percentile rank (relative: a scenario's percentile can rise when another scenario's detector is removed, because the other projects fall, without any detector detecting that scenario better):

| Scenario | FULL | NO_COST | NO_SIMILARITY | NO_CONTRACTOR | NO_BILLING | NO_GEOGRAPHIC |
|---|--:|--:|--:|--:|--:|--:|
| COST_ANOMALY | 0.91 | 0.26 | 0.90 | 0.91 | 0.93 | 0.91 |
| BILLING_ANOMALY | 0.79 | 0.92 | 0.80 | 0.80 | 0.39 | 0.82 |
| CONTRACTOR_PATTERN | 0.75 | 0.75 | 0.75 | 0.61 | 0.80 | 0.78 |
| SIMILAR_PROJECT | 0.66 | 0.78 | 0.41 | 0.69 | 0.75 | 0.70 |
| GEOGRAPHIC_PATTERN | 0.56 | 0.67 | 0.61 | 0.58 | 0.58 | 0.37 |
| MULTI_SIGNAL | 0.97 | 0.90 | 0.97 | 0.97 | 0.96 | 0.97 |
| NORMAL | 0.33 | 0.39 | 0.34 | 0.33 | 0.37 | 0.34 |
| ADVERSARIAL_NORMAL | 0.44 | 0.42 | 0.46 | 0.45 | 0.42 | 0.44 |

Scenario/variant pairs where the mean percentile rank moved by 0.05 or more versus FULL: COST_ANOMALY under NO_COST (-0.65); BILLING_ANOMALY under NO_COST (+0.13); BILLING_ANOMALY under NO_BILLING (-0.40); CONTRACTOR_PATTERN under NO_CONTRACTOR (-0.14); CONTRACTOR_PATTERN under NO_BILLING (+0.05); SIMILAR_PROJECT under NO_COST (+0.12); SIMILAR_PROJECT under NO_SIMILARITY (-0.25); SIMILAR_PROJECT under NO_BILLING (+0.08); GEOGRAPHIC_PATTERN under NO_COST (+0.10); GEOGRAPHIC_PATTERN under NO_GEOGRAPHIC (-0.19); MULTI_SIGNAL under NO_COST (-0.08).

## 11. Limitations

- This ablation study evaluates detector contribution on the frozen V2.1 synthetic evaluation set. It does not establish real-world fraud-detection effectiveness.
- The evaluation set is synthetic (150 projects, 49 anomalous) and its scenario families were designed around the same red-flag patterns as the detectors; the results measure agreement with that definition.
- One-at-a-time removal measures each detector's marginal effect inside V1's additive formula. It cannot show how detectors substitute for each other, and it says nothing about adding a detector to a different system.
- Detector scores are additive, so removing a detector also lowers every project's score by that detector's typical value (for example, project similarity contributes a near-constant baseline to most projects); fixed-cutoff counts at 30 and 40 therefore change partly by arithmetic, and the ranking metrics are the fairer comparison.
- Bootstrap intervals use row resampling and ignore the linked synthetic scenario groups, so they are optimistic; with this sample size small differences are not reliable.
- The 'small change' cutoff (0.02 in PR-AUC) is an operational label declared in advance, not a statistical test.
- Detector thresholds, caps and weights were not changed; nothing here recommends changing them.

## 12. Conclusion

On this frozen synthetic evaluation set, removing project similarity had the largest effect on PR-AUC (-0.110) and removing cost anomaly the second largest (-0.058). No ablation increased PR-AUC. The ablations disagree between the top of the queue and the whole ranking: removing cost anomaly (precision at 10 +0.10, precision at 20 +0.05, recall at 20 +0.020) and billing anomaly (precision at 10 +0.10) raised top-of-queue precision even though PR-AUC fell. Under the optimistic paired bootstrap, the PR-AUC decrease on removal is reliable for project similarity, geographic signal and contractor pattern, and not reliable for cost anomaly and billing anomaly. These are statements about detector contribution within V1's additive scoring on this dataset; they do not show that any detector is unnecessary or sufficient in general.

This ablation study evaluates detector contribution on the frozen V2.1 synthetic evaluation set. It does not establish real-world fraud-detection effectiveness.

