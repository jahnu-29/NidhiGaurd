"""
NidhiGuard V2.1 - evaluation dataset: shared constants.

These constants define the *generative* ground truth of the evaluation pool
(the "true" median cost of a work type in a state, the construction thresholds
of each scenario). They are written from domain reasoning, NOT read from the
V1 detectors or the V1 dataset. Both the generator and the label-consistency
tests import this file, so a label can always be re-derived from the data
using only these numbers.

See evaluation/SCENARIO_SPEC.md for the plain-language definition of every rule.
"""
from datetime import date

SEED = 7919
DATASET_VERSION = "2.1.0-eval"

AS_OF_DATE = date(2025, 12, 31)          # snapshot date of the pool
SANCTION_MIN = date(2023, 1, 2)
SANCTION_MAX = date(2024, 12, 31)

N_PROJECTS = 150
N_CONTRACTORS = 100
N_HISTORICAL = 1200

# ---- cost model (INR) -------------------------------------------------------
# Generative median sanctioned amount of a work type, and log-normal sigma.
BASE_MEDIAN = {
    "Concrete Road": 3_000_000,
    "Bitumen Road": 2_400_000,
    "Hand Pump Installation": 180_000,
    "Overhead Water Tank": 1_600_000,
    "Classroom Block": 2_600_000,
    "Health Sub-Centre Upgrade": 2_000_000,
    "Street Lighting": 600_000,
    "Community Hall": 1_800_000,
    "Drainage System": 1_500_000,
}
SIGMA = {
    "Concrete Road": 0.30, "Bitumen Road": 0.30, "Hand Pump Installation": 0.25,
    "Overhead Water Tank": 0.28, "Classroom Block": 0.28,
    "Health Sub-Centre Upgrade": 0.28, "Street Lighting": 0.30,
    "Community Hall": 0.28, "Drainage System": 0.30,
}
STATE_FACTOR = {
    "Kerala": 1.12, "Tamil Nadu": 1.05, "Karnataka": 1.08, "Maharashtra": 1.10,
    "West Bengal": 0.97, "Odisha": 0.93, "Uttar Pradesh": 0.92, "Bihar": 0.88,
    "Madhya Pradesh": 0.94, "Rajasthan": 0.96,
}
CATEGORY = {
    "Concrete Road": "Road Infrastructure",
    "Bitumen Road": "Road Infrastructure",
    "Hand Pump Installation": "Drinking Water",
    "Overhead Water Tank": "Drinking Water",
    "Classroom Block": "Education Infrastructure",
    "Health Sub-Centre Upgrade": "Health Infrastructure",
    "Street Lighting": "Public Infrastructure",
    "Community Hall": "Community Infrastructure",
    "Drainage System": "Sanitation Infrastructure",
}
DURATION = {   # planned work duration in days (start -> expected completion)
    "Concrete Road": (150, 240), "Bitumen Road": (140, 220),
    "Hand Pump Installation": (90, 130), "Overhead Water Tank": (150, 230),
    "Classroom Block": (170, 260), "Health Sub-Centre Upgrade": (150, 230),
    "Street Lighting": (100, 150), "Community Hall": (160, 250),
    "Drainage System": (140, 220),
}
LONG_WORK_TYPES = [w for w, (lo, _) in DURATION.items() if lo >= 140]


def group_median(work_type: str, state: str) -> float:
    """Generative median sanctioned amount for (work type, state)."""
    return BASE_MEDIAN[work_type] * STATE_FACTOR[state]


# ---- rule thresholds (the label-consistency tests re-check all of these) -----
# NORMAL-1: plain normal cost sits within +-1.2 sigma of the group median
PLAIN_Z_MAX = 1.2
PLAIN_SANCTION_OVER_ESTIMATE_MAX = 1.06
PLAIN_MIN_BILL_SPAN_DAYS = 21             # no 3 bills within 20 days
PLAIN_END_SHARE_MAX = 0.30
PLAIN_ISOLATION_KM = 6.0
PLAIN_CONTRACTOR_CAP = 3

# COST-1
COST_RATIO_MIN = 1.7
COST_SANCTION_OVER_ESTIMATE_MIN = 1.6
COST_OBVIOUS = (3.0, 4.0)
COST_BORDERLINE = (1.8, 2.2)

# BILL-1 (compression) and BILL-2 (end-loading)
COMPRESS_OBVIOUS = {"bills": 4, "span_days": 5}
COMPRESS_BORDERLINE = {"bills": 3, "span_days": 10}
ENDLOAD_WINDOW = 0.15                      # last 15% of start -> completion
ENDLOAD_MIN_SHARE = 0.60
ENDLOAD_OBVIOUS = (0.72, 0.85)
ENDLOAD_BORDERLINE = (0.60, 0.66)

# CONT-1
CP_MIN_MEMBERS = 4
CP_WORK_ORDER_SPAN_MAX = 45
CP_RATIO_MIN = 1.15
CP_MIN_DISTANCE_KM = 10.0

# SIM-1
SIM_MAX_SANCTION_GAP_DAYS = 60
SIM_MAX_DISTANCE_KM = 2.0
SIM_MAX_AMOUNT_DIFF = 0.10                 # |a-b| / mean(a,b)

# GEO-1
GEO_MIN_MEMBERS = 3
GEO_MAX_CENTROID_KM = 2.0
GEO_MAX_AMOUNT_DEVIATION = 0.15            # vs cluster mean
GEO_MIN_SANCTION_GAP_DAYS = 60

# ADV-A (large legitimate portfolio)
ADVA_MIN_PROJECTS = 6
ADVA_MIN_WO_GAP_DAYS = 95
ADVA_MIN_WORK_TYPES = 4
ADVA_RATIO_RANGE = (0.79, 1.27)
ADVA_MIN_DISTANCE_KM = 10.0
# ADV-B (nearby legitimate projects)
ADVB_MAX_PAIR_KM = 1.6
ADVB_RATIO_RANGE = (0.84, 1.16)
# ADV-C (high-cost, justified)
ADVC_RATIO_MIN = 1.8
ADVC_SANCTION_OVER_ESTIMATE_MAX = 1.06
# ADV-D (milestone billing)
ADVD_FINAL_SHARE = (0.35, 0.50)
ADVD_MIN_BILL_GAP_DAYS = 25
# ADV-E (similar wording, legitimately separate)
ADVE_MIN_DISTANCE_KM = 8.0
ADVE_MIN_SANCTION_GAP_DAYS = 150
ADVE_MIN_AMOUNT_DIFF = 0.20

BANNED_ENGINE_COLUMNS = {
    "ground_truth_label", "scenario_type", "severity", "difficulty",
    "injected_signals", "group_id", "rationale", "adversarial_subtype", "label",
}
