# NidhiGuard — Synthetic Data Foundation

**MPLADS Intelligence & Monitoring System**
*Detect Early. Explain Clearly. Prioritise Intelligently.*

> **Prototype Environment — Synthetic Demonstration Data.**
> Every ID, name, project, contractor, bill, and payment in this dataset is
> fictional and generated for a Smart India Hackathon prototype. Nothing
> here refers to a real MP, contractor, citizen, or transaction.
>
> Risk score indicates anomaly signals and does not constitute a finding of fraud.

This package is **only** the synthetic-data foundation described in the
brief — the relational dataset an intelligence layer (built separately)
will read, correlate, and score. It does not implement any scoring logic
itself.

## What's in here

```
data/
  projects.csv              200 current MPLADS-style projects
  contractors.csv           75 contractors
  bills.csv                 ~890 bills
  payments.csv              ~985 payments
  locations.csv             200 project locations
  historical_projects.csv   500 completed comparable projects
  project_contractors.csv   200 project–contractor relationships
  anomaly_signals.csv       ~60 planted ground-truth anomaly signals

scripts/
  generate_data.py          deterministic generator (SEED = 42)
  validate_data.py          referential-integrity + scenario validator

docs/
  DATA_SCHEMA.md            field-by-field schema for every CSV
  RELATIONSHIPS.md          textual ER diagram + join-key guidance
  ANOMALY_SCENARIOS.md      what each planted anomaly story is and why
```

## Quick start

```bash
# Regenerate the dataset (idempotent — same seed, same output every time)
python scripts/generate_data.py --outdir data

# Validate referential integrity + confirm every planted scenario exists
python scripts/validate_data.py --datadir data
```

`validate_data.py` exits `0` and prints `DATA VALIDATION PASSED` when the
dataset is internally consistent, or `1` with an itemised error list
otherwise. It specifically checks that project `P-1023` — the hero
demonstration case used by the frontend prototype — exists and carries
every one of the five underlying signal types (cost, similarity,
contractor pattern, billing, geography), plus the roll-up `MULTI_SIGNAL`
row.

## How the dataset is built

`generate_data.py` does **not** create rows independently and hope
anomalies show up statistically. It works the other way round:

1. It first designs every anomaly *story* (Scenarios 2–6 from the brief,
   plus the hero case) as explicit "specs" — deciding the work type,
   comparable-cost cluster, contractor, and location each story needs.
2. It reserves index 22 in the project sequence for the hero case, so a
   full re-run always produces the hero at `P-1023`.
3. It fills every remaining project slot with an ordinary, unremarkable
   project drawn from the same reference data (states/districts, work
   types, contractors) as the anomaly stories, so anomalous and normal
   projects are statistically comparable rather than visually distinct.
4. From the finished project list it derives bills, payments, and
   locations, keeping billing timing "compressed" only for the projects
   whose story calls for a billing-pattern anomaly.
5. Finally it writes `anomaly_signals.csv` as the ground truth of exactly
   what was planted, so a separately-built intelligence engine can be
   scored against a known answer.

## Current distribution (this run)

| Group | Projects | Share |
|---|---|---|
| Normal | 159 | ~79.5% |
| Single planted signal | 24 | ~12% |
| Multi-signal (correlated) | 17 | ~8.5% |

This sits inside the brief's normal/multi-signal targets; the single-signal
share is a little under the 15–20% target for this particular seed/size —
acceptable for an MVP, and easy to nudge by adjusting the `n_cost_anom` /
`n_billing` / `n_dup_clusters` constants in `generate_data.py` if a future
run needs a different mix.

## The hero case — P-1023

"Construction of Concrete Road – Ward 14" is the strongest connected
anomaly case, deliberately combining all five signal types described in
`docs/ANOMALY_SCENARIOS.md`. It exists specifically so a downstream
intelligence layer can be unit-tested against a known, explainable,
multi-signal answer (illustrative target: **Risk Score ≈ 91/100, HIGH**).

## Regenerating with a different scale

```bash
python scripts/generate_data.py --n_projects 300 --n_contractors 100 --n_historical 800
```

The hero case stays at `P-1023` for any `--n_projects` ≥ 23. Re-running
with the same arguments always reproduces byte-identical CSVs because the
random seed is fixed (`SEED = 42` in `generate_data.py`).

## Data quality guarantees

- Every foreign key resolves (projects → contractors/locations, bills →
  projects/contractors, payments → bills/projects/contractors, etc.).
- `sum(payments for a bill) ≤ bill.approved_amount ≤ bill.claimed_amount`.
- Dates follow logical ordering: sanction → work order → start → bill
  work-period → submission → approval → payment → completion.
- Coordinates fall inside a plausible India bounding box and cluster
  realistically by district.
- No real personal, financial, or contact data of any kind is used —
  every name, registration number, UTR-style reference, and contact
  string is synthetically generated.

Run `python scripts/validate_data.py` any time to re-confirm all of the
above against the current `data/` folder.
