# V2.5 Investigation Queue and Operating-Point Analysis

_V2.5 evaluates how NidhiGuard's deterministic risk scores translate into investigation workload. Rather than arbitrarily tuning a fraud threshold, the evaluation compares predefined score thresholds and Top-K operating points, exposing the precision/recall and false-positive trade-offs for investigators._

## 1. Objective, scope and vocabulary

Show how V1's existing deterministic risk scores translate into investigation workload on the frozen V2.1 evaluation set: how many projects must be reviewed at each operating point, and what precision, recall and false-positive trade-offs follow. This stage is evaluation only. V1, its thresholds, weights and queue rule, the dataset, the labels and the V2.2 to V2.4 implementations are unchanged. No threshold was searched or chosen using the labels: the thresholds and capacities below were fixed in advance.

Four concepts are kept separate:

- **Model score**: The deterministic anomaly/risk score produced by V1 (risk_score, 0-100 scale, in practice compressed). It is not a probability of fraud.
- **Evaluation threshold**: A score cutoff (risk_score >= T) used only to study performance on the frozen V2.1 set. It is not calibrated for production.
- **Investigator operating point**: A hypothetical workload constraint such as Top-20 (review the 20 highest-scored projects). It does not represent actual staffing.
- **Production threshold**: What V1 actually does today: the investigation queue is every project whose risk_level is not LOW (risk_score >= 30), ranked by score descending.

## 2. Frozen inputs and V1 facts

- Score formula: `risk_score = round(min(100.0, cost + similarity + contractor + billing + geographic), 1); caps 25/25/20/20/10`.
- Risk-level boundaries: LOW < 30 <= MEDIUM < 60 <= HIGH < 80 <= CRITICAL (unchanged).
- Production queue rule: production queue = every project with risk_level != LOW, i.e. risk_score >= 30 (V1 route /api/investigation-queue), sorted by score descending.
- Dataset: **150 projects**, **49 anomalous**, **101 normal** (including **41 adversarial normals**); the same projects and labels as V2.2 to V2.4 (labels match their frozen hash: True).
- Scores come from the frozen `evaluation/evaluation_predictions.csv` (column `risk_score`). Ranking: score descending, project_id ascending for ties; V1's production route sorts by score only, so its tie order can differ from this evaluation ordering.

## 3. Score distribution

Minimum 11.8, maximum 55.5, mean 21.85, median 17.65, standard deviation 9.34 (population), quartiles 15.70 / 17.65 / 24.95. There are 76 distinct scores; the largest tie block is 10 projects at 15.1.

| Score band | Projects | Anomalous | Normal | of which adversarial | Share anomalous |
|---|--:|--:|--:|--:|--:|
| <20 | 89 | 5 | 84 | 28 | 5.6% |
| 20-24.9 | 23 | 12 | 11 | 7 | 52.2% |
| 25-29.9 | 17 | 14 | 3 | 3 | 82.4% |
| 30-34.9 | 3 | 3 | 0 | 0 | 100.0% |
| 35-39.9 | 8 | 6 | 2 | 2 | 75.0% |
| 40-44.9 | 1 | 1 | 0 | 0 | 100.0% |
| 45-49.9 | 7 | 6 | 1 | 1 | 85.7% |
| >=50 | 2 | 2 | 0 | 0 | 100.0% |

| V1 risk level | Projects | Anomalous | Normal | of which adversarial |
|---|--:|--:|--:|--:|
| LOW | 129 | 31 | 98 | 38 |
| MEDIUM | 21 | 18 | 3 | 3 |
| HIGH | 0 | 0 | 0 | 0 |
| CRITICAL | 0 | 0 | 0 | 0 |

What this means for queue sizing: the observed scores occupy only 11.8-55.5 of the theoretical 0-100 scale, and no project reaches HIGH or CRITICAL. Mean score is 30.5 for anomalous and 17.6 for normal projects. Because the scale is compressed, a cutoff expressed in points moves the queue size by a lot per few points (see section 4), and a score is a deterministic anomaly score, not a probability: a score of 40 does not mean a 40% chance of fraud.

## 4. Fixed-score evaluation thresholds

Evaluation thresholds, fixed in advance. Only 30 is V1's own boundary (the production queue floor); 40 was the V2.2 evaluation threshold and is not a native V1 boundary.

| Threshold | Queued | % of dataset | TP | FP | TN | FN | Precision | Recall | F1 | Adversarial queued | % of adversarial | Plain normals queued |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| >= 20 | 61 | 40.7% | 44 | 17 | 84 | 5 | 0.721 | 0.898 | 0.800 | 13 | 31.7% | 4 |
| >= 25 | 38 | 25.3% | 32 | 6 | 95 | 17 | 0.842 | 0.653 | 0.736 | 6 | 14.6% | 0 |
| >= 30 (V1 production queue) | 21 | 14.0% | 18 | 3 | 98 | 31 | 0.857 | 0.367 | 0.514 | 3 | 7.3% | 0 |
| >= 35 | 18 | 12.0% | 15 | 3 | 98 | 34 | 0.833 | 0.306 | 0.448 | 3 | 7.3% | 0 |
| >= 40 (V2.2 eval. threshold) | 10 | 6.7% | 9 | 1 | 100 | 40 | 0.900 | 0.184 | 0.305 | 1 | 2.4% | 0 |
| >= 45 | 9 | 6.0% | 8 | 1 | 100 | 41 | 0.889 | 0.163 | 0.276 | 1 | 2.4% | 0 |
| >= 50 | 2 | 1.3% | 2 | 0 | 101 | 47 | 1.000 | 0.041 | 0.078 | 0 | 0.0% | 0 |

Anomalous projects captured = TP; normal projects incorrectly queued = FP. Precision is n/a when nothing is queued.

## 5. Investigator-capacity operating points (Top-K)

Hypothetical workload constraints, labelled as evaluation operating points; they do not represent real staffing levels.

| Top-K | % of dataset | Anomalous captured | Recall | Precision | False positives | Lowest selected score | Tie at cutoff | Adversarial in queue | Highest-ranked normal |
|--:|--:|--:|--:|--:|--:|--:|---|--:|---|
| 5 | 3.3% | 5 | 0.102 | 1.000 | 0 | 47.1 | 2 tied at 47.1; 1 outside the queue; label mix does not matter | 0 | P-5040 at rank 9 (not in queue) |
| 10 | 6.7% | 9 | 0.184 | 0.900 | 1 | 42.4 | none | 1 | P-5040 at rank 9 (in queue) |
| 20 | 13.3% | 17 | 0.347 | 0.850 | 3 | 33.4 | none | 3 | P-5040 at rank 9 (in queue) |
| 25 | 16.7% | 22 | 0.449 | 0.880 | 3 | 28.1 | none | 3 | P-5040 at rank 9 (in queue) |
| 30 | 20.0% | 27 | 0.551 | 0.900 | 3 | 27.1 | 3 tied at 27.1; 1 outside the queue; label mix does not matter | 3 | P-5040 at rank 9 (in queue) |
| 40 | 26.7% | 33 | 0.673 | 0.825 | 7 | 24.1 | none | 7 | P-5040 at rank 9 (in queue) |
| 50 | 33.3% | 39 | 0.796 | 0.780 | 11 | 22.1 | none | 11 | P-5040 at rank 9 (in queue) |

The highest-ranked normal project overall is P-5040 (ADVERSARIAL_NORMAL), at rank 9 with score 45.3; every project ranked above it is anomalous. Ties are broken by project_id ascending, which is deterministic but arbitrary; the tie column shows where it could change a count.

## 6. Fixed threshold versus Top-K

**A. Fixed-score queue** (`risk_score >= T`) versus **B. Top-K queue**. At the same queue size the two select the same projects whenever there is no tie at the cutoff: this holds for 7 of 7 thresholds here. The difference is therefore not which projects are chosen but how the size is decided: a fixed threshold lets the score scale decide the workload, while a Top-K queue fixes the workload and lets the scale decide how deep the list goes.

- V1's native queue (>= 30) holds 21 projects with 18 anomalous captured (precision 0.857, recall 0.367); Top-20 captures 17 (precision 0.850, recall 0.347) and Top-25 captures 22 (precision 0.880, recall 0.449).
- Workload is sensitive to a few points of score: moving the cutoff from 20 to 25 changes the queue by 23 projects, whereas 30 to 35 changes it by 3.
- Score-scale sensitivity (supplementary, from the frozen V2.4 ablation scores; no variant or threshold is selected): applying the same `>= 30` cutoff to the six scoring variants queues between 1 and 21 projects, whereas a Top-20 queue is 20 projects in every variant.

| Scoring variant | Highest score observed | Queued at >= 30 | Anomalous at >= 30 | Queued at >= 40 | Anomalous at >= 40 | Anomalous in Top-10 | Anomalous in Top-20 |
|---|--:|--:|--:|--:|--:|--:|--:|
| FULL | 55.5 | 21 | 18 | 10 | 9 | 9 | 17 |
| NO_COST | 30.5 | 1 | 1 | 0 | 0 | 10 | 18 |
| NO_SIMILARITY | 35.0 | 5 | 4 | 0 | 0 | 6 | 16 |
| NO_CONTRACTOR | 55.5 | 18 | 15 | 10 | 9 | 9 | 17 |
| NO_BILLING | 47.1 | 21 | 18 | 5 | 5 | 10 | 17 |
| NO_GEOGRAPHIC | 55.5 | 21 | 18 | 10 | 9 | 9 | 17 |

Trade-off. A fixed threshold is simple to state and audit and does not force a review when nothing scores high, but its workload moves with the score scale and with a few points of score. A Top-K queue gives a predictable workload and is unaffected by score-scale shifts, but it forces K reviews even when fewer projects look suspicious, and it hides that the K-th project may score barely above the (K+1)-th. V1's production queue already combines both: a ranked list with a score floor, so an investigator can stop at any rank.

## 7. Adversarial normals

The 41 adversarial normals are deliberately difficult legitimate cases. Their maximum score is 45.3 (mean 19.5, median 17.1).

| Operating point | Queue size | Adversarial queued | % of the 41 | Plain normals queued | Adversarial share of all false positives |
|---|--:|--:|--:|--:|--:|
| >= 20 | 61 | 13 | 31.7% | 4 | 76.5% |
| >= 25 | 38 | 6 | 14.6% | 0 | 100.0% |
| >= 30 | 21 | 3 | 7.3% | 0 | 100.0% |
| >= 35 | 18 | 3 | 7.3% | 0 | 100.0% |
| >= 40 | 10 | 1 | 2.4% | 0 | 100.0% |
| >= 45 | 9 | 1 | 2.4% | 0 | 100.0% |
| >= 50 | 2 | 0 | 0.0% | 0 | n/a |
| Top-5 | 5 | 0 | 0.0% | 0 | n/a |
| Top-10 | 10 | 1 | 2.4% | 0 | 100.0% |
| Top-20 | 20 | 3 | 7.3% | 0 | 100.0% |
| Top-25 | 25 | 3 | 7.3% | 0 | 100.0% |
| Top-30 | 30 | 3 | 7.3% | 0 | 100.0% |
| Top-40 | 40 | 7 | 17.1% | 0 | 100.0% |
| Top-50 | 50 | 11 | 26.8% | 0 | 100.0% |

Highest-scored adversarial normals (rank among all 150): P-5040 ADV-C score 45.3 rank 9; P-5010 ADV-C score 38.1 rank 15; P-5048 ADV-C score 36.9 rank 18; P-5024 ADV-D score 26.2 rank 33; P-5043 ADV-C score 25.0 rank 37.

## 8. Scenario capture

Anomalous projects captured per scenario, by evaluation threshold and by Top-K (denominators are the V2.1 scenario sizes).

| Operating point | COST_ANOMALY (8) | BILLING_ANOMALY (8) | CONTRACTOR_PATTERN (9) | SIMILAR_PROJECT (8) | GEOGRAPHIC_PATTERN (8) | MULTI_SIGNAL (8) |
|---|--:|--:|--:|--:|--:|--:|
| >= 20 | 8 | 8 | 9 | 6 | 5 | 8 |
| >= 25 | 8 | 7 | 4 | 0 | 5 | 8 |
| >= 30 | 7 | 0 | 3 | 0 | 0 | 8 |
| >= 35 | 7 | 0 | 0 | 0 | 0 | 8 |
| >= 40 | 1 | 0 | 0 | 0 | 0 | 8 |
| >= 45 | 1 | 0 | 0 | 0 | 0 | 7 |
| >= 50 | 0 | 0 | 0 | 0 | 0 | 2 |
| Top-5 | 0 | 0 | 0 | 0 | 0 | 5 |
| Top-10 | 1 | 0 | 0 | 0 | 0 | 8 |
| Top-20 | 7 | 0 | 2 | 0 | 0 | 8 |
| Top-25 | 8 | 1 | 3 | 0 | 2 | 8 |
| Top-30 | 8 | 3 | 3 | 0 | 5 | 8 |
| Top-40 | 8 | 7 | 5 | 0 | 5 | 8 |
| Top-50 | 8 | 8 | 6 | 4 | 5 | 8 |

## 9. Plots

- [Risk-score distribution](plots/score_distribution.svg)
- [Queue size vs recall](plots/queue_size_vs_recall.svg)
- [Queue size vs precision](plots/queue_size_vs_precision.svg)
- [Threshold vs number queued](plots/threshold_vs_queued.svg)
- [Threshold vs precision and recall](plots/threshold_vs_precision_recall.svg)

Plain SVG files generated without plotting libraries, so they are byte-identical on every run. The queue-size curves show every K for shape; markers are the predefined capacities, and no point is selected.

## 10. Answers to the required questions

**Q1. What happens to investigator workload as the score threshold increases?** It falls steadily, but unevenly: >= 20: 61 (40.7%), >= 25: 38 (25.3%), >= 30: 21 (14.0%), >= 35: 18 (12.0%), >= 40: 10 (6.7%), >= 45: 9 (6.0%), >= 50: 2 (1.3%). The largest single step is 20 to 25 (-23 projects); the step from 30 to 35 removes only 3. Workload is therefore very sensitive to where a cutoff sits on this compressed scale.

**Q2. What happens to precision and recall?** Recall falls from 0.898 at >= 20 to 0.041 at >= 50 (it cannot rise as the cutoff rises). Precision goes from 0.721 to 1.000 and is not monotonic across the seven thresholds. At V1's production boundary (>= 30): precision 0.857, recall 0.367 (18 of 49 anomalous). At >= 40: precision 0.900, recall 0.184 (9 of 49). In the Top-K view the trade-off appears as K grows: recall rises from 0.10 (Top-5) to 0.80 (Top-50) while precision goes from 1.00 to 0.78 and is not monotonic across the seven capacities: Top-5 recall 0.10 / precision 1.00, Top-10 recall 0.18 / precision 0.90, Top-20 recall 0.35 / precision 0.85, Top-25 recall 0.45 / precision 0.88, Top-30 recall 0.55 / precision 0.90, Top-40 recall 0.67 / precision 0.82, Top-50 recall 0.80 / precision 0.78.

**Q3. Is a fixed threshold or Top-K more appropriate for an investigation workflow?** On this evaluation set, a Top-K (capacity-bounded, ranked) queue is the more predictable workflow: fixed cutoffs gave queue sizes of 1-21 across the six scoring variants and moved by up to 23 projects for a five-point change, while Top-K stays at its capacity. A fixed floor is easier to explain and avoids forced reviews. Because V1's production queue is already ranked by score with a floor of 30, the practical difference is whether the investigator stops at the floor (21 projects) or at a chosen capacity; this study does not show that either rule should replace the other.

**Q4. How vulnerable are the queues to adversarial normals?** At >= 30, 3 of the 41 adversarial normals are queued (7.3%) and they are 100.0% of the false positives; at >= 40, 1 (2.4%). At >= 25 the count rises to 6 and at >= 20 to 13. The highest-scored adversarial normal (P-5040, ADV-C) scores 45.3 and ranks 9 of 150, so it is queued at >= 20, >= 25, >= 30, >= 35, >= 40 and >= 45; the first predefined cutoff that excludes every adversarial normal is >= 50, at a recall of 0.041. In Top-K terms, the Top-10 contains 1 adversarial normal and the Top-20 contains 3.

**Q5. Which operating points give useful trade-offs without claiming to be production-calibrated?** The following are evaluation operating points chosen for workload reasons from the predefined lists, not because they maximise any metric:

| Candidate | Kind | Queue | % of dataset | Anomalous captured | Precision | Recall | Adversarial queued | Why (operational) |
|---|---|--:|--:|--:|--:|--:|--:|---|
| V1 native queue: risk_score >= 30 | production threshold | 21 | 14.0% | 18 | 0.857 | 0.367 | 3 | This is what V1 does today (every non-LOW project); it is the baseline any alternative must be compared with. |
| Top-10 | investigator operating point | 10 | 6.7% | 9 | 0.900 | 0.184 | 1 | A small high-priority tier for a reviewer with very little capacity; about 7% of this pool. |
| Top-20 | investigator operating point | 20 | 13.3% | 17 | 0.850 | 0.347 | 3 | Roughly the same workload as the native queue, but fixed in size however the score scale moves. |
| risk_score >= 40 | evaluation threshold | 10 | 6.7% | 9 | 0.900 | 0.184 | 1 | A narrow high-score tier, shown for continuity with V2.2; not a V1 boundary. |
| Top-40 | investigator operating point | 40 | 26.7% | 33 | 0.825 | 0.673 | 7 | A deliberately wide net (about 27% of the pool) to show how much precision is given up for coverage. |

**Q6. Does V2.5 justify changing the V1 production queue?** **No.** (1) V1's production queue is already a ranked list with a score floor, so an investigator can already work top-down and stop at any capacity; nothing here shows that rule is wrong. (2) The evidence is one synthetic, author-designed set of 150 projects, with scores that are not calibrated to any real outcome. (3) The descriptive observation that the 25-29.9 band is dense with anomalies (a cutoff of 25 would queue 38 projects instead of 21, capturing 32 instead of 18 anomalous at the cost of 6 instead of 3 false positives) describes a trade-off on these labels; adopting it would be exactly the label-driven threshold tuning this stage excludes. (4) A score is a deterministic anomaly score, not a probability. Any change to the production queue should wait for calibration against real review outcomes.

## 11. Limitations

- The dataset is synthetic (150 projects, 49 anomalous) and its scenarios were designed around the same red-flag patterns as V1's detectors; these results measure agreement with that design, not real-world fraud detection.
- The thresholds and capacities are predefined evaluation operating points, not production-calibrated thresholds, and Top-K sizes do not represent actual investigator staffing.
- With 150 projects, differences of one or two projects between operating points are within noise; no confidence intervals are computed here.
- Tied scores are ordered by project_id ascending for determinism; V1's production route does not break ties that way, so its exact Top-K membership at a tie may differ.
- The score-scale sensitivity table reuses the frozen V2.4 ablation scores purely as an illustration of how fixed cutoffs depend on the score scale; the variants are not alternative production systems.
- Precision and recall here depend on the V2.1 prevalence (32.7% anomalous), which is far higher than any realistic fraud rate; absolute precision values should not be transferred to production.

## 12. Conclusion

On this frozen synthetic evaluation set, raising the score threshold shrinks the queue from 61 to 2 projects while recall falls from 0.898 to 0.041. The head of the ranking is dense with anomalies (9 of the Top-10), but recall at V1's production cutoff is limited (0.367), and the first adversarial normal appears at rank 9, accounting for every false positive at >= 30. V2.5 does not justify changing V1's production queue; it supplies a transparent description of the operating-point trade-offs, to be revisited when real review outcomes are available.

