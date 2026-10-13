# NidhiGuard — Relationship Diagram (textual)

```
                         ┌────────────────────┐
                         │   contractors.csv   │
                         │  contractor_id (PK) │
                         └─────────┬────────────┘
                                   │ 1
                                   │
                                   │ N
┌──────────────────┐     ┌────────▼─────────┐      ┌────────────────────────┐
│   locations.csv   │ 1 N│    projects.csv    │  1  N│ project_contractors.csv│
│  location_id (PK) ├────►  project_id (PK)   ├──────►  relationship_id (PK)  │
│  project_id (FK)  │    │  contractor_id(FK) │      │  project_id (FK)       │
└────────────────────┘    │  location_id (FK) │      │  contractor_id (FK)    │
                           └───┬───────────┬───┘      └────────────────────────┘
                               │1          │1
                               │           │
                               │N          │N
                     ┌─────────▼───┐  ┌────▼────────────┐
                     │  bills.csv   │  │ anomaly_signals  │
                     │  bill_id(PK) │  │  .csv            │
                     │ project_id   │  │  project_id (FK) │
                     │ contractor_id│  └──────────────────┘
                     └──────┬───────┘
                             │1
                             │
                             │N
                     ┌───────▼────────┐
                     │  payments.csv   │
                     │  payment_id(PK) │
                     │  bill_id (FK)   │
                     │  project_id(FK) │
                     │ contractor_id   │
                     └─────────────────┘

        (standalone, joined only by attributes — not by ID —
         for statistical comparison, never for live transactions)
                     ┌───────────────────────────┐
                     │   historical_projects.csv  │
                     │  work_type / district /    │
                     │  category used as join key │
                     └───────────────────────────┘
```

## Join keys an intelligence engine will actually use

1. **Cost-anomaly detection**
   `projects.work_type + projects.state/district (+ rough size)`
   ⟶ compare `projects.sanctioned_amount` against the distribution of
   `historical_projects.sanctioned_amount` (and same-cluster current
   projects) for matching `work_type`/`district`.

2. **Similar-project / duplicate detection**
   `projects.project_description` (text similarity) +
   `locations.latitude/longitude` (proximity) +
   `projects.work_type` + overlapping `sanction_date`/`start_date` windows.
   No shared ID is provided on purpose — the engine must discover the
   relationship, exactly like a real duplicate-works case.

3. **Contractor pattern detection**
   `projects.contractor_id` ⟶ group all projects for one contractor, look at
   the spread of `sanctioned_amount`, `work_type` repetition, geographic
   clustering (via `locations`), and how close together `work_order_date`
   values fall.

4. **Billing anomaly detection**
   `bills.project_id` ⟶ order by `bill_date`, inspect the gaps between
   `submission_date` values and the share of `claimed_amount` billed close
   to `project.actual_completion_date`.

5. **Payment anomaly detection**
   `payments.bill_id` ⟶ `bills.approved_amount` reconciliation, and
   `payments.payment_date` vs `bills.approval_date` lag.

6. **Geographic signal**
   `locations.latitude/longitude` proximity clustering, cross-referenced
   with `projects.work_type`/`sanctioned_amount`/`contractor_id` to see
   whether a tight geographic cluster also shares other attributes.

## Referential integrity rules enforced by the generator/validator

- Every `projects.contractor_id` exists in `contractors.contractor_id`.
- Every `projects.location_id` exists in `locations.location_id` (1:1).
- Every `bills.project_id` exists in `projects.project_id`.
- Every `payments.bill_id` exists in `bills.bill_id`; `payments.project_id`
  and `payments.contractor_id` always match the parent bill's project and
  contractor.
- Every `project_contractors.project_id`/`contractor_id` pair exists in
  `projects.csv` / `contractors.csv`.
- Every `anomaly_signals.project_id` exists in `projects.csv`.
- `sum(payments.payment_amount for a bill) <= bills.approved_amount`.
- `bills.approved_amount <= bills.claimed_amount`.
- Date ordering: `sanction_date ≤ work_order_date ≤ start_date ≤
  work_period_start ≤ work_period_end ≤ submission_date ≤ approval_date ≤
  payment_date`, and `actual_completion_date` (if set) is the latest date
  on the project.
