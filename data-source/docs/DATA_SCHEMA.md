# NidhiGuard — Data Schema

**Prototype Environment — Synthetic Demonstration Data**
This entire dataset is fictional. No real MPs, contractors, citizens, bank
accounts, or phone numbers are used. All IDs, names, and financial figures
are synthetically generated for the purpose of demonstrating an anomaly
*signal* detection prototype.

> Risk score indicates anomaly signals and does not constitute a finding of fraud.

---

## 1. `projects.csv`

| Field | Type | Notes |
|---|---|---|
| project_id | string | PK. Format `P-1001`…`P-1200` |
| project_code | string | Human-facing MPLADS-style code, e.g. `MPLADS/TN/2023/0142` |
| project_name | string | |
| project_description | string | Free text, used for similarity detection |
| project_category | string | e.g. `Road Infrastructure`, `Drinking Water`, `Education Infrastructure` |
| work_type | string | e.g. `Concrete Road`, `Hand Pump Installation` |
| mp_id | string | FK → conceptual MP register (`MP-01`…`MP-30`) |
| constituency_id | string | FK (`CONST-01`…`CONST-30`) |
| district_id | string | FK (`DIST-01`…`DIST-30`) |
| state | string | |
| implementing_agency_id | string | e.g. `AGENCY-03` |
| contractor_id | string | FK → contractors.csv |
| location_id | string | FK → locations.csv |
| sanctioned_amount | float (INR) | |
| estimated_cost | float (INR) | |
| approved_amount | float (INR) | |
| actual_expenditure | float (INR) | |
| project_status | string | `Completed`, `In Progress`, `Delayed`, `Sanctioned` |
| sanction_date | date | |
| work_order_date | date | ≥ sanction_date |
| start_date | date | ≥ work_order_date |
| expected_completion_date | date | |
| actual_completion_date | date/blank | only if completed |
| completion_percentage | int 0–100 | |
| created_date | date | record-creation timestamp, = sanction_date |

## 2. `contractors.csv`

| Field | Type | Notes |
|---|---|---|
| contractor_id | string | PK, `C-001`…`C-075` |
| contractor_name | string | Fictional. A handful of contractors intentionally have 2–3 name *variants* (e.g. "ABC Infrastructure Pvt Ltd" / "ABC Infra Pvt. Ltd.") to exercise future entity-resolution logic, while `contractor_id` stays the true join key. |
| registration_number | string | Synthetic, e.g. `REG-TN-04821` |
| contractor_type | string | `Individual Proprietor`, `Partnership`, `Pvt Ltd`, `Public Works Cooperative` |
| district | string | home district |
| state | string | |
| registration_date | date | |
| active_status | string | `Active` / `Inactive` |
| total_projects | int | derived — count of projects.csv rows with this contractor_id |
| total_project_value | float | derived — sum of sanctioned_amount |
| contact_reference | string | synthetic placeholder, e.g. `CONTACT-C-014` (never a real phone/email) |

## 3. `bills.csv`

| Field | Type | Notes |
|---|---|---|
| bill_id | string | PK, `B-00001`… |
| project_id | string | FK |
| contractor_id | string | FK (denormalized for convenience) |
| bill_number | string | e.g. `BILL/2023/0007` |
| bill_date | date | |
| bill_type | string | `Advance`, `Running Account (RA)`, `Final` |
| claimed_amount | float | |
| approved_amount | float | ≤ claimed_amount |
| bill_status | string | `Approved`, `Pending`, `Rejected` |
| work_period_start | date | |
| work_period_end | date | ≥ work_period_start |
| submission_date | date | ≥ work_period_end |
| approval_date | date/blank | ≥ submission_date, blank if not yet approved |

## 4. `payments.csv`

| Field | Type | Notes |
|---|---|---|
| payment_id | string | PK, `PAY-00001`… |
| bill_id | string | FK |
| project_id | string | FK (denormalized) |
| contractor_id | string | FK (denormalized) |
| payment_date | date | ≥ bill approval_date |
| payment_reference | string | synthetic UTR-style string, e.g. `UTR-SIM-000482` — **not a real bank reference** |
| payment_amount | float | ≤ bill approved_amount; sum of payments per bill ≤ approved_amount |
| payment_mode | string | `PFMS Transfer`, `RTGS`, `Cheque` |
| payment_status | string | `Success`, `Processing` |
| approving_authority | string | synthetic role label, e.g. `District Program Officer` |

## 5. `locations.csv`

| Field | Type | Notes |
|---|---|---|
| location_id | string | PK, `L-0001`… |
| project_id | string | FK (1:1 with projects for this MVP) |
| state | string | |
| district | string | |
| constituency | string | |
| block | string | synthetic block name |
| village_or_ward | string | synthetic |
| latitude | float | jittered around district reference point |
| longitude | float | jittered around district reference point |
| pincode | string | synthetic, district-consistent prefix |
| location_type | string | `Urban Ward`, `Rural Village`, `Panchayat` |

## 6. `historical_projects.csv`

Comparable/completed projects used purely as a statistical baseline for
cost-anomaly detection. Not linked into the live bills/payments graph.

| Field | Type | Notes |
|---|---|---|
| historical_project_id | string | PK, `H-0001`… |
| project_description | string | |
| project_category | string | |
| work_type | string | |
| state | string | |
| district | string | |
| constituency | string | |
| latitude | float | |
| longitude | float | |
| sanctioned_amount | float | |
| actual_expenditure | float | |
| completion_date | date | earlier date range than current projects |
| contractor_id | string | FK, may reuse contractors.csv IDs |
| implementing_agency_id | string | |

## 7. `project_contractors.csv`

Kept separate so the model supports multiple contractors per project later,
even though this MVP is one-primary-contractor-per-project.

| Field | Type | Notes |
|---|---|---|
| relationship_id | string | PK, `REL-0001`… |
| project_id | string | FK |
| contractor_id | string | FK |
| role | string | `Primary Contractor` (this MVP always uses this role) |
| contract_value | float | = project sanctioned_amount |
| award_date | date | = work_order_date |

## 8. `anomaly_signals.csv`

Ground truth of every anomaly planted during generation, used to validate
that the (separately built) intelligence engine actually recovers them.

| Field | Type | Notes |
|---|---|---|
| signal_id | string | PK, `SIG-001`… |
| project_id | string | FK — the project the signal is attached to |
| signal_type | string | `COST_ANOMALY`, `SIMILAR_PROJECT`, `CONTRACTOR_PATTERN`, `BILLING_ANOMALY`, `PAYMENT_ANOMALY`, `GEOGRAPHIC_SIGNAL`, `MULTI_SIGNAL` |
| severity | string | `LOW`, `MEDIUM`, `HIGH` |
| expected_reason | string | short human-readable summary |
| related_entity_id | string | contractor_id / other project_id / cluster_id depending on signal_type |
| planted_for_testing | bool | always `True` in this file |
| explanation | string | longer explanation, phrased as a *signal*, never as an accusation |

All monetary fields are in INR (plain float, not paise) and are entirely
synthetic.
