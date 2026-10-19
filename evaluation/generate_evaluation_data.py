"""
NidhiGuard V2.1 - controlled evaluation dataset generator.

Independence notes
------------------
* Written from scratch. It does NOT import or reuse data-source/scripts/generate_data.py,
  does NOT read any V1 CSV (in particular never anomaly_signals.csv), and does NOT
  import anything from intelligence/.
* Every label is determined by the construction rule used to build the case
  (see evaluation/SCENARIO_SPEC.md), never by an engine score.
* Project IDs are assigned AFTER a random shuffle, so file order / ID order carries
  no information about scenario type.

Usage (from the repository root):
    python -m evaluation.generate_evaluation_data --out evaluation
Output:
    <out>/engine_input/*.csv          what the V1 engine is allowed to see
    <out>/evaluation_labels.csv       ground truth, used only AFTER prediction
    <out>/evaluation_metadata.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
from collections import Counter
from datetime import date, timedelta

from evaluation import spec_constants as K

# --------------------------------------------------------------------------- #
# Reference data (public geography; template wording written for this pool)
# --------------------------------------------------------------------------- #
DISTRICTS = {  # (state, district): (lat, lon)
    ("Bihar", "Bhagalpur"): (25.24, 86.97), ("Bihar", "Gaya"): (24.80, 85.00),
    ("Bihar", "Patna"): (25.59, 85.14),
    ("Karnataka", "Belagavi"): (15.85, 74.50), ("Karnataka", "Bengaluru Urban"): (12.97, 77.59),
    ("Karnataka", "Mysuru"): (12.30, 76.64),
    ("Kerala", "Ernakulam"): (9.98, 76.28), ("Kerala", "Kozhikode"): (11.26, 75.78),
    ("Kerala", "Thiruvananthapuram"): (8.52, 76.94),
    ("Madhya Pradesh", "Bhopal"): (23.26, 77.41), ("Madhya Pradesh", "Gwalior"): (26.22, 78.18),
    ("Madhya Pradesh", "Indore"): (22.72, 75.86),
    ("Maharashtra", "Nagpur"): (21.15, 79.09), ("Maharashtra", "Nashik"): (20.00, 73.79),
    ("Maharashtra", "Pune"): (18.52, 73.86),
    ("Odisha", "Cuttack"): (20.46, 85.88), ("Odisha", "Khordha"): (20.18, 85.62),
    ("Odisha", "Puri"): (19.81, 85.83),
    ("Rajasthan", "Jaipur"): (26.91, 75.79), ("Rajasthan", "Jodhpur"): (26.24, 73.02),
    ("Rajasthan", "Udaipur"): (24.59, 73.71),
    ("Tamil Nadu", "Chennai"): (13.08, 80.27), ("Tamil Nadu", "Coimbatore"): (11.02, 76.96),
    ("Tamil Nadu", "Madurai"): (9.93, 78.12),
    ("Uttar Pradesh", "Kanpur Nagar"): (26.45, 80.35), ("Uttar Pradesh", "Lucknow"): (26.85, 80.95),
    ("Uttar Pradesh", "Varanasi"): (25.32, 82.97),
    ("West Bengal", "Darjeeling"): (27.04, 88.26), ("West Bengal", "Howrah"): (22.59, 88.31),
    ("West Bengal", "Kolkata"): (22.57, 88.36),
}
DISTRICT_LIST = sorted(DISTRICTS)
DISTRICT_INDEX = {d: i + 1 for i, d in enumerate(DISTRICT_LIST)}
STATE_CODE = {"Bihar": "BR", "Karnataka": "KA", "Kerala": "KL", "Madhya Pradesh": "MP",
              "Maharashtra": "MH", "Odisha": "OD", "Rajasthan": "RJ", "Tamil Nadu": "TN",
              "Uttar Pradesh": "UP", "West Bengal": "WB"}
STATES = sorted(STATE_CODE)
WORK_TYPES = sorted(K.BASE_MEDIAN)

TEMPLATES = {
    "Concrete Road": ["Construction of Concrete Road at {v}", "Upgradation of internal road at {v} to concrete standard", "Laying of cement concrete road stretch in {v}"],
    "Bitumen Road": ["Bituminous road improvement at {v}", "Black-topping of road stretch in {v}", "Resurfacing of bitumen road connecting {v}"],
    "Hand Pump Installation": ["Installation of hand pump at {v}", "Drilling and fitting of hand pump, {v}", "Provision of hand pump for drinking water at {v}"],
    "Overhead Water Tank": ["Construction of overhead water tank at {v}", "Erection of elevated water storage tank, {v}", "Overhead tank for village water supply at {v}"],
    "Classroom Block": ["Construction of classroom block at {v}", "Extension of school building, {v}", "Additional classrooms for government school at {v}"],
    "Health Sub-Centre Upgrade": ["Upgradation of health sub-centre at {v}", "Renovation and equipping of sub-centre, {v}", "Strengthening of rural health sub-centre at {v}"],
    "Street Lighting": ["Installation of solar street lights at {v}", "Street lighting improvement work, {v}", "Provision of LED street lights along main road, {v}"],
    "Community Hall": ["Construction of community hall at {v}", "Community hall building for {v}", "Multi-purpose community hall, {v}"],
    "Drainage System": ["Construction of drainage system at {v}", "Storm water drain and culvert work, {v}", "Covered drain construction in {v}"],
}
SCOPE_PHRASES = [
    "including boundary wall and rainwater harvesting",
    "with additional scope of side drains and retaining wall",
    "two-storey with science laboratory and toilet block",
    "including culvert, side drains and road signage",
    "with solar backup, generator room and compound wall",
]
VILLAGE_PRE = ["Kala", "Nava", "Rama", "Vela", "Hari", "Mandi", "Shiva", "Gopal", "Anand", "Deva",
                "Lakshmi", "Padma", "Kesar", "Tara", "Surya", "Chandra", "Mohan", "Bala", "Indra", "Pushpa"]
VILLAGE_SUF = ["pur", "nagar", "palli", "gaon", "patti", "khed", "wadi", "kuppam", "halli", "pura"]
BLOCKS = ["Northern Block", "Southern Block", "Eastern Block", "Western Block", "Central Block", "Hill Block"]
CONTR_PRE = ["Sri", "Maruti", "Annapurna", "Bharat", "Gayatri", "Shakti", "Kaveri", "Narmada", "Ganga", "Vindhya",
             "Sahyadri", "Nilgiri", "Himalaya", "Konark", "Mahanadi", "Hoysala", "Chola", "Pallava", "Maurya", "Rajdhani"]
CONTR_MID = ["Infra", "Builders", "Constructions", "Engineering Works", "Infrastructure", "Associates", "Civil Works", "Developers"]
CONTR_TYPES = ["Individual Proprietor", "Partnership Firm", "Pvt Ltd", "Public Works Cooperative"]
AUTHORITIES = ["Executive Engineer (PWD)", "Assistant Engineer, PWD", "District Program Officer",
               "District Collector Office", "District Rural Development Agency"]
LOC_TYPES = ["Urban Ward", "Rural Village", "Panchayat"]

ENGINE_FILES = {
    "projects.csv": ["project_id", "project_code", "project_name", "project_description", "project_category", "work_type",
                     "mp_id", "constituency_id", "district_id", "state", "implementing_agency_id", "contractor_id",
                     "location_id", "sanctioned_amount", "estimated_cost", "approved_amount", "actual_expenditure",
                     "project_status", "sanction_date", "work_order_date", "start_date", "expected_completion_date",
                     "actual_completion_date", "completion_percentage", "created_date"],
    "contractors.csv": ["contractor_id", "contractor_name", "registration_number", "contractor_type", "district", "state",
                        "registration_date", "active_status", "total_projects", "total_project_value", "contact_reference"],
    "bills.csv": ["bill_id", "project_id", "contractor_id", "bill_number", "bill_date", "bill_type", "claimed_amount",
                  "approved_amount", "bill_status", "work_period_start", "work_period_end", "submission_date", "approval_date"],
    "payments.csv": ["payment_id", "bill_id", "project_id", "contractor_id", "payment_date", "payment_reference",
                     "payment_amount", "payment_mode", "payment_status", "approving_authority"],
    "locations.csv": ["location_id", "project_id", "state", "district", "constituency", "block", "village_or_ward",
                      "latitude", "longitude", "pincode", "location_type"],
    "historical_projects.csv": ["historical_project_id", "project_description", "project_category", "work_type", "state",
                                "district", "constituency", "latitude", "longitude", "sanctioned_amount",
                                "actual_expenditure", "completion_date", "contractor_id", "implementing_agency_id"],
    "project_contractors.csv": ["relationship_id", "project_id", "contractor_id", "role", "contract_value", "award_date"],
    # The V1 loader requires this file to exist. It is written HEADER-ONLY (zero rows):
    # no planted signals, no labels. Its only purpose is to let the unmodified loader run.
    "anomaly_signals.csv": ["signal_id", "project_id", "signal_type", "severity", "expected_reason",
                            "related_entity_id", "planted_for_testing", "explanation"],
}
LABEL_COLUMNS = ["project_id", "ground_truth_label", "scenario_type", "difficulty", "injected_signals",
                 "group_id", "severity", "adversarial_subtype", "rationale"]


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def haversine_km(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def offset(lat, lon, dx_km, dy_km):
    return (lat + dy_km / 110.574, lon + dx_km / (111.320 * math.cos(math.radians(lat))))


def iso(d):
    return d.isoformat() if d else ""


class Generator:
    def __init__(self):
        self.rng = random.Random(K.SEED)
        self.projects, self.bills, self.labels = [], [], []
        self.placed = []                # (lat, lon) of every project so far
        self.used_villages = set()
        self.contractors = []
        self.free_contractors = []
        self.contractor_load = {}       # cid -> list[(work_order, work_type)]
        self._build_contractors()

    # ----------------------------- primitives ----------------------------- #
    def u(self, a, b):
        return self.rng.uniform(a, b)

    def rdate(self, a, b):
        return a + timedelta(days=self.rng.randint(0, (b - a).days))

    def tnorm(self, lim):
        while True:
            z = self.rng.gauss(0, 0.6)
            if -lim <= z <= lim:
                return z

    def village(self):
        for _ in range(1000):
            v = self.rng.choice(VILLAGE_PRE) + self.rng.choice(VILLAGE_SUF)
            if v not in self.used_villages:
                self.used_villages.add(v)
                return v
        raise RuntimeError("village names exhausted")

    # ----------------------------- contractors ---------------------------- #
    def _build_contractors(self):
        names = set()
        for i in range(K.N_CONTRACTORS):
            while True:
                nm = f"{self.rng.choice(CONTR_PRE)} {self.rng.choice(CONTR_MID)}"
                ctype = self.rng.choice(CONTR_TYPES)
                nm += {"Pvt Ltd": " Pvt Ltd", "Partnership Firm": " & Co",
                       "Public Works Cooperative": " Cooperative", "Individual Proprietor": ""}[ctype]
                if nm not in names:
                    names.add(nm)
                    break
            st, dist = self.rng.choice(DISTRICT_LIST)
            cid = f"C-{501 + i}"
            self.contractors.append({
                "contractor_id": cid, "contractor_name": nm,
                "registration_number": f"REG-{STATE_CODE[st]}-{self.rng.randint(10000, 99999)}",
                "contractor_type": ctype, "district": dist, "state": st,
                "registration_date": iso(self.rdate(date(2008, 1, 1), date(2020, 12, 31))),
                "active_status": "Inactive" if self.rng.random() < 0.04 else "Active",
                "contact_reference": f"CONTACT-{cid}",
            })
            self.contractor_load[cid] = []
        ids = [c["contractor_id"] for c in self.contractors]
        self.rng.shuffle(ids)
        self.free_contractors = ids

    def fresh_contractor(self):
        return self.free_contractors.pop()

    def plain_contractor(self, work_order, work_type):
        """Pick a contractor for a plain normal: cap 3 projects, >=120 days apart."""
        ok = [c for c in self.free_contractors
              if len(self.contractor_load[c]) < K.PLAIN_CONTRACTOR_CAP
              and all(abs((work_order - wo).days) >= 120 for wo, _ in self.contractor_load[c])]
        used = [c for c in ok if self.contractor_load[c]]
        unused = [c for c in ok if not self.contractor_load[c]]
        if used and (not unused or self.rng.random() < 0.5):
            return self.rng.choice(used)
        if unused:
            return self.rng.choice(unused)
        raise RuntimeError("no plain contractor available")

    # ----------------------------- locations ------------------------------ #
    def _isolated(self, pt, min_km, ignore=()):
        return all(haversine_km(pt, p) >= min_km for i, p in enumerate(self.placed) if i not in ignore)

    def place_isolated(self, district, min_km=K.PLAIN_ISOLATION_KM, radius=28.0):
        lat, lon = DISTRICTS[district]
        for _ in range(2000):
            r, th = radius * math.sqrt(self.rng.random()), self.rng.random() * 2 * math.pi
            pt = offset(lat, lon, r * math.cos(th), r * math.sin(th))
            if self._isolated(pt, min_km):
                return pt
        raise RuntimeError(f"cannot place isolated point in {district}")

    def place_near(self, anchor, d_lo, d_hi, avoid_km=4.0, ignore=()):
        for _ in range(2000):
            d, th = self.u(d_lo, d_hi), self.rng.random() * 2 * math.pi
            pt = offset(anchor[0], anchor[1], d * math.cos(th), d * math.sin(th))
            if self._isolated(pt, avoid_km, ignore=ignore) or avoid_km == 0:
                return pt
        raise RuntimeError("cannot place point near anchor")

    # ----------------------------- bills ---------------------------------- #
    def _shares(self, total, n):
        w = [self.u(0.8, 1.2) for _ in range(n)]
        s = sum(w)
        return [total * x / s for x in w]

    def _plan_normal(self, S, C, completed, kw):
        adv_date = S + timedelta(days=7)
        adv = kw.get("adv", self.u(0.10, 0.15))
        n = self.rng.choice([2, 3, 4])
        n = min(n, max(1, (C - adv_date).days // 28 - 1))
        events = [("Advance", S, adv_date, adv)]
        f = kw.get("final", self.u(0.12, 0.25)) if completed else 0.0
        ra_total = 1.0 - adv - f
        shares = self._shares(ra_total, n)
        L = (C - adv_date).days
        gap = L / (n + 1)
        for k in range(1, n + 1):
            d = adv_date + timedelta(days=round(gap * k + self.u(-0.12, 0.12) * gap))
            events.append(("Running Account (RA)", None, d, shares[k - 1]))
        if completed:
            events.append(("Final", None, C, f))
        return events

    def _plan_milestone(self, S, C, kw):
        adv_date = S + timedelta(days=7)
        f = kw["final"]
        adv = 0.15
        rest = 1.0 - adv - f
        r1 = rest * self.u(0.45, 0.55)
        L = (C - adv_date).days
        return [("Advance", S, adv_date, adv),
                ("Running Account (RA)", None, adv_date + timedelta(days=round(L * 0.35)), r1),
                ("Running Account (RA)", None, adv_date + timedelta(days=round(L * 0.65)), rest - r1),
                ("Final", None, C, f)]

    def _plan_endload(self, S, C, kw):
        adv_date = S + timedelta(days=7)
        f = kw["final"]
        adv = self.u(0.08, 0.12)
        ra = 1.0 - adv - f
        ra_date = S + timedelta(days=round((C - S).days * self.u(0.25, 0.40)))
        return [("Advance", S, adv_date, adv), ("Running Account (RA)", None, ra_date, ra), ("Final", None, C, f)]

    def _plan_compress(self, S, C, kw):
        adv_date = S + timedelta(days=7)
        k = kw["bills"]
        adv, f = 0.10, self.u(0.15, 0.25)
        b0 = S + timedelta(days=round((C - S).days * self.u(0.45, 0.60)))
        if kw["bills"] == K.COMPRESS_OBVIOUS["bills"]:
            offs = sorted(self.rng.sample(range(0, K.COMPRESS_OBVIOUS["span_days"] + 1), k))
            offs[0] = 0
        else:
            offs = [0, self.rng.randint(2, 6), self.rng.randint(7, K.COMPRESS_BORDERLINE["span_days"])]
        shares = self._shares(1.0 - adv - f, k)
        events = [("Advance", S, adv_date, adv)]
        span = (b0 - timedelta(days=1) - adv_date).days
        for j in range(k):
            wp_end = adv_date + timedelta(days=round(span * (j + 1) / k))
            events.append(("Running Account (RA)", ("auto",), (b0 + timedelta(days=offs[j]), wp_end), shares[j]))
        events.append(("Final", None, C, f))
        return events

    def make_bills(self, pidx, style, S, C, total, completed, contractor, kw):
        if style == "normal":
            plan = self._plan_normal(S, C, completed, kw)
        elif style == "milestone":
            plan = self._plan_milestone(S, C, kw)
        elif style == "endload":
            plan = self._plan_endload(S, C, kw)
        elif style == "compress":
            plan = self._plan_compress(S, C, kw)
        else:
            raise ValueError(style)
        prev_end = None
        out = []
        for btype, wps, d, share in plan:
            if isinstance(wps, tuple):          # compress burst bill: d = (bill_date, wp_end)
                bill_date, wp_end = d
                wp_start = prev_end + timedelta(days=1)
            else:
                bill_date = wp_end = d
                wp_start = wps if wps is not None else prev_end + timedelta(days=1)
            if wp_start > wp_end:
                wp_start = wp_end
            prev_end = wp_end
            claimed = round(total * share, 2)
            approved = round(claimed * self.u(0.95, 0.995), 2)
            sub = bill_date + timedelta(days=self.rng.randint(1, 2))
            appr = sub + timedelta(days=self.rng.randint(3, 14))
            out.append({"pidx": pidx, "contractor_id": contractor, "bill_date": bill_date, "bill_type": btype,
                        "claimed": claimed, "approved": approved, "wp_start": wp_start, "wp_end": wp_end,
                        "submission": sub, "approval": appr,
                        "pay_date": appr + timedelta(days=self.rng.randint(5, 20)),
                        "mode": self.rng.choice(["PFMS Transfer", "RTGS", "Cheque"]),
                        "authority": self.rng.choice(AUTHORITIES)})
        return out

    # ----------------------------- projects ------------------------------- #
    def add_project(self, *, district, work_type, ratio, contractor, latlon, village, label,
                    desc=None, template=0, sanction=None, work_order=None, est_over_median=None,
                    status="Completed", bill_style="normal", bill_kw=None):
        state = district[0]
        median = K.group_median(work_type, state)
        amount = round(median * ratio, 2)
        est = round(median * est_over_median, 2) if est_over_median is not None else round(amount / self.u(1.0, 1.05), 2)
        if work_order is None:
            work_order = sanction + timedelta(days=self.rng.randint(5, 20))
        else:
            sanction = work_order - timedelta(days=self.rng.randint(5, 12))
        start = work_order + timedelta(days=self.rng.randint(3, 14))
        expected = start + timedelta(days=self.rng.randint(*K.DURATION[work_type]))
        if status == "Completed":
            actual = expected + timedelta(days=self.rng.randint(-8, 15))
            pct, C = 100, actual
        else:
            actual, pct = None, self.rng.randint(80, 95)
            C = start + timedelta(days=round((expected - start).days * 0.9))
        completed = status == "Completed"
        total = amount * self.u(0.90, 0.99) if completed else amount * (pct / 100) * self.u(0.90, 1.0)
        pidx = len(self.projects)
        bills = self.make_bills(pidx, bill_style, start, C, total, completed, contractor, bill_kw or {})
        self.bills.extend(bills)
        description = desc or TEMPLATES[work_type][template].format(v=village)
        self.projects.append({
            "district": district, "work_type": work_type, "state": state, "contractor": contractor,
            "latlon": latlon, "village": village, "description": description,
            "sanctioned": amount, "estimated": est, "approved": round(amount * self.u(0.97, 0.995), 2),
            "actual_exp": round(sum(b["approved"] for b in bills), 2),
            "status": status, "sanction": sanction, "work_order": work_order, "start": start,
            "expected": expected, "actual_completion": actual, "pct": pct,
            "agency": f"AGENCY-{self.rng.randint(1, 12):02d}",
            "block": self.rng.choice(BLOCKS), "loc_type": self.rng.choice(LOC_TYPES),
            "ratio": ratio, "label": label,
        })
        self.placed.append(latlon)
        self.contractor_load[contractor].append((work_order, work_type))
        return pidx

    @staticmethod
    def lab(scenario, difficulty, signals="", group="", severity=None, subtype="", rationale="", anomalous=None):
        if anomalous is None:
            anomalous = scenario not in ("NORMAL", "ADVERSARIAL_NORMAL")
        return {"ground_truth_label": "ANOMALOUS" if anomalous else "NORMAL", "scenario_type": scenario,
                "difficulty": difficulty, "injected_signals": signals, "group_id": group,
                "severity": severity or ("NONE" if not anomalous else "HIGH"),
                "adversarial_subtype": subtype, "rationale": rationale}

    def rand_district(self, exclude=()):
        return self.rng.choice([d for d in DISTRICT_LIST if d not in exclude])

    def rand_sanction(self, lo=None, hi=None):
        return self.rdate(lo or K.SANCTION_MIN, hi or K.SANCTION_MAX)

    # ----------------------------- scenarios ------------------------------ #
    def build_cost(self):
        for i in range(8):
            obv = i < 4
            k = self.u(*(K.COST_OBVIOUS if obv else K.COST_BORDERLINE))
            wt, dist = self.rng.choice(WORK_TYPES), self.rand_district()
            est = self.u(0.95, 1.08)
            r = (f"COST-1: sanctioned amount is {k:.2f}x the (work type, state) generative median while the "
                 f"estimated cost is only {est:.2f}x the median, so the sanction is not supported by the estimate and no "
                 f"scope text explains it.")
            self.add_project(district=dist, work_type=wt, ratio=k, contractor=self.fresh_contractor(),
                             latlon=self.place_isolated(dist), village=self.village(), template=self.rng.randrange(3),
                             sanction=self.rand_sanction(), est_over_median=est,
                             label=self.lab("COST_ANOMALY", "OBVIOUS" if obv else "BORDERLINE", "COST_INFLATION",
                                            severity="HIGH" if obv else "MEDIUM", rationale=r))

    def _billing_case(self, kind, obv, extra_cost=None, scenario="BILLING_ANOMALY", group="", rationale_prefix=""):
        wt, dist = self.rng.choice(K.LONG_WORK_TYPES), self.rand_district()
        if kind == "endload":
            f = self.u(*(K.ENDLOAD_OBVIOUS if obv else K.ENDLOAD_BORDERLINE))
            style, kw, sig = "endload", {"final": f}, "BILLING_ENDLOAD"
            why = (f"BILL-2: {f:.0%} of the total claimed amount was billed in the final bill, dated inside the last "
                   f"{K.ENDLOAD_WINDOW:.0%} of the project's start-to-completion window; earlier bills are few and small.")
        else:
            bills = (K.COMPRESS_OBVIOUS if obv else K.COMPRESS_BORDERLINE)["bills"]
            style, kw, sig = "compress", {"bills": bills}, "BILLING_COMPRESSION"
            why = (f"BILL-1: {bills} running-account bills were dated within a burst of at most "
                   f"{(K.COMPRESS_OBVIOUS if obv else K.COMPRESS_BORDERLINE)['span_days']} days mid-project.")
        k = extra_cost if extra_cost is not None else self.u(0.85, 1.15)
        est_over = self.u(0.95, 1.08) if extra_cost is not None else None
        if extra_cost is not None:
            why = (f"COST-1: sanctioned amount is {k:.2f}x the group median with the estimate at "
                   f"{est_over:.2f}x median (unsupported). ") + why
            sig = "COST_INFLATION;" + sig
        return self.add_project(
            district=dist, work_type=wt, ratio=k, contractor=self.fresh_contractor(),
            latlon=self.place_isolated(dist), village=self.village(), template=self.rng.randrange(3),
            sanction=self.rand_sanction(date(2023, 1, 2), date(2024, 11, 30)), est_over_median=est_over,
            bill_style=style, bill_kw=kw,
            label=self.lab(scenario, "OBVIOUS" if obv else "BORDERLINE", sig, group=group,
                           severity=("CRITICAL" if obv else "HIGH") if scenario == "MULTI_SIGNAL" else ("HIGH" if obv else "MEDIUM"),
                           rationale=rationale_prefix + why))

    def build_billing(self):
        for kind, obv in [("endload", True), ("endload", True), ("endload", False), ("endload", False),
                          ("compress", True), ("compress", True), ("compress", False), ("compress", False)]:
            self._billing_case(kind, obv)

    def build_contractor_pattern(self):
        for gi, (n, obv, base, window, kr) in enumerate([
                (5, True, date(2023, 6, 5), 16, (1.30, 1.55)),
                (4, False, date(2023, 10, 2), 38, (1.15, 1.30))], start=1):
            cid = self.fresh_contractor()
            wt = self.rng.choice(K.LONG_WORK_TYPES)
            districts = self.rng.sample(DISTRICT_LIST, n)
            offs = sorted(set([0, window] + self.rng.sample(range(1, window), n - 2)))
            gid = f"GRP-CP-{gi:02d}"
            for dist, off in zip(districts, offs):
                k = self.u(*kr)
                r = (f"CONT-1: contractor holds {n} same-work-type projects awarded within {window} days, all at "
                     f"{kr[0]:.2f}-{kr[1]:.2f}x the group median (this project {k:.2f}x), in districts at least "
                     f"{K.CP_MIN_DISTANCE_KM:.0f} km apart; the contractor's other projects are cheaper and months away.")
                self.add_project(district=dist, work_type=wt, ratio=k, contractor=cid,
                                 latlon=self.place_isolated(dist, 8.0), village=self.village(),
                                 template=self.rng.randrange(3), work_order=base + timedelta(days=off),
                                 label=self.lab("CONTRACTOR_PATTERN", "OBVIOUS" if obv else "BORDERLINE",
                                                "CONTRACTOR_CONCENTRATION", group=gid,
                                                severity="HIGH" if obv else "MEDIUM", rationale=r))
            # the same contractor's ordinary, cheaper, well-separated work (plain normals)
            gap = self.rng.randint(150, 200)
            for ex in range(2):
                other_wt = self.rng.choice([w for w in WORK_TYPES if w != wt])
                dist = self.rand_district()
                wo = base + timedelta(days=window + gap)
                self._plain_one(contractor=cid, work_type=other_wt, district=dist, work_order=wo,
                                z_range=(-0.9, -0.1))
                gap += self.rng.randint(150, 180)

    def build_similar(self):
        specs = [(True, 0), (True, 1), (False, 2), (False, 3)]
        for gi, (obv, _) in enumerate(specs, start=1):
            wt, dist = self.rng.choice(WORK_TYPES), self.rand_district()
            v = self.village()
            ratio_a = self.u(0.85, 1.15)
            sanc_a = self.rand_sanction(date(2023, 1, 2), date(2024, 10, 31))
            c_a = self.fresh_contractor()
            c_b = c_a if obv else self.fresh_contractor()
            pt_a = self.place_isolated(dist)
            gap = self.rng.randint(5, 20) if obv else self.rng.randint(40, 60)
            d_km = self.u(0.1, 0.5) if obv else self.u(1.0, 1.8)
            amt_f = self.u(0.97, 1.03) if obv else self.u(0.92, 1.08)
            t_a = self.rng.randrange(3)
            gid = f"GRP-SIM-{gi:02d}"
            desc_a = TEMPLATES[wt][t_a].format(v=v)
            if obv:
                desc_b = desc_a + " - new work"
            else:
                desc_b = TEMPLATES[wt][(t_a + 1) % 3].format(v=v)
            r = (f"SIM-1: a pair of {wt} projects in {dist[1]}, {'near-identical' if obv else 'paraphrased'} descriptions "
                 f"for the same village, sanctioned {gap} days apart, about {d_km:.1f} km apart, amounts within "
                 f"{abs(amt_f - 1) * 100:.0f}% of each other, {'same' if obv else 'different'} contractor.")
            lbl = lambda: self.lab("SIMILAR_PROJECT", "OBVIOUS" if obv else "BORDERLINE", "DUPLICATE_LIKE", group=gid,
                                   severity="HIGH" if obv else "MEDIUM", rationale=r)
            ia = self.add_project(district=dist, work_type=wt, ratio=ratio_a, contractor=c_a, latlon=pt_a, village=v,
                                  desc=desc_a, sanction=sanc_a, label=lbl())
            pt_b = self.place_near(pt_a, d_km, d_km, avoid_km=3.0, ignore=(ia,))
            self.add_project(district=dist, work_type=wt, ratio=ratio_a * amt_f, contractor=c_b, latlon=pt_b,
                             village=v, desc=desc_b, sanction=sanc_a + timedelta(days=gap), label=lbl())

    def build_geographic(self):
        for gi, (n, obv, rad, dev, base) in enumerate([
                (5, True, 0.8, 0.07, date(2023, 3, 1)), (3, False, 1.8, 0.12, date(2024, 1, 10))], start=1):
            dist, wt = self.rand_district(), self.rng.choice(WORK_TYPES)
            cid = self.fresh_contractor()
            center = self.place_isolated(dist, 10.0)
            gid = f"GRP-GEO-{gi:02d}"
            mean_ratio = self.u(1.0, 1.12)
            sanc = base
            for m in range(n):
                th = 2 * math.pi * m / n + self.u(-0.3, 0.3)
                rr = self.u(0.4, 1.0) * rad
                pt = offset(center[0], center[1], rr * math.cos(th), rr * math.sin(th))
                k = mean_ratio * self.u(1 - dev, 1 + dev)
                r = (f"GEO-1: {n} {wt} projects within {rad:.1f} km of one centre, same contractor, amounts within "
                     f"{dev:.0%} of the cluster mean, sanctioned at least {K.GEO_MIN_SANCTION_GAP_DAYS} days apart "
                     f"with different villages/descriptions.")
                self.add_project(district=dist, work_type=wt, ratio=k, contractor=cid, latlon=pt, village=self.village(),
                                 template=m % 3, sanction=sanc,
                                 label=self.lab("GEOGRAPHIC_PATTERN", "OBVIOUS" if obv else "BORDERLINE", "GEO_CLUSTER",
                                                group=gid, severity="HIGH" if obv else "MEDIUM", rationale=r))
                sanc = sanc + timedelta(days=self.rng.randint(65, 90))

    def build_multi(self):
        combos = [("endload", True), ("compress", True), ("endload", True),
                  ("endload", False), ("compress", False), ("endload", False)]
        for kind, obv in combos:
            k = self.u(2.8, 3.6) if obv else self.u(1.8, 2.0)
            self._billing_case(kind, obv, extra_cost=k, scenario="MULTI_SIGNAL")
        # duplicate-like pair with inflated cost on both members
        wt, dist = self.rng.choice(WORK_TYPES), self.rand_district()
        v, ratio_a, cid = self.village(), self.u(2.2, 2.6), self.fresh_contractor()
        pt_a, sanc = self.place_isolated(dist), self.rand_sanction(date(2023, 1, 2), date(2024, 10, 31))
        gap, d_km, amt_f, t_a = self.rng.randint(5, 20), self.u(0.1, 0.5), self.u(0.97, 1.03), self.rng.randrange(3)
        est = self.u(0.95, 1.08)
        r = (f"MULTI-1: SIM-1 duplicate-like pair (same village, near-identical wording, {gap} days apart, "
             f"{d_km:.1f} km apart, same contractor) AND COST-1 (both sanctioned at about {ratio_a:.1f}x group median "
             f"with the estimate at {est:.2f}x median, unsupported).")
        lbl = lambda: self.lab("MULTI_SIGNAL", "OBVIOUS", "DUPLICATE_LIKE;COST_INFLATION", group="GRP-MULTI-01",
                               severity="CRITICAL", rationale=r)
        da = TEMPLATES[wt][t_a].format(v=v)
        ia = self.add_project(district=dist, work_type=wt, ratio=ratio_a, contractor=cid, latlon=pt_a, village=v,
                              desc=da, sanction=sanc, est_over_median=est, label=lbl())
        self.add_project(district=dist, work_type=wt, ratio=ratio_a * amt_f, contractor=cid,
                         latlon=self.place_near(pt_a, d_km, d_km, avoid_km=3.0, ignore=(ia,)), village=v,
                         desc=da + " - new work", sanction=sanc + timedelta(days=gap), est_over_median=est, label=lbl())

    # ----- adversarial normals -----
    def build_adv_a(self):
        for gi in (1, 2):
            cid = self.fresh_contractor()
            wts = self.rng.sample(WORK_TYPES, 7)
            dists = self.rng.sample(DISTRICT_LIST, 7)
            wo = date(2023, 2, 1) + timedelta(days=self.rng.randint(0, 25))
            for wt, dist in zip(wts, dists):
                k = math.exp(self.u(-0.8, 0.8) * K.SIGMA[wt])
                r = ("ADV-A: contractor with a large portfolio (7 projects) spread over ~22 months, at least "
                     f"{K.ADVA_MIN_WO_GAP_DAYS} days between awards, {len(set(wts))} different work types, different "
                     "districts, costs within normal range, no clustering.")
                self.add_project(district=dist, work_type=wt, ratio=k, contractor=cid,
                                 latlon=self.place_isolated(dist, 8.0), village=self.village(),
                                 template=self.rng.randrange(3), work_order=wo,
                                 label=self.lab("ADVERSARIAL_NORMAL", "NA", group=f"GRP-ADVA-{gi:02d}", subtype="A",
                                                rationale=r, anomalous=False))
                wo += timedelta(days=self.rng.randint(100, 112))

    def build_adv_b(self):
        for gi in (1, 2, 3):
            dist = self.rand_district()
            wts = self.rng.sample(WORK_TYPES, 3)
            center = self.place_isolated(dist, 10.0)
            sanc = self.rand_sanction(date(2023, 1, 2), date(2024, 5, 31))
            for m, wt in enumerate(wts):
                th = 2 * math.pi * m / 3 + self.u(-0.2, 0.2)
                rr = self.u(0.35, 0.7)
                pt = offset(center[0], center[1], rr * math.cos(th), rr * math.sin(th))
                r = ("ADV-B: three projects within about 1 km of each other but three different work types, three "
                     "different contractors, sanctioned at least 60 days apart, normal cost and billing.")
                self.add_project(district=dist, work_type=wt, ratio=self.u(*K.ADVB_RATIO_RANGE), contractor=self.fresh_contractor(),
                                 latlon=pt, village=self.village(), template=self.rng.randrange(3), sanction=sanc,
                                 label=self.lab("ADVERSARIAL_NORMAL", "NA", group=f"GRP-ADVB-{gi:02d}", subtype="B",
                                                rationale=r, anomalous=False))
                sanc += timedelta(days=self.rng.randint(65, 90))

    def build_adv_c(self):
        for i in range(5):
            wt, dist = self.rng.choice(WORK_TYPES), self.rand_district()
            k = self.u(1.8, 2.4)
            phrase = SCOPE_PHRASES[i % len(SCOPE_PHRASES)]
            v = self.village()
            est = k * self.u(0.97, 1.03)
            r = (f"ADV-C: sanctioned amount is {k:.2f}x the group median, but the estimated cost corroborates it "
                 f"({est:.2f}x median) and the description documents extra scope ({phrase}).")
            self.add_project(district=dist, work_type=wt, ratio=k, contractor=self.fresh_contractor(),
                             latlon=self.place_isolated(dist), village=v,
                             desc=TEMPLATES[wt][self.rng.randrange(3)].format(v=v) + ", " + phrase,
                             sanction=self.rand_sanction(), est_over_median=est,
                             label=self.lab("ADVERSARIAL_NORMAL", "NA", subtype="C", rationale=r, anomalous=False))

    def build_adv_d(self):
        for i in range(5):
            wt, dist = self.rng.choice(K.LONG_WORK_TYPES), self.rand_district()
            f = self.u(0.38, 0.48)
            r = (f"ADV-D: milestone payment structure - advance plus two evenly spaced running bills, then a final bill "
                 f"of {f:.0%} on completion certificate; the final share is high but the earlier billing is regular.")
            self.add_project(district=dist, work_type=wt, ratio=self.u(0.85, 1.15), contractor=self.fresh_contractor(),
                             latlon=self.place_isolated(dist), village=self.village(), template=self.rng.randrange(3),
                             sanction=self.rand_sanction(date(2023, 1, 2), date(2024, 11, 30)),
                             bill_style="milestone", bill_kw={"final": f},
                             label=self.lab("ADVERSARIAL_NORMAL", "NA", subtype="D", rationale=r, anomalous=False))

    def build_adv_e(self):
        for gi in range(1, 5):
            wt, dist = self.rng.choice(WORK_TYPES), self.rand_district()
            t = self.rng.randrange(3)
            pt_a = self.place_isolated(dist)
            sanc = self.rand_sanction(date(2023, 1, 2), date(2024, 5, 31))
            ka, kb = self.u(0.78, 0.92), self.u(1.16, 1.30)
            d_km = self.u(9.0, 18.0)
            gap = self.rng.randint(150, 220)
            r = (f"ADV-E: two {wt} projects in {dist[1]} using the same description template (different villages), "
                 f"about {d_km:.0f} km apart, sanctioned {gap} days apart, amounts differing by "
                 f"{(kb / ka - 1) * 100:.0f}%, different contractors: similar wording only.")
            ia = self.add_project(district=dist, work_type=wt, ratio=ka, contractor=self.fresh_contractor(),
                                  latlon=pt_a, village=self.village(), template=t, sanction=sanc,
                                  label=self.lab("ADVERSARIAL_NORMAL", "NA", group=f"GRP-ADVE-{gi:02d}", subtype="E",
                                                 rationale=r, anomalous=False))
            pt_b = self.place_near(pt_a, d_km, d_km, avoid_km=4.0, ignore=(ia,))
            self.add_project(district=dist, work_type=wt, ratio=kb, contractor=self.fresh_contractor(),
                             latlon=pt_b, village=self.village(), template=t, sanction=sanc + timedelta(days=gap),
                             label=self.lab("ADVERSARIAL_NORMAL", "NA", group=f"GRP-ADVE-{gi:02d}", subtype="E",
                                            rationale=r, anomalous=False))

    # ----- plain normals -----
    def _plain_one(self, *, contractor=None, work_type=None, district=None, work_order=None, z_range=None):
        wt = work_type or self.rng.choice(WORK_TYPES)
        dist = district or self.rand_district()
        if work_order is None:
            sanction, wo = self.rand_sanction(), None
            wo_for_pick = sanction + timedelta(days=12)
        else:
            sanction, wo, wo_for_pick = None, work_order, work_order
        cid = contractor or self.plain_contractor(wo_for_pick, wt)
        if z_range:
            z = self.u(*z_range)
        else:
            z = self.tnorm(K.PLAIN_Z_MAX)
        ratio = math.exp(K.SIGMA[wt] * z)
        status = "Completed" if self.rng.random() < 0.8 else "Delayed"
        r = (f"NORM-1: cost {ratio:.2f}x group median (within +-{K.PLAIN_Z_MAX} sigma), estimate corroborates the sanction, "
             f"bills spaced at least 3 weeks apart with a modest final bill, no near neighbour, contractor has a "
             f"small spread-out portfolio.")
        self.add_project(district=dist, work_type=wt, ratio=ratio, contractor=cid,
                         latlon=self.place_isolated(dist), village=self.village(), template=self.rng.randrange(3),
                         sanction=sanction, work_order=wo, status=status,
                         label=self.lab("NORMAL", "NA", rationale=r, anomalous=False))

    def build_plain_normals(self):
        while len(self.projects) < K.N_PROJECTS:
            self._plain_one()

    # ----------------------------- output --------------------------------- #
    def finalize(self, out_dir):
        rng = self.rng
        n = len(self.projects)
        order = list(range(n))
        rng.shuffle(order)
        pid = {idx: f"P-{5001 + rank}" for rank, idx in enumerate(order)}
        ranked = sorted(range(n), key=lambda i: pid[i])
        loc_id = {idx: f"L-{5001 + r}" for r, idx in enumerate(ranked)}
        rank_of = {idx: r for r, idx in enumerate(ranked)}

        by_c = Counter(), Counter()
        for p in self.projects:
            by_c[0][p["contractor"]] += 1
            by_c[1][p["contractor"]] += p["sanctioned"]

        rows = {k: [] for k in ENGINE_FILES}
        year_seq = Counter()
        for i in ranked:
            p = self.projects[i]
            di = DISTRICT_INDEX[p["district"]]
            rows["projects.csv"].append({
                "project_id": pid[i],
                "project_code": f"MPLADS/{STATE_CODE[p['state']]}/{p['sanction'].year}/{5001 + rank_of[i]:04d}",
                "project_name": p["description"], "project_description": p["description"],
                "project_category": K.CATEGORY[p["work_type"]], "work_type": p["work_type"],
                "mp_id": f"MP-{di:02d}", "constituency_id": f"CONST-{di:02d}", "district_id": f"DIST-{di:02d}",
                "state": p["state"], "implementing_agency_id": p["agency"], "contractor_id": p["contractor"],
                "location_id": loc_id[i], "sanctioned_amount": f"{p['sanctioned']:.2f}",
                "estimated_cost": f"{p['estimated']:.2f}", "approved_amount": f"{p['approved']:.2f}",
                "actual_expenditure": f"{p['actual_exp']:.2f}", "project_status": p["status"],
                "sanction_date": iso(p["sanction"]), "work_order_date": iso(p["work_order"]),
                "start_date": iso(p["start"]), "expected_completion_date": iso(p["expected"]),
                "actual_completion_date": iso(p["actual_completion"]), "completion_percentage": p["pct"],
                "created_date": iso(p["sanction"])})
            rows["locations.csv"].append({
                "location_id": loc_id[i], "project_id": pid[i], "state": p["state"], "district": p["district"][1],
                "constituency": f"CONST-{di:02d}", "block": p["block"], "village_or_ward": p["village"],
                "latitude": f"{p['latlon'][0]:.5f}", "longitude": f"{p['latlon'][1]:.5f}",
                "pincode": f"{rng.randint(100000, 899999)}", "location_type": p["loc_type"]})
            rows["project_contractors.csv"].append({
                "relationship_id": f"REL-{5001 + len(rows['project_contractors.csv'])}", "project_id": pid[i],
                "contractor_id": p["contractor"], "role": "Primary Contractor",
                "contract_value": f"{p['sanctioned']:.2f}", "award_date": iso(p["work_order"])})

        bills = sorted(self.bills, key=lambda b: (pid[b["pidx"]], b["bill_date"], b["bill_type"] != "Advance"))
        for k, b in enumerate(bills):
            bid = f"B-{50001 + k}"
            year_seq[b["bill_date"].year] += 1
            rows["bills.csv"].append({
                "bill_id": bid, "project_id": pid[b["pidx"]], "contractor_id": b["contractor_id"],
                "bill_number": f"BILL/{b['bill_date'].year}/{year_seq[b['bill_date'].year]:04d}",
                "bill_date": iso(b["bill_date"]), "bill_type": b["bill_type"],
                "claimed_amount": f"{b['claimed']:.2f}", "approved_amount": f"{b['approved']:.2f}",
                "bill_status": "Approved", "work_period_start": iso(b["wp_start"]), "work_period_end": iso(b["wp_end"]),
                "submission_date": iso(b["submission"]), "approval_date": iso(b["approval"])})
            rows["payments.csv"].append({
                "payment_id": f"PAY-{50001 + k}", "bill_id": bid, "project_id": pid[b["pidx"]],
                "contractor_id": b["contractor_id"], "payment_date": iso(b["pay_date"]),
                "payment_reference": f"UTR-SIM-{50001 + k:06d}", "payment_amount": f"{b['approved']:.2f}",
                "payment_mode": b["mode"], "payment_status": "Success", "approving_authority": b["authority"]})

        for c in self.contractors:
            rows["contractors.csv"].append({**c, "total_projects": by_c[0][c["contractor_id"]],
                                            "total_project_value": f"{by_c[1][c['contractor_id']]:.2f}"})

        # independent historical baseline drawn from the generative cost model
        cids = [c["contractor_id"] for c in self.contractors]
        for h in range(K.N_HISTORICAL):
            wt, dist = rng.choice(WORK_TYPES), rng.choice(DISTRICT_LIST)
            z = max(-2.5, min(2.5, rng.gauss(0, 1)))
            amt = K.group_median(wt, dist[0]) * math.exp(K.SIGMA[wt] * z)
            lat, lon = DISTRICTS[dist]
            rr, th = 30 * math.sqrt(rng.random()), rng.random() * 2 * math.pi
            la, lo = offset(lat, lon, rr * math.cos(th), rr * math.sin(th))
            rows["historical_projects.csv"].append({
                "historical_project_id": f"H-{5001 + h}",
                "project_description": TEMPLATES[wt][rng.randrange(3)].format(v=rng.choice(VILLAGE_PRE) + rng.choice(VILLAGE_SUF)),
                "project_category": K.CATEGORY[wt], "work_type": wt, "state": dist[0], "district": dist[1],
                "constituency": f"CONST-{DISTRICT_INDEX[dist]:02d}", "latitude": f"{la:.5f}", "longitude": f"{lo:.5f}",
                "sanctioned_amount": f"{amt:.2f}", "actual_expenditure": f"{amt * rng.uniform(0.9, 1.0):.2f}",
                "completion_date": iso(self.rdate(date(2018, 1, 1), date(2022, 12, 31))),
                "contractor_id": rng.choice(cids), "implementing_agency_id": f"AGENCY-{rng.randint(1, 12):02d}"})

        eng_dir = os.path.join(out_dir, "engine_input")
        os.makedirs(eng_dir, exist_ok=True)
        for fn, cols in ENGINE_FILES.items():
            with open(os.path.join(eng_dir, fn), "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
                w.writeheader()
                w.writerows(rows[fn])

        label_rows = []
        for i in ranked:
            label_rows.append({"project_id": pid[i], **self.projects[i]["label"]})
        with open(os.path.join(out_dir, "evaluation_labels.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=LABEL_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(label_rows)
        return label_rows


SCENARIO_CONSTRUCTION = {
    "NORMAL": "NORM-1: cost within +-1.2 sigma of the generative (work type, state) median, estimate corroborates sanction, bills >=3 weeks apart with final bill 12-25%, >=6 km from every other project, contractor <=3 projects >=120 days apart.",
    "COST_ANOMALY": "COST-1: sanctioned = 3.0-4.0x (obvious) or 1.8-2.2x (borderline) generative median; estimated cost stays at ~median so the estimate does not support the sanction; no scope text.",
    "BILLING_ANOMALY": "BILL-1 compression (4 bills in <=5 days / 3 bills in <=10 days mid-project) or BILL-2 end-loading (72-85% / 60-66% of claims in the final bill within the last 15% of the project window).",
    "CONTRACTOR_PATTERN": "CONT-1: one contractor, 5 (obvious, 16-day window, 1.30-1.55x) or 4 (borderline, 38-day window, 1.15-1.30x) same-work-type projects in districts >=10 km apart; contractor's other projects are cheaper and >=150 days away.",
    "SIMILAR_PROJECT": "SIM-1: pairs, same work type/district/village; obvious = near-identical wording, 5-20 days, 0.1-0.5 km, +-3%, same contractor; borderline = paraphrased wording, 40-60 days, 1.0-1.8 km, +-8%, different contractors.",
    "GEOGRAPHIC_PATTERN": "GEO-1: same contractor and work type, comparable amounts, tight cluster (5 projects <=0.8 km +-7% / 3 projects <=1.8 km +-12%), sanctioned >=60 days apart, different villages and templates.",
    "MULTI_SIGNAL": "MULTI-1: >=2 independent injected signals each meeting its rule: COST-1 + BILL-1/BILL-2 (6 projects, 3 obvious, 3 borderline) and one duplicate-like pair with inflated cost on both members.",
    "ADVERSARIAL_NORMAL": "ADV-A large legitimate portfolio; ADV-B nearby but unrelated works; ADV-C high cost with corroborating estimate and documented scope; ADV-D milestone billing with 38-48% final bill; ADV-E similar wording but far apart, months apart, different amounts.",
}
KNOWN_LIMITATIONS = [
    "Controlled synthetic evaluation dataset; it does not represent real MPLADS ground truth.",
    "The scenarios and the V1 detectors were designed by the same author, so this measures agreement with the author's definition of 'suspicious', not with an external truth.",
    "Rules were written before any engine output was seen, and no detector source file was read. However, the scenario author had read the V1 README's plain-language description of each detector (median cost benchmark, contractor concentration, bill timing, proximity plus shared attributes), so the scenario families mirror the detector families by design. Complete independence cannot be guaranteed.",
    "While inspecting file layouts, the first two rows of V1 anomaly_signals.csv (one CONTRACTOR_PATTERN and one COST_ANOMALY explanation sentence) were displayed to the scenario author. They were not used as input, but the CONT-1 rule resembles that sentence; treat CONTRACTOR_PATTERN results with extra caution.",
    "The sample is small (150 cases, 49 anomalous); metrics will have wide confidence intervals.",
    "Labels are binary by construction; real-world ambiguity (a legitimate project that looks odd, a fraud that looks clean) is only represented by the ADVERSARIAL_NORMAL and BORDERLINE cases.",
    "Several adversarial cases (ADV-C, ADV-D) rely on fields (estimated cost, bill structure) the V1 engine may not use; expected false positives there are a property of the engine, not a dataset defect.",
    "The V1 loader requires anomaly_signals.csv; a header-only placeholder is shipped in engine_input. It contains no rows and no labels.",
    "Cost scale, template wording and the district list are domain-plausible, not calibrated to real data.",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def generate(out_dir: str) -> dict:
    g = Generator()
    # order matters only for contractor/district allocation; IDs are shuffled in finalize()
    g.build_cost()
    g.build_billing()
    g.build_contractor_pattern()
    g.build_similar()
    g.build_geographic()
    g.build_multi()
    g.build_adv_a()
    g.build_adv_b()
    g.build_adv_c()
    g.build_adv_d()
    g.build_adv_e()
    g.build_plain_normals()
    assert len(g.projects) == K.N_PROJECTS, len(g.projects)
    labels = g.finalize(out_dir)

    sc = Counter(l["scenario_type"] for l in labels)
    meta = {
        "dataset_version": K.DATASET_VERSION,
        "creation_method": "Deterministic rule-based construction (evaluation/generate_evaluation_data.py, seed "
                           f"{K.SEED}). Each case is built from an explicit scenario rule in evaluation/SCENARIO_SPEC.md; "
                           "labels are the scenario the case was built from. Project IDs are assigned after a random shuffle.",
        "generator_seed": K.SEED,
        "as_of_date": K.AS_OF_DATE.isoformat(),
        "number_of_cases": len(labels),
        "number_normal": sum(l["ground_truth_label"] == "NORMAL" for l in labels),
        "number_anomalous": sum(l["ground_truth_label"] == "ANOMALOUS" for l in labels),
        "scenario_distribution": dict(sorted(sc.items())),
        "difficulty_distribution": dict(sorted(Counter(l["difficulty"] for l in labels).items())),
        "adversarial_negative_count": sc["ADVERSARIAL_NORMAL"],
        "adversarial_subtype_distribution": dict(sorted(Counter(l["adversarial_subtype"] for l in labels if l["adversarial_subtype"]).items())),
        "label_definition": "ANOMALOUS = the project was constructed to satisfy at least one anomaly rule (COST-1, BILL-1, "
                            "BILL-2, CONT-1, SIM-1, GEO-1) in SCENARIO_SPEC.md. NORMAL = constructed to satisfy NORM-1 or one "
                            "of the ADV-A..E legitimate-lookalike rules. A label says how the case was built, not what any detector says.",
        "independence_statement": "This dataset is intentionally separated from the V1 planted-signal dataset and is used only for evaluation. "
                                  "The labels are generated from independently defined evaluation scenarios and are not derived from "
                                  "NidhiGuard risk scores. The generator does not read any V1 data file, does not import the intelligence "
                                  "package, and was written without reading the detector implementations.",
        "leakage_controls": [
            "Labels live in evaluation_labels.csv, outside engine_input/; no label, scenario, difficulty or group column exists in any engine input file.",
            "engine_input/anomaly_signals.csv is header-only (0 rows); it exists solely because the V1 loader requires the file.",
            "The generator never reads data-source/ and never imports intelligence/.",
            "The prediction runner never opens evaluation_labels.csv.",
            "Project IDs are shuffled so ID order and file order carry no scenario information.",
            "SHA-256 hashes of all dataset files are recorded here before the engine is run; later changes must be logged in CHANGELOG.md.",
        ],
        "scenario_construction": SCENARIO_CONSTRUCTION,
        "known_limitations": KNOWN_LIMITATIONS,
        "engine_input_files": sorted(ENGINE_FILES),
        "file_sha256": {},
    }
    files = {f"engine_input/{fn}": os.path.join(out_dir, "engine_input", fn) for fn in sorted(ENGINE_FILES)}
    files["evaluation_labels.csv"] = os.path.join(out_dir, "evaluation_labels.csv")
    meta["file_sha256"] = {k: sha256(v) for k, v in files.items()}
    with open(os.path.join(out_dir, "evaluation_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluation")
    a = ap.parse_args()
    meta = generate(a.out)
    print(f"cases={meta['number_of_cases']} normal={meta['number_normal']} anomalous={meta['number_anomalous']} "
          f"adversarial={meta['adversarial_negative_count']}")
    print(meta["scenario_distribution"])


if __name__ == "__main__":
    main()
