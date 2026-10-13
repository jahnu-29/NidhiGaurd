# NidhiGuard — Anomaly Scenario Documentation

**Prototype Environment — Synthetic Demonstration Data.**
Every scenario below describes a *risk signal pattern*, not a fraud
allegation. The generator plants these patterns deliberately so a
downstream intelligence engine can be validated against known ground
truth (see `data/anomaly_signals.csv`).

> Risk score indicates anomaly signals and does not constitute a finding of fraud.

## Target distribution (achieved by the generator)

| Group | Share | Meaning |
|---|---|---|
| Normal | ~75% | No planted signal |
| Single-signal | ~17% | Exactly one planted anomaly type |
| Multi-signal | ~8% | Two or more correlated planted anomalies (includes the hero case) |

## Scenario 1 — Normal project

No planted signal. Cost sits within ~±10% of its comparable cluster mean,
contractor has an unremarkable project history, bills follow the expected
3–6 step cadence spread across the project timeline, payments trail bills
by a realistic number of days, and the location is an unremarkable point
inside its district.

## Scenario 2 — Cost anomaly (`COST_ANOMALY`)

A project's `sanctioned_amount` is generated **1.5×–1.8×** above the mean
of its comparable group (same `work_type` + district-level bucket, pulled
from both sibling current projects and `historical_projects.csv`), while
everything else about it (contractor, billing cadence, location) looks
ordinary. This mirrors the "₹18–21 lakh cluster vs. ₹34 lakh outlier"
example from the brief — a meaningful but not absurd deviation.

## Scenario 3 — Similar / potential duplicate projects (`SIMILAR_PROJECT`)

Small clusters (2–3 projects) are generated with near-identical
`project_description` templates, the same `work_type`, overlapping
`sanction_date`/`start_date` windows, comparable `sanctioned_amount`, and
`locations` within roughly 1–3 km of each other — but distinct
`project_id`s, distinct `project_code`s, and often distinct contractors or
implementing agencies. The intelligence layer is expected to surface these
via text + geographic similarity, not via any shared key.

## Scenario 4 — Contractor pattern (`CONTRACTOR_PATTERN`)

One or more "pattern contractors" are given a normal-sized project
portfolio, but a subset (roughly a third) of their projects are clustered
in `award_date` (awarded within a short window of each other), repeat the
same `work_type`, and sit in the higher end of their cost cluster. The
majority of the contractor's other projects remain completely ordinary —
the signal is a *concentration/clustering* pattern across the connected
projects, not a property of the contractor as an entity.

## Scenario 5 — Billing anomaly (`BILLING_ANOMALY`)

The project's `bills.csv` rows are generated with unusually short gaps
between `bill_date`/`submission_date` (several bills within days of each
other rather than spread across the work period), and a disproportionate
share of the total `claimed_amount` concentrated in a bill raised close to
`actual_completion_date`. Amounts still reconcile arithmetically —
`approved_amount ≤ claimed_amount` and payments never exceed approvals —
so the anomaly lives in the *timing/pattern*, not in broken arithmetic.

## Scenario 6 — Geographic pattern (`GEOGRAPHIC_SIGNAL`)

A tight geographic cluster (projects within ~1–2 km of each other) is
generated in a single block/village. Most members of the cluster are
ordinary. A subset within that same cluster additionally shares similar
`work_type`, comparable `sanctioned_amount`, and (for some) the same
contractor or implementing agency — so the *combination* of tight
geography plus shared attributes is what should trip the signal, not
proximity alone.

## Hero case — P-1023

`P-1023` ("Construction of Concrete Road – Ward 14") is generated as the
strongest `MULTI_SIGNAL` case, deliberately combining all five patterns:

1. **Cost anomaly** — sanctioned ~1.7× its comparable cluster mean.
2. **Similar-project relationship** — two sibling projects (`P-1024`,
   `P-1057`-style IDs, see `anomaly_signals.csv` for the actual generated
   IDs) with near-identical descriptions and close locations.
3. **Contractor pattern** — its contractor is a "pattern contractor" with a
   cluster of closely-awarded, same-work-type, higher-cost projects.
4. **Billing anomaly** — compressed bill timing with a large claim near
   completion.
5. **Geographic signal** — sits inside a tight, attribute-sharing
   geographic cluster.

`data/anomaly_signals.csv` contains one row per independent signal for
`P-1023` (`signal_type = MULTI_SIGNAL` parent row plus the underlying
individual rows), each carrying `related_entity_id` pointing at the
concrete contractor/project/cluster that produced it, so a scoring engine
can be built and unit-tested against a known answer such as:

```
Project P-1023 — Construction of Concrete Road – Ward 14
Risk Score: ~91 / 100   Risk Level: HIGH
  Cost anomaly:         25 / 25
  Project similarity:   23 / 25
  Contractor pattern:   18 / 20
  Billing anomaly:      15 / 20
  Geographic signal:    10 / 10
```

These exact weights are illustrative only — the data merely needs to
*support* an explainable breakdown along these lines; the scoring formula
itself belongs to the intelligence-layer codebase, not to this data
generator.
