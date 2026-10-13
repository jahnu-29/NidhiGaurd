"""
NidhiGuard — Synthetic Data Generator
Prototype Environment — Synthetic Demonstration Data.

Deterministic (SEED = 42): re-running this script produces an identical
dataset. This generator constructs the anomaly stories FIRST, then fills
in the normal population around them, per the project brief.

Usage:
    python generate_data.py [--outdir ../data]
"""
import argparse
import csv
import math
import os
import random
from datetime import date, timedelta

SEED = 42
random.seed(SEED)

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

STATE_DISTRICTS = {
    "Tamil Nadu": [("Chennai", 13.08, 80.27), ("Coimbatore", 11.02, 76.96), ("Madurai", 9.93, 78.12)],
    "Karnataka": [("Bengaluru Urban", 12.97, 77.59), ("Mysuru", 12.30, 76.64), ("Belagavi", 15.85, 74.50)],
    "Maharashtra": [("Pune", 18.52, 73.86), ("Nagpur", 21.15, 79.09), ("Nashik", 20.00, 73.79)],
    "Uttar Pradesh": [("Lucknow", 26.85, 80.95), ("Varanasi", 25.32, 82.97), ("Kanpur Nagar", 26.45, 80.33)],
    "Bihar": [("Patna", 25.59, 85.14), ("Gaya", 24.80, 85.00), ("Bhagalpur", 25.25, 86.99)],
    "West Bengal": [("Kolkata", 22.57, 88.36), ("Howrah", 22.59, 88.31), ("Darjeeling", 27.04, 88.26)],
    "Rajasthan": [("Jaipur", 26.91, 75.79), ("Jodhpur", 26.29, 73.02), ("Udaipur", 24.58, 73.68)],
    "Madhya Pradesh": [("Bhopal", 23.26, 77.41), ("Indore", 22.72, 75.86), ("Gwalior", 26.22, 78.18)],
    "Odisha": [("Khordha", 20.30, 85.82), ("Cuttack", 20.46, 85.88), ("Puri", 19.81, 85.83)],
    "Kerala": [("Thiruvananthapuram", 8.52, 76.94), ("Ernakulam", 9.98, 76.30), ("Kozhikode", 11.26, 75.78)],
}

DISTRICT_LIST = []  # (idx, state, district, lat, lon)
_idx = 1
for _state, _dists in STATE_DISTRICTS.items():
    for _d, _lat, _lon in _dists:
        DISTRICT_LIST.append({
            "idx": _idx, "state": _state, "district": _d, "lat": _lat, "lon": _lon,
            "district_id": f"DIST-{_idx:02d}", "mp_id": f"MP-{_idx:02d}",
            "constituency_id": f"CONST-{_idx:02d}",
        })
        _idx += 1

WORK_TYPES = {
    # work_type: (category, base_cost_lakh_min, base_cost_lakh_max, unit_label, description_templates)
    "Concrete Road": ("Road Infrastructure", 16, 22, "km", [
        "Construction of Concrete Road at {loc}",
        "Laying of CC Road connecting {loc} to main road",
        "Upgradation of internal road at {loc} to concrete standard",
    ]),
    "Bitumen Road": ("Road Infrastructure", 10, 16, "km", [
        "Bituminous road improvement at {loc}",
        "Black-topping of road stretch in {loc}",
    ]),
    "Hand Pump Installation": ("Drinking Water", 2, 4, "unit", [
        "Installation of hand pump at {loc}",
        "Provision of drinking water hand pump, {loc}",
    ]),
    "Overhead Water Tank": ("Drinking Water", 12, 18, "unit", [
        "Construction of overhead water tank at {loc}",
        "Drinking water storage tank facility, {loc}",
    ]),
    "Classroom Block": ("Education Infrastructure", 20, 28, "unit", [
        "Construction of additional classroom block at Govt School, {loc}",
        "Extension of school building, {loc}",
    ]),
    "Community Hall": ("Community Infrastructure", 15, 22, "unit", [
        "Construction of community hall at {loc}",
        "Building of multipurpose community centre, {loc}",
    ]),
    "Drainage System": ("Sanitation Infrastructure", 9, 15, "unit", [
        "Construction of pucca drainage at {loc}",
        "Storm water drain improvement work, {loc}",
    ]),
    "Street Lighting": ("Public Infrastructure", 4, 8, "unit", [
        "Installation of solar street lights at {loc}",
        "Street lighting improvement work, {loc}",
    ]),
    "Health Sub-Centre Upgrade": ("Health Infrastructure", 18, 26, "unit", [
        "Upgradation of health sub-centre at {loc}",
        "Renovation and equipment support, PHC {loc}",
    ]),
}
WORK_TYPE_NAMES = list(WORK_TYPES.keys())

STATE_CODES = {
    "Tamil Nadu": "TN", "Karnataka": "KA", "Maharashtra": "MH", "Uttar Pradesh": "UP",
    "Bihar": "BR", "West Bengal": "WB", "Rajasthan": "RJ", "Madhya Pradesh": "MP",
    "Odisha": "OD", "Kerala": "KL",
}

BLOCK_NAMES = ["Anaikatti", "Ramnagar", "Sultanpet", "Vellalore", "Kinathukadavu", "Perur",
               "Sathyamangalam", "Modakurichi", "Bhavani", "Gobichettipalayam", "Ward 5", "Ward 9",
               "Ward 12", "Ward 14", "Ward 17", "Panchayat North", "Panchayat South"]
VILLAGE_NAMES = ["Keezhapalayam", "Melapalayam", "Sundarapuram", "Nallur", "Kondampatti",
                  "Periyanaickenpalayam", "Alandurai", "Karamadai", "Thondamuthur", "Vadavalli",
                  "Ganapathy", "Saravanampatti"]

CONTRACTOR_TYPES = ["Individual Proprietor", "Partnership Firm", "Pvt Ltd", "Public Works Cooperative"]

AGENCIES = [f"AGENCY-{i:02d}" for i in range(1, 13)]

APPROVING_AUTHORITIES = ["District Program Officer", "District Rural Development Agency",
                          "Executive Engineer (PWD)", "Assistant Engineer, PWD",
                          "District Collector Office"]

PAYMENT_MODES = ["PFMS Transfer", "RTGS", "Cheque"]

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def d(y, m, day):
    return date(y, m, day)

def add_days(dt, n):
    return dt + timedelta(days=n)

def rand_date_between(start, end):
    span = (end - start).days
    if span <= 0:
        return start
    return add_days(start, random.randint(0, span))

def jitter_coord(lat, lon, km=3.0):
    # ~1 deg lat ~ 111 km
    dlat = (random.uniform(-km, km)) / 111.0
    dlon = (random.uniform(-km, km)) / (111.0 * math.cos(math.radians(lat)) if lat else 111.0)
    return round(lat + dlat, 5), round(lon + dlon, 5)

def lakh(x):
    return round(x * 100000, 2)

def money_variation(base_lakh, pct=0.08):
    return base_lakh * random.uniform(1 - pct, 1 + pct)

def fmt_date(dt):
    return dt.isoformat() if dt else ""


class IdCounter:
    def __init__(self, prefix, width, start=1):
        self.prefix = prefix
        self.width = width
        self.n = start

    def next(self):
        v = f"{self.prefix}-{self.n:0{self.width}d}"
        self.n += 1
        return v


# --------------------------------------------------------------------------
# Contractors
# --------------------------------------------------------------------------

FIRST_TOKENS = ["Shree", "Balaji", "Om", "Sri", "National", "United", "Modern", "Prime", "Sun",
                "Metro", "Vishwa", "Ganga", "Bharat", "Classic", "Elite", "Regal", "Anand", "Vinayaga"]
MID_TOKENS = ["Infra", "Infrastructure", "Construction", "Builders", "Engineering", "Roadways",
              "Contractors", "Projects", "Works"]
SUFFIXES = ["Pvt Ltd", "Private Limited", "& Co", "Enterprises", "Associates"]


def make_contractor_name():
    return f"{random.choice(FIRST_TOKENS)} {random.choice(MID_TOKENS)} {random.choice(SUFFIXES)}"


def name_variant(base_name):
    """Produce a plausible alternate rendering of the same contractor name."""
    variants = [base_name]
    v = base_name
    v = v.replace("Infrastructure", "Infra").replace("Private Limited", "Pvt. Ltd.")
    v = v.replace("Pvt Ltd", "Pvt. Ltd.")
    variants.append(v)
    variants.append(base_name.upper())
    return random.choice([x for x in variants if x != base_name] or [base_name])


def generate_contractors(n_contractors):
    contractors = []
    cid = IdCounter("C", 3)
    for i in range(n_contractors):
        dist = random.choice(DISTRICT_LIST)
        base_name = make_contractor_name()
        # ~12% of contractors get a name-variant flavour noted for entity resolution
        display_name = base_name
        reg_date = rand_date_between(d(2008, 1, 1), d(2020, 12, 31))
        contractors.append({
            "contractor_id": cid.next(),
            "contractor_name": display_name,
            "_base_name": base_name,
            "registration_number": f"REG-{dist['state'][:2].upper()}-{random.randint(10000,99999)}",
            "contractor_type": random.choice(CONTRACTOR_TYPES),
            "district": dist["district"],
            "state": dist["state"],
            "registration_date": fmt_date(reg_date),
            "active_status": "Active" if random.random() > 0.06 else "Inactive",
            "contact_reference": f"CONTACT-{cid.n-1:03d}",
        })
    # apply a few explicit name-variant siblings (does NOT create new contractor_ids;
    # it just demonstrates that contractor_name text can vary while the ID is stable)
    for c in random.sample(contractors, k=max(1, n_contractors // 10)):
        c["contractor_name"] = name_variant(c["_base_name"])
    for c in contractors:
        del c["_base_name"]
    return contractors


# --------------------------------------------------------------------------
# Project spec construction (anomaly stories planted FIRST)
# --------------------------------------------------------------------------

def build_location_name():
    return f"{random.choice(VILLAGE_NAMES)}"


def make_description(work_type, loc_name):
    tmpl = random.choice(WORK_TYPES[work_type][4])
    return tmpl.format(loc=loc_name)


def new_spec(work_type, district, size_bucket="medium", cost_multiplier=1.0,
             contractor_id=None, tags=None, cluster_id=None, loc_name=None,
             base_year=2023):
    category, cmin, cmax, unit, _ = WORK_TYPES[work_type]
    base = random.uniform(cmin, cmax)
    size_mult = {"small": 0.65, "medium": 1.0, "large": 1.55}[size_bucket]
    sanctioned_lakh = money_variation(base * size_mult, pct=0.07) * cost_multiplier
    loc_name = loc_name or build_location_name()
    return {
        "work_type": work_type,
        "category": category,
        "district": district,
        "loc_name": loc_name,
        "sanctioned_amount": lakh(sanctioned_lakh),
        "contractor_id": contractor_id,
        "tags": tags or [],
        "cluster_id": cluster_id,
        "description": make_description(work_type, loc_name),
        "base_year": base_year,
        "billing_profile": "normal",
        "size_bucket": size_bucket,
    }


def plan_all_specs(n_projects, contractors):
    """
    Build a flat list of project 'specs' (dicts) of length n_projects,
    in the exact order they will receive sequential project_ids
    (P-1001 .. P-1000+n). Index 22 (0-based) => P-1023, reserved for the
    hero multi-signal case.
    """
    specs = [None] * n_projects
    contractor_ids = [c["contractor_id"] for c in contractors]

    def free_slots(exclude=None):
        exclude = exclude or set()
        return [i for i in range(n_projects) if specs[i] is None and i not in exclude]

    HERO_INDEX = 22  # -> P-1023

    # ---- Pick a "pattern contractor" for Scenario 4 / hero ----
    pattern_contractor = random.choice(contractor_ids)
    other_contractors = [c for c in contractor_ids if c != pattern_contractor]

    # ---- HERO CASE: P-1023 -------------------------------------------------
    hero_district = DISTRICT_LIST[3]  # fixed pick: 4th district in the reference list
    hero_work_type = "Concrete Road"
    hero_loc = "Ward 14"
    hero_spec = new_spec(hero_work_type, hero_district["district"], size_bucket="medium",
                          cost_multiplier=1.72, contractor_id=pattern_contractor,
                          tags=["COST_ANOMALY", "SIMILAR_PROJECT", "CONTRACTOR_PATTERN",
                                "BILLING_ANOMALY", "GEOGRAPHIC_SIGNAL", "MULTI_SIGNAL", "HERO"],
                          cluster_id="CLUSTER-HERO", loc_name=hero_loc)
    hero_spec["project_name"] = "Construction of Concrete Road – Ward 14"
    hero_spec["billing_profile"] = "compressed"
    specs[HERO_INDEX] = hero_spec

    # sibling "comparable" projects for the hero's cost cluster (normal cost)
    cost_cluster_slots = random.sample(free_slots(), 5)
    for s in cost_cluster_slots:
        specs[s] = new_spec(hero_work_type, hero_district["district"], size_bucket="medium",
                             contractor_id=random.choice(other_contractors),
                             cluster_id="CLUSTER-HERO-COST")

    # similar/duplicate siblings for the hero (Scenario 3, tied into hero).
    # Same village as the hero -> also a genuine geographic signal, so these
    # are deliberately correlated (multi-signal) rather than single-signal.
    sim_slots = random.sample(free_slots(), 2)
    for s in sim_slots:
        specs[s] = new_spec(hero_work_type, hero_district["district"], size_bucket="medium",
                             cost_multiplier=random.uniform(0.95, 1.08),
                             contractor_id=random.choice(other_contractors + [pattern_contractor]),
                             tags=["SIMILAR_PROJECT", "GEOGRAPHIC_SIGNAL"], cluster_id="CLUSTER-HERO-SIM",
                             loc_name=hero_loc)
        specs[s]["description"] = make_description(hero_work_type, hero_loc)

    # contractor-pattern siblings: same pattern_contractor, closely awarded, higher
    # cost -> the elevated cost_multiplier also earns these a cost-anomaly tag,
    # making them a correlated (multi-signal) group rather than single-signal.
    pattern_slots = random.sample(free_slots(), 3)
    for s in pattern_slots:
        wt = random.choice(["Concrete Road", "Bitumen Road"])
        specs[s] = new_spec(wt, hero_district["district"], size_bucket="medium",
                             cost_multiplier=random.uniform(1.25, 1.4),
                             contractor_id=pattern_contractor,
                             tags=["CONTRACTOR_PATTERN", "COST_ANOMALY"], cluster_id="CLUSTER-HERO-CONTRACTOR")
    # a handful of ORDINARY projects also from the pattern contractor (majority normal)
    pattern_normal_slots = random.sample(free_slots(), 5)
    for s in pattern_normal_slots:
        wt = random.choice(WORK_TYPE_NAMES)
        dist = random.choice(DISTRICT_LIST)["district"]
        specs[s] = new_spec(wt, dist, size_bucket=random.choice(["small", "medium"]),
                             contractor_id=pattern_contractor)

    # geographic-signal cluster around the hero's location (mostly benign)
    geo_slots = random.sample(free_slots(), 4)
    for s in geo_slots:
        wt = random.choice(["Drainage System", "Street Lighting", hero_work_type])
        specs[s] = new_spec(wt, hero_district["district"], size_bucket="small",
                             contractor_id=random.choice(contractor_ids),
                             tags=["GEOGRAPHIC_SIGNAL"] if wt == hero_work_type else [],
                             cluster_id="CLUSTER-HERO-GEO", loc_name=hero_loc)

    # ---- Scenario 2: standalone cost anomalies (not the hero) --------------
    n_cost_anom = max(4, n_projects // 25)
    for _ in range(n_cost_anom):
        s = random.choice(free_slots())
        wt = random.choice(WORK_TYPE_NAMES)
        dist = random.choice(DISTRICT_LIST)["district"]
        cluster_id = f"CLUSTER-COST-{s}"
        specs[s] = new_spec(wt, dist, size_bucket="medium", cost_multiplier=random.uniform(1.5, 1.8),
                             contractor_id=random.choice(contractor_ids),
                             tags=["COST_ANOMALY"], cluster_id=cluster_id)
        # comparable siblings so the anomaly is statistically visible
        sib_slots = random.sample(free_slots(exclude={s}), 4)
        for ss in sib_slots:
            specs[ss] = new_spec(wt, dist, size_bucket="medium", contractor_id=random.choice(contractor_ids),
                                  cluster_id=cluster_id)

    # ---- Scenario 3: standalone similar/duplicate clusters -----------------
    # Same village + close sanction timing also constitutes a mild geographic
    # signal, so roughly half of these clusters are tagged as correlated
    # (SIMILAR_PROJECT + GEOGRAPHIC_SIGNAL); the rest stay single-signal.
    n_dup_clusters = max(3, n_projects // 35)
    for k in range(n_dup_clusters):
        wt = random.choice(WORK_TYPE_NAMES)
        dist_info = random.choice(DISTRICT_LIST)
        loc_name = build_location_name()
        cluster_id = f"CLUSTER-DUP-{k}"
        also_geo = (k % 2 == 0)
        tags = ["SIMILAR_PROJECT", "GEOGRAPHIC_SIGNAL"] if also_geo else ["SIMILAR_PROJECT"]
        slots = random.sample(free_slots(), random.choice([2, 3]))
        for s in slots:
            specs[s] = new_spec(wt, dist_info["district"], size_bucket="medium",
                                 cost_multiplier=random.uniform(0.95, 1.08),
                                 contractor_id=random.choice(contractor_ids),
                                 tags=list(tags), cluster_id=cluster_id, loc_name=loc_name)
            specs[s]["description"] = make_description(wt, loc_name)

    # ---- Scenario 4: standalone contractor-pattern contractor --------------
    # Elevated cost_multiplier again earns a correlated COST_ANOMALY tag.
    pattern_contractor_2 = random.choice([c for c in other_contractors])
    pat_slots = random.sample(free_slots(), 3)
    for s in pat_slots:
        wt = random.choice(["Classroom Block", "Community Hall"])
        dist = random.choice(DISTRICT_LIST)["district"]
        specs[s] = new_spec(wt, dist, size_bucket="medium", cost_multiplier=random.uniform(1.2, 1.35),
                             contractor_id=pattern_contractor_2,
                             tags=["CONTRACTOR_PATTERN", "COST_ANOMALY"], cluster_id="CLUSTER-PATTERN2")
    pat_slots_normal = random.sample(free_slots(), 6)
    for s in pat_slots_normal:
        wt = random.choice(WORK_TYPE_NAMES)
        dist = random.choice(DISTRICT_LIST)["district"]
        specs[s] = new_spec(wt, dist, size_bucket=random.choice(["small", "medium"]),
                             contractor_id=pattern_contractor_2)

    # ---- Scenario 5: standalone billing-anomaly projects --------------------
    n_billing = max(4, n_projects // 25)
    for _ in range(n_billing):
        s = random.choice(free_slots())
        wt = random.choice(WORK_TYPE_NAMES)
        dist = random.choice(DISTRICT_LIST)["district"]
        specs[s] = new_spec(wt, dist, size_bucket="medium", contractor_id=random.choice(contractor_ids),
                             tags=["BILLING_ANOMALY"])
        specs[s]["billing_profile"] = "compressed"

    # ---- Scenario 6: standalone geographic cluster --------------------------
    geo_dist = random.choice(DISTRICT_LIST)
    geo_loc = build_location_name()
    geo_slots2 = random.sample(free_slots(), 5)
    shared_contractor = random.choice(contractor_ids)
    for i, s in enumerate(geo_slots2):
        wt = random.choice(WORK_TYPE_NAMES)
        suspicious = i < 2
        specs[s] = new_spec(wt if not suspicious else "Drainage System", geo_dist["district"],
                             size_bucket="small",
                             cost_multiplier=random.uniform(1.1, 1.2) if suspicious else 1.0,
                             contractor_id=shared_contractor if suspicious else random.choice(contractor_ids),
                             tags=["GEOGRAPHIC_SIGNAL"] if suspicious else [],
                             cluster_id="CLUSTER-GEO2", loc_name=geo_loc)

    # ---- Fill remaining slots with plain normal projects --------------------
    for s in free_slots():
        wt = random.choice(WORK_TYPE_NAMES)
        dist = random.choice(DISTRICT_LIST)["district"]
        specs[s] = new_spec(wt, dist, size_bucket=random.choice(["small", "medium", "large"]),
                             contractor_id=random.choice(contractor_ids))

    return specs, pattern_contractor, hero_district


# --------------------------------------------------------------------------
# Materialize projects / locations / bills / payments from specs
# --------------------------------------------------------------------------

def district_lookup(name):
    for d_ in DISTRICT_LIST:
        if d_["district"] == name:
            return d_
    return DISTRICT_LIST[0]


def build_projects_and_children(specs, contractors_by_id):
    projects, locations, bills, payments, rels = [], [], [], [], []
    pid_ctr = 1001
    loc_ctr = IdCounter("L", 4)
    bill_ctr = IdCounter("B", 5)
    pay_ctr = IdCounter("PAY", 5)
    rel_ctr = IdCounter("REL", 4)
    code_seq = {}

    for spec in specs:
        pid = f"P-{pid_ctr}"
        pid_ctr += 1
        dinfo = district_lookup(spec["district"])
        state = dinfo["state"]

        # ---- dates ----
        sanction_year = spec.get("base_year", 2023)
        sanction_date = rand_date_between(d(sanction_year, 1, 1), d(sanction_year, 9, 30))
        work_order_date = add_days(sanction_date, random.randint(10, 40))
        start_date = add_days(work_order_date, random.randint(5, 25))
        # duration depends on work type roughly
        duration_days = random.randint(90, 270)
        expected_completion = add_days(start_date, duration_days)

        completion_pct = random.choice([100, 100, 100, 90, 75, 60, 40, 20]) if "HERO" not in spec["tags"] else 100
        status = "Completed" if completion_pct == 100 else ("Delayed" if random.random() < 0.3 else "In Progress")
        actual_completion = None
        if status == "Completed":
            actual_completion = add_days(expected_completion, random.randint(-10, 35))

        sanctioned = spec["sanctioned_amount"]
        estimated = round(sanctioned * random.uniform(0.97, 1.0), 2)
        approved = round(sanctioned * random.uniform(0.98, 1.0), 2)
        expenditure_ratio = completion_pct / 100.0
        actual_expenditure = round(approved * expenditure_ratio * random.uniform(0.97, 1.0), 2)

        contractor_id = spec["contractor_id"]

        # ---- location ----
        lat, lon = jitter_coord(dinfo["lat"], dinfo["lon"], km=4.0)
        loc_id = loc_ctr.next()
        pincode_base = 600000 + dinfo["idx"] * 137
        locations.append({
            "location_id": loc_id, "project_id": pid, "state": state, "district": spec["district"],
            "constituency": dinfo["constituency_id"], "block": random.choice(BLOCK_NAMES),
            "village_or_ward": spec["loc_name"], "latitude": lat, "longitude": lon,
            "pincode": str(pincode_base + random.randint(0, 99)),
            "location_type": random.choice(["Rural Village", "Panchayat", "Urban Ward"]),
        })

        code_seq.setdefault(state, 0)
        code_seq[state] += 1
        state_code = STATE_CODES.get(state, state[:2].upper())
        project_code = f"MPLADS/{state_code}/{sanction_year}/{code_seq[state]:04d}"

        project_name = spec.get("project_name", spec["description"][:60])

        projects.append({
            "project_id": pid, "project_code": project_code, "project_name": project_name,
            "project_description": spec["description"], "project_category": spec["category"],
            "work_type": spec["work_type"], "mp_id": dinfo["mp_id"], "constituency_id": dinfo["constituency_id"],
            "district_id": dinfo["district_id"], "state": state,
            "implementing_agency_id": random.choice(AGENCIES), "contractor_id": contractor_id,
            "location_id": loc_id, "sanctioned_amount": sanctioned, "estimated_cost": estimated,
            "approved_amount": approved, "actual_expenditure": actual_expenditure,
            "project_status": status, "sanction_date": fmt_date(sanction_date),
            "work_order_date": fmt_date(work_order_date), "start_date": fmt_date(start_date),
            "expected_completion_date": fmt_date(expected_completion),
            "actual_completion_date": fmt_date(actual_completion) if actual_completion else "",
            "completion_percentage": completion_pct, "created_date": fmt_date(sanction_date),
            "_tags": spec["tags"], "_cluster_id": spec.get("cluster_id"),
            "_billing_profile": spec.get("billing_profile", "normal"),
            "_size_bucket": spec.get("size_bucket"),
        })

        rels.append({
            "relationship_id": rel_ctr.next(), "project_id": pid, "contractor_id": contractor_id,
            "role": "Primary Contractor", "contract_value": sanctioned, "award_date": fmt_date(work_order_date),
        })

        # ---- bills & payments ----
        n_bills = random.choice([3, 4, 4, 5, 6])
        window_end = actual_completion or min(expected_completion, add_days(start_date, int(duration_days * expenditure_ratio) + 10))
        window_end = max(window_end, add_days(start_date, 20))

        if spec.get("billing_profile") == "compressed":
            # several bills bunched close together late in the project, big final claim
            n_bills = random.choice([4, 5])
            cluster_start = add_days(window_end, -random.randint(10, 18))
            bill_dates = sorted(add_days(cluster_start, random.randint(0, 12)) for _ in range(n_bills))
            bill_dates[0] = add_days(start_date, random.randint(15, 30))  # keep one early bill for realism
            bill_dates = sorted(bill_dates)
            weights = [0.12] * (n_bills - 1) + [0.0]
            weights[-1] = 1 - sum(weights[:-1])  # big final claim
        else:
            bill_dates = sorted(rand_date_between(add_days(start_date, 10), window_end) for _ in range(n_bills))
            raw = [random.uniform(0.6, 1.4) for _ in range(n_bills)]
            s = sum(raw)
            weights = [r / s for r in raw]

        remaining_claimable = actual_expenditure if actual_expenditure > 0 else approved * 0.1
        running_total = 0
        for i, bdate in enumerate(bill_dates):
            claimed = round(remaining_claimable * weights[i], 2)
            approved_amt = round(claimed * random.uniform(0.95, 1.0), 2)
            work_start = add_days(bdate, -random.randint(15, 45))
            work_end = add_days(bdate, -random.randint(0, 3))
            submission = add_days(bdate, random.randint(0, 3))
            approval = add_days(submission, random.randint(3, 15))
            bill_status = "Approved"
            bill_type = "Advance" if i == 0 and spec.get("billing_profile") != "compressed" else (
                "Final" if i == len(bill_dates) - 1 and status == "Completed" else "Running Account (RA)")
            bill_id = bill_ctr.next()
            bills.append({
                "bill_id": bill_id, "project_id": pid, "contractor_id": contractor_id,
                "bill_number": f"BILL/{bdate.year}/{bill_ctr.n-1:04d}", "bill_date": fmt_date(bdate),
                "bill_type": bill_type, "claimed_amount": claimed, "approved_amount": approved_amt,
                "bill_status": bill_status, "work_period_start": fmt_date(work_start),
                "work_period_end": fmt_date(work_end), "submission_date": fmt_date(submission),
                "approval_date": fmt_date(approval),
            })
            # payments: usually one payment per bill, occasionally split into two
            n_pay = 1 if random.random() > 0.12 else 2
            pay_amounts = []
            if n_pay == 1:
                pay_amounts = [approved_amt]
            else:
                first = round(approved_amt * random.uniform(0.4, 0.6), 2)
                pay_amounts = [first, round(approved_amt - first, 2)]
            pay_date_cursor = approval
            for amt in pay_amounts:
                pay_date_cursor = add_days(pay_date_cursor, random.randint(2, 10))
                payments.append({
                    "payment_id": pay_ctr.next(), "bill_id": bill_id, "project_id": pid,
                    "contractor_id": contractor_id, "payment_date": fmt_date(pay_date_cursor),
                    "payment_reference": f"UTR-SIM-{pay_ctr.n-1:06d}", "payment_amount": amt,
                    "payment_mode": random.choice(PAYMENT_MODES), "payment_status": "Success",
                    "approving_authority": random.choice(APPROVING_AUTHORITIES),
                })

    return projects, locations, bills, payments, rels


# --------------------------------------------------------------------------
# Historical projects (comparable baseline pool)
# --------------------------------------------------------------------------

def build_historical_projects(n_hist, contractors):
    hist = []
    hid_ctr = IdCounter("H", 4)
    contractor_ids = [c["contractor_id"] for c in contractors]
    for _ in range(n_hist):
        wt = random.choice(WORK_TYPE_NAMES)
        category, cmin, cmax, unit, _ = WORK_TYPES[wt]
        dinfo = random.choice(DISTRICT_LIST)
        size_bucket = random.choice(["small", "medium", "medium", "large"])
        size_mult = {"small": 0.65, "medium": 1.0, "large": 1.55}[size_bucket]
        sanctioned = lakh(money_variation(random.uniform(cmin, cmax) * size_mult, pct=0.10))
        expenditure = round(sanctioned * random.uniform(0.9, 1.0), 2)
        completion = rand_date_between(d(2018, 1, 1), d(2022, 12, 31))
        lat, lon = jitter_coord(dinfo["lat"], dinfo["lon"], km=5.0)
        loc_name = build_location_name()
        hist.append({
            "historical_project_id": hid_ctr.next(),
            "project_description": make_description(wt, loc_name),
            "project_category": category, "work_type": wt, "state": dinfo["state"],
            "district": dinfo["district"], "constituency": dinfo["constituency_id"],
            "latitude": lat, "longitude": lon, "sanctioned_amount": sanctioned,
            "actual_expenditure": expenditure, "completion_date": fmt_date(completion),
            "contractor_id": random.choice(contractor_ids),
            "implementing_agency_id": random.choice(AGENCIES),
        })
    return hist


# --------------------------------------------------------------------------
# Anomaly signal ground-truth rows
# --------------------------------------------------------------------------

def build_anomaly_signals(projects):
    signals = []
    sid_ctr = IdCounter("SIG", 3)
    by_cluster = {}
    for p in projects:
        cid = p.get("_cluster_id")
        if cid:
            by_cluster.setdefault(cid, []).append(p["project_id"])

    for p in projects:
        tags = p.get("_tags", [])
        if not tags:
            continue
        is_hero = "HERO" in tags
        for tag in tags:
            if tag in ("HERO",):
                continue
            severity = "HIGH" if is_hero else random.choice(["MEDIUM", "HIGH"])
            related = ""
            explanation = ""
            if tag == "COST_ANOMALY":
                related = p.get("_cluster_id", "")
                explanation = ("Sanctioned amount for this project sits well above the cost "
                               "distribution of comparable projects sharing its work type and "
                               "district — flagged as an elevated cost risk pattern requiring review.")
            elif tag == "SIMILAR_PROJECT":
                siblings = [x for x in by_cluster.get(p.get("_cluster_id"), []) if x != p["project_id"]]
                related = ";".join(siblings)
                explanation = ("Project description, work type, timing, and location closely match "
                               "one or more other sanctioned projects — an unusual relationship that "
                               "may indicate overlapping or duplicated works requiring review.")
            elif tag == "CONTRACTOR_PATTERN":
                related = p["contractor_id"]
                explanation = ("This project is part of a cluster of closely-awarded, "
                               "similarly-typed, higher-cost projects connected to the same "
                               "contractor — an unusual concentration pattern requiring review.")
            elif tag == "BILLING_ANOMALY":
                related = p["project_id"]
                explanation = ("Bills on this project were raised in an unusually compressed "
                               "sequence, with a disproportionate claim concentrated near "
                               "completion — a billing timing pattern requiring review.")
            elif tag == "GEOGRAPHIC_SIGNAL":
                related = p.get("_cluster_id", "")
                explanation = ("This project sits within a tight geographic cluster that also "
                               "shares cost and/or contractor attributes with nearby projects — "
                               "a geographic relationship pattern requiring review.")
            elif tag == "MULTI_SIGNAL":
                related = p["project_id"]
                explanation = ("Multiple independent risk signals (cost, similarity, contractor "
                               "pattern, billing, geography) converge on this single project — "
                               "recommended as a priority investigation candidate.")
            else:
                continue
            signals.append({
                "signal_id": sid_ctr.next(), "project_id": p["project_id"], "signal_type": tag,
                "severity": severity, "expected_reason": tag.replace("_", " ").title(),
                "related_entity_id": related, "planted_for_testing": True,
                "explanation": explanation,
            })
    return signals


# --------------------------------------------------------------------------
# CSV writer
# --------------------------------------------------------------------------

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    parser.add_argument("--n_projects", type=int, default=200)
    parser.add_argument("--n_contractors", type=int, default=75)
    parser.add_argument("--n_historical", type=int, default=500)
    args = parser.parse_args()

    random.seed(SEED)  # re-seed at the top of main so re-running is deterministic

    contractors = generate_contractors(args.n_contractors)
    contractors_by_id = {c["contractor_id"]: c for c in contractors}

    specs, pattern_contractor, hero_district = plan_all_specs(args.n_projects, contractors)
    projects, locations, bills, payments, rels = build_projects_and_children(specs, contractors_by_id)

    # derive contractor totals
    proj_count = {}
    proj_value = {}
    for p in projects:
        proj_count[p["contractor_id"]] = proj_count.get(p["contractor_id"], 0) + 1
        proj_value[p["contractor_id"]] = proj_value.get(p["contractor_id"], 0) + p["sanctioned_amount"]
    for c in contractors:
        c["total_projects"] = proj_count.get(c["contractor_id"], 0)
        c["total_project_value"] = round(proj_value.get(c["contractor_id"], 0), 2)

    historical = build_historical_projects(args.n_historical, contractors)
    signals = build_anomaly_signals(projects)

    os.makedirs(args.outdir, exist_ok=True)

    project_fields = ["project_id", "project_code", "project_name", "project_description",
                       "project_category", "work_type", "mp_id", "constituency_id", "district_id",
                       "state", "implementing_agency_id", "contractor_id", "location_id",
                       "sanctioned_amount", "estimated_cost", "approved_amount", "actual_expenditure",
                       "project_status", "sanction_date", "work_order_date", "start_date",
                       "expected_completion_date", "actual_completion_date", "completion_percentage",
                       "created_date"]
    write_csv(os.path.join(args.outdir, "projects.csv"), projects, project_fields)

    contractor_fields = ["contractor_id", "contractor_name", "registration_number", "contractor_type",
                          "district", "state", "registration_date", "active_status", "total_projects",
                          "total_project_value", "contact_reference"]
    write_csv(os.path.join(args.outdir, "contractors.csv"), contractors, contractor_fields)

    bill_fields = ["bill_id", "project_id", "contractor_id", "bill_number", "bill_date", "bill_type",
                   "claimed_amount", "approved_amount", "bill_status", "work_period_start",
                   "work_period_end", "submission_date", "approval_date"]
    write_csv(os.path.join(args.outdir, "bills.csv"), bills, bill_fields)

    payment_fields = ["payment_id", "bill_id", "project_id", "contractor_id", "payment_date",
                       "payment_reference", "payment_amount", "payment_mode", "payment_status",
                       "approving_authority"]
    write_csv(os.path.join(args.outdir, "payments.csv"), payments, payment_fields)

    location_fields = ["location_id", "project_id", "state", "district", "constituency", "block",
                        "village_or_ward", "latitude", "longitude", "pincode", "location_type"]
    write_csv(os.path.join(args.outdir, "locations.csv"), locations, location_fields)

    hist_fields = ["historical_project_id", "project_description", "project_category", "work_type",
                   "state", "district", "constituency", "latitude", "longitude", "sanctioned_amount",
                   "actual_expenditure", "completion_date", "contractor_id", "implementing_agency_id"]
    write_csv(os.path.join(args.outdir, "historical_projects.csv"), historical, hist_fields)

    rel_fields = ["relationship_id", "project_id", "contractor_id", "role", "contract_value", "award_date"]
    write_csv(os.path.join(args.outdir, "project_contractors.csv"), rels, rel_fields)

    signal_fields = ["signal_id", "project_id", "signal_type", "severity", "expected_reason",
                      "related_entity_id", "planted_for_testing", "explanation"]
    write_csv(os.path.join(args.outdir, "anomaly_signals.csv"), signals, signal_fields)

    print("NidhiGuard synthetic data generated (Prototype Environment — Synthetic Demonstration Data).")
    print(f"  projects.csv:            {len(projects)}")
    print(f"  contractors.csv:         {len(contractors)}")
    print(f"  bills.csv:               {len(bills)}")
    print(f"  payments.csv:            {len(payments)}")
    print(f"  locations.csv:           {len(locations)}")
    print(f"  historical_projects.csv: {len(historical)}")
    print(f"  project_contractors.csv: {len(rels)}")
    print(f"  anomaly_signals.csv:     {len(signals)}")
    hero = [p for p in projects if "HERO" in p.get("_tags", [])]
    if hero:
        print(f"  Hero case confirmed: {hero[0]['project_id']} ({hero[0]['project_name']})")


if __name__ == "__main__":
    main()
