"""
NidhiGuard — Data Validation Script
Prototype Environment — Synthetic Demonstration Data.

Checks the generated CSVs for:
  - missing/duplicate primary keys
  - broken foreign keys
  - invalid or out-of-order dates
  - invalid payment/bill amount relationships
  - missing required fields
  - geographic validity (lat/lon within a plausible India bounding box)
  - presence of each planted anomaly scenario
  - existence and multi-signal completeness of the hero case, P-1023

Usage:
    python validate_data.py [--datadir ../data]
Exit code is 0 if all checks pass, 1 otherwise.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import date

REQUIRED_SIGNAL_TYPES = {
    "COST_ANOMALY", "SIMILAR_PROJECT", "CONTRACTOR_PATTERN",
    "BILLING_ANOMALY", "GEOGRAPHIC_SIGNAL", "MULTI_SIGNAL",
}

HERO_PROJECT_ID = "P-1023"
# Every one of these signal types must exist for the hero case.
HERO_REQUIRED_SIGNALS = {
    "COST_ANOMALY", "SIMILAR_PROJECT", "CONTRACTOR_PATTERN",
    "BILLING_ANOMALY", "GEOGRAPHIC_SIGNAL", "MULTI_SIGNAL",
}

# Rough India bounding box
LAT_RANGE = (6.0, 38.0)
LON_RANGE = (68.0, 98.0)

REQUIRED_FIELDS = {
    "projects.csv": ["project_id", "project_code", "project_name", "contractor_id",
                      "location_id", "sanctioned_amount", "sanction_date"],
    "contractors.csv": ["contractor_id", "contractor_name", "registration_number"],
    "bills.csv": ["bill_id", "project_id", "contractor_id", "claimed_amount", "approved_amount"],
    "payments.csv": ["payment_id", "bill_id", "project_id", "payment_amount"],
    "locations.csv": ["location_id", "project_id", "latitude", "longitude"],
    "historical_projects.csv": ["historical_project_id", "work_type", "sanctioned_amount"],
    "project_contractors.csv": ["relationship_id", "project_id", "contractor_id"],
    "anomaly_signals.csv": ["signal_id", "project_id", "signal_type"],
}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.counts = {}

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return "INVALID"


def check_required_fields(name, rows, fields, report):
    for i, row in enumerate(rows):
        for field in fields:
            if row.get(field, "") in ("", None):
                report.error(f"{name}: row {i} missing required field '{field}' (id={row.get(list(row.keys())[0])})")


def check_duplicate_ids(name, rows, id_field, report):
    seen = set()
    for row in rows:
        v = row[id_field]
        if v in seen:
            report.error(f"{name}: duplicate {id_field} '{v}'")
        seen.add(v)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datadir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    args = parser.parse_args()

    report = Report()

    files = ["projects.csv", "contractors.csv", "bills.csv", "payments.csv", "locations.csv",
             "historical_projects.csv", "project_contractors.csv", "anomaly_signals.csv"]
    data = {}
    for fn in files:
        path = os.path.join(args.datadir, fn)
        if not os.path.exists(path):
            report.error(f"MISSING FILE: {fn}")
            data[fn] = []
        else:
            data[fn] = load_csv(path)
        report.counts[fn] = len(data[fn])

    projects = data["projects.csv"]
    contractors = data["contractors.csv"]
    bills = data["bills.csv"]
    payments = data["payments.csv"]
    locations = data["locations.csv"]
    historical = data["historical_projects.csv"]
    rels = data["project_contractors.csv"]
    signals = data["anomaly_signals.csv"]

    # ---- required fields ----
    for fn, fields in REQUIRED_FIELDS.items():
        if data.get(fn):
            check_required_fields(fn, data[fn], fields, report)

    # ---- duplicate PKs ----
    check_duplicate_ids("projects.csv", projects, "project_id", report)
    check_duplicate_ids("contractors.csv", contractors, "contractor_id", report)
    check_duplicate_ids("bills.csv", bills, "bill_id", report)
    check_duplicate_ids("payments.csv", payments, "payment_id", report)
    check_duplicate_ids("locations.csv", locations, "location_id", report)
    check_duplicate_ids("historical_projects.csv", historical, "historical_project_id", report)
    check_duplicate_ids("project_contractors.csv", rels, "relationship_id", report)
    check_duplicate_ids("anomaly_signals.csv", signals, "signal_id", report)

    # ---- foreign keys ----
    contractor_ids = {c["contractor_id"] for c in contractors}
    project_ids = {p["project_id"] for p in projects}
    location_ids = {l["location_id"] for l in locations}
    bill_ids = {b["bill_id"] for b in bills}

    fk_errors = 0
    for p in projects:
        if p["contractor_id"] not in contractor_ids:
            report.error(f"projects.csv: {p['project_id']} references unknown contractor_id {p['contractor_id']}")
            fk_errors += 1
        if p["location_id"] not in location_ids:
            report.error(f"projects.csv: {p['project_id']} references unknown location_id {p['location_id']}")
            fk_errors += 1
    for b in bills:
        if b["project_id"] not in project_ids:
            report.error(f"bills.csv: {b['bill_id']} references unknown project_id {b['project_id']}")
            fk_errors += 1
        if b["contractor_id"] not in contractor_ids:
            report.error(f"bills.csv: {b['bill_id']} references unknown contractor_id {b['contractor_id']}")
            fk_errors += 1
    for pay in payments:
        if pay["bill_id"] not in bill_ids:
            report.error(f"payments.csv: {pay['payment_id']} references unknown bill_id {pay['bill_id']}")
            fk_errors += 1
        if pay["project_id"] not in project_ids:
            report.error(f"payments.csv: {pay['payment_id']} references unknown project_id {pay['project_id']}")
            fk_errors += 1
    for loc in locations:
        if loc["project_id"] not in project_ids:
            report.error(f"locations.csv: {loc['location_id']} references unknown project_id {loc['project_id']}")
            fk_errors += 1
    for r in rels:
        if r["project_id"] not in project_ids:
            report.error(f"project_contractors.csv: {r['relationship_id']} unknown project_id {r['project_id']}")
            fk_errors += 1
        if r["contractor_id"] not in contractor_ids:
            report.error(f"project_contractors.csv: {r['relationship_id']} unknown contractor_id {r['contractor_id']}")
            fk_errors += 1
    for s in signals:
        if s["project_id"] not in project_ids:
            report.error(f"anomaly_signals.csv: {s['signal_id']} references unknown project_id {s['project_id']}")
            fk_errors += 1

    # ---- bill/payment consistency: sum(payments) <= approved_amount, approved <= claimed ----
    payments_by_bill = defaultdict(list)
    for pay in payments:
        payments_by_bill[pay["bill_id"]].append(float(pay["payment_amount"]))

    amount_errors = 0
    for b in bills:
        try:
            claimed = float(b["claimed_amount"])
            approved = float(b["approved_amount"])
        except ValueError:
            report.error(f"bills.csv: {b['bill_id']} has non-numeric amount")
            amount_errors += 1
            continue
        if approved > claimed + 0.01:
            report.error(f"bills.csv: {b['bill_id']} approved_amount ({approved}) exceeds claimed_amount ({claimed})")
            amount_errors += 1
        total_paid = sum(payments_by_bill.get(b["bill_id"], []))
        if total_paid > approved + 0.01:
            report.error(f"bills.csv/payments.csv: bill {b['bill_id']} total payments ({total_paid:.2f}) "
                          f"exceed approved_amount ({approved:.2f})")
            amount_errors += 1

    # ---- date ordering ----
    date_errors = 0
    for p in projects:
        keys = ["sanction_date", "work_order_date", "start_date", "expected_completion_date"]
        parsed = [parse_date(p[k]) for k in keys]
        if any(x == "INVALID" for x in parsed):
            report.error(f"projects.csv: {p['project_id']} has an invalid date")
            date_errors += 1
            continue
        for a, b_ in zip(parsed, parsed[1:]):
            if a and b_ and a > b_:
                report.error(f"projects.csv: {p['project_id']} dates out of order ({keys})")
                date_errors += 1
                break
        actual = parse_date(p.get("actual_completion_date", ""))
        if actual and actual != "INVALID" and parsed[2] and actual < parsed[2]:
            report.error(f"projects.csv: {p['project_id']} actual_completion_date before start_date")
            date_errors += 1

    for b in bills:
        keys = ["work_period_start", "work_period_end", "submission_date", "approval_date"]
        parsed = [parse_date(b[k]) for k in keys if b.get(k)]
        for a, b_ in zip(parsed, parsed[1:]):
            if a == "INVALID" or b_ == "INVALID":
                continue
            if a and b_ and a > b_:
                report.error(f"bills.csv: {b['bill_id']} dates out of order ({keys})")
                date_errors += 1
                break

    # ---- geographic validity ----
    geo_errors = 0
    for loc in locations:
        try:
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
        except ValueError:
            report.error(f"locations.csv: {loc['location_id']} has non-numeric coordinates")
            geo_errors += 1
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            report.error(f"locations.csv: {loc['location_id']} coordinates ({lat},{lon}) outside plausible India bounding box")
            geo_errors += 1

    # ---- anomaly scenario presence ----
    present_types = {s["signal_type"] for s in signals}
    missing_types = REQUIRED_SIGNAL_TYPES - present_types
    if missing_types:
        report.error(f"anomaly_signals.csv: missing planted scenario types: {sorted(missing_types)}")

    # ---- hero case P-1023 ----
    hero_projects = [p for p in projects if p["project_id"] == HERO_PROJECT_ID]
    if not hero_projects:
        report.error(f"HERO CASE MISSING: {HERO_PROJECT_ID} not found in projects.csv")
    else:
        hero_signal_types = {s["signal_type"] for s in signals if s["project_id"] == HERO_PROJECT_ID}
        missing_hero = HERO_REQUIRED_SIGNALS - hero_signal_types
        if missing_hero:
            report.error(f"HERO CASE INCOMPLETE: {HERO_PROJECT_ID} missing signal types {sorted(missing_hero)}")

    # ---- data distribution sanity ----
    anomalous_project_ids = {s["project_id"] for s in signals if s["signal_type"] != "MULTI_SIGNAL"}
    multi_signal_ids = {s["project_id"] for s in signals if s["signal_type"] == "MULTI_SIGNAL"}
    normal_count = len(project_ids) - len(anomalous_project_ids | multi_signal_ids)
    pct_normal = 100 * normal_count / max(1, len(project_ids))
    if pct_normal < 55:
        report.warn(f"Normal-project share is {pct_normal:.1f}% — lower than the ~70-80% target.")

    # ---- summary ----
    print("=" * 60)
    print("NidhiGuard — DATA VALIDATION" + (" PASSED" if not report.errors else " FAILED"))
    print("Prototype Environment — Synthetic Demonstration Data")
    print("=" * 60)
    print(f"Projects:            {report.counts.get('projects.csv', 0)}")
    print(f"Contractors:         {report.counts.get('contractors.csv', 0)}")
    print(f"Bills:               {report.counts.get('bills.csv', 0)}")
    print(f"Payments:            {report.counts.get('payments.csv', 0)}")
    print(f"Locations:           {report.counts.get('locations.csv', 0)}")
    print(f"Historical Projects: {report.counts.get('historical_projects.csv', 0)}")
    print(f"Relationships:       {report.counts.get('project_contractors.csv', 0)}")
    print(f"Anomaly signals:     {report.counts.get('anomaly_signals.csv', 0)}")
    print("-" * 60)
    print(f"Foreign-key errors:   {fk_errors}")
    print(f"Amount errors:        {amount_errors}")
    print(f"Date-ordering errors: {date_errors}")
    print(f"Geographic errors:    {geo_errors}")
    print(f"Normal-project share: {pct_normal:.1f}%")
    print(f"Hero case ({HERO_PROJECT_ID}) present: {'YES' if hero_projects else 'NO'}")
    if hero_projects:
        print(f"Hero case signal types: {sorted({s['signal_type'] for s in signals if s['project_id'] == HERO_PROJECT_ID})}")
    print("-" * 60)
    print(f"Total errors:   {len(report.errors)}")
    print(f"Total warnings: {len(report.warnings)}")
    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")
    if report.errors:
        print("\nFirst 25 errors:")
        for e in report.errors[:25]:
            print(f"  - {e}")
        if len(report.errors) > 25:
            print(f"  ... and {len(report.errors) - 25} more")
    print("=" * 60)

    sys.exit(0 if not report.errors else 1)


if __name__ == "__main__":
    main()
