"""
V2.1 evaluation dataset validation.

Run against the committed dataset:   pytest evaluation/tests -q
Run against a scratch build:         EVAL_DIR=/tmp/draft pytest evaluation/tests -q

These tests never call the V1 engine. They (a) validate data quality, (b) check there is
no label leakage, and (c) re-derive every label rule from the raw engine-input CSVs using
only evaluation/spec_constants.py, so a label can never silently disagree with its data.
"""
import hashlib
import itertools
import json
import math
import os
import tempfile
from datetime import timedelta

import pandas as pd
import pytest

from evaluation import spec_constants as K
from evaluation.generate_evaluation_data import ENGINE_FILES, haversine_km, generate

EVAL_DIR = os.environ.get("EVAL_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ENG = os.path.join(EVAL_DIR, "engine_input")
DATE_COLS = {
    "projects.csv": ["sanction_date", "work_order_date", "start_date", "expected_completion_date",
                     "actual_completion_date", "created_date"],
    "bills.csv": ["bill_date", "work_period_start", "work_period_end", "submission_date", "approval_date"],
    "payments.csv": ["payment_date"], "contractors.csv": ["registration_date"],
    "historical_projects.csv": ["completion_date"], "project_contractors.csv": ["award_date"],
}


def _read(fn):
    df = pd.read_csv(os.path.join(ENG, fn), dtype=str, keep_default_na=False)
    for c in DATE_COLS.get(fn, []):
        df[c] = pd.to_datetime(df[c].replace("", pd.NA), errors="raise")
    return df


@pytest.fixture(scope="module")
def d():
    t = {fn[:-4]: _read(fn) for fn in ENGINE_FILES}
    p = t["projects"].copy()
    for c in ["sanctioned_amount", "estimated_cost", "approved_amount", "actual_expenditure", "completion_percentage"]:
        p[c] = pd.to_numeric(p[c])
    t["projects"] = p
    for fn, cols in [("bills", ["claimed_amount", "approved_amount"]), ("payments", ["payment_amount"]),
                     ("locations", ["latitude", "longitude"]), ("historical_projects", ["sanctioned_amount", "actual_expenditure", "latitude", "longitude"]),
                     ("project_contractors", ["contract_value"]), ("contractors", ["total_projects", "total_project_value"])]:
        for c in cols:
            t[fn][c] = pd.to_numeric(t[fn][c])
    labels = pd.read_csv(os.path.join(EVAL_DIR, "evaluation_labels.csv"), dtype=str, keep_default_na=False)
    t["labels"] = labels
    # convenience: projects + location + label
    m = p.merge(t["locations"][["project_id", "latitude", "longitude", "district"]], on="project_id") \
         .merge(labels, on="project_id")
    m["ratio"] = m.apply(lambda r: r.sanctioned_amount / K.group_median(r.work_type, r.state), axis=1)
    m["sig_ratio"] = m["sanctioned_amount"] / m["estimated_cost"]
    t["m"] = m.set_index("project_id", drop=False)
    return t


def ll(m, pid):
    r = m.loc[pid]
    return (r.latitude, r.longitude)


def bill_dates(bills, pid):
    return sorted(bills.loc[bills.project_id == pid, "bill_date"])


def end_share(m, bills, pid):
    r = m.loc[pid]
    b = bills[bills.project_id == pid]
    S, C = r.start_date, r.actual_completion_date
    cut = C - (C - S) * K.ENDLOAD_WINDOW
    return b.loc[b.bill_date > cut, "claimed_amount"].sum() / b["claimed_amount"].sum()


def max_burst(dates, k):
    """smallest span (days) containing k bills"""
    return min((dates[i + k - 1] - dates[i]).days for i in range(len(dates) - k + 1)) if len(dates) >= k else 10 ** 6


# --------------------------------------------------------------------------- #
# (a) data quality
# --------------------------------------------------------------------------- #
def test_unique_ids(d):
    for name, col in [("projects", "project_id"), ("contractors", "contractor_id"), ("bills", "bill_id"),
                      ("payments", "payment_id"), ("locations", "location_id"),
                      ("historical_projects", "historical_project_id"), ("project_contractors", "relationship_id")]:
        assert d[name][col].is_unique, f"{name}.{col} not unique"
    assert d["projects"]["project_code"].is_unique


def test_foreign_keys(d):
    P, C, L, B = set(d["projects"].project_id), set(d["contractors"].contractor_id), set(d["locations"].location_id), set(d["bills"].bill_id)
    assert set(d["projects"].contractor_id) <= C
    assert set(d["projects"].location_id) == L
    assert set(d["locations"].project_id) == P
    assert set(d["bills"].project_id) <= P and set(d["bills"].contractor_id) <= C
    assert set(d["payments"].bill_id) <= B and set(d["payments"].project_id) <= P
    assert set(d["project_contractors"].project_id) == P and set(d["project_contractors"].contractor_id) <= C
    assert set(d["historical_projects"].contractor_id) <= C
    assert set(d["labels"].project_id) == P and d["labels"].project_id.is_unique


def test_no_duplicate_rows(d):
    for name, df in d.items():
        if name in ("m", "labels"):
            continue
        assert not df.duplicated().any(), f"duplicate rows in {name}"
    pr = d["projects"]
    assert not pr.duplicated(["project_description", "sanction_date", "contractor_id"]).any()


def test_dates_valid_and_ordered(d):
    p = d["projects"]
    assert (p.sanction_date <= p.work_order_date).all()
    assert (p.work_order_date <= p.start_date).all()
    assert (p.start_date < p.expected_completion_date).all()
    done = p[p.project_status == "Completed"]
    assert done.actual_completion_date.notna().all() and (done.actual_completion_date > done.start_date).all()
    assert p.loc[p.project_status != "Completed", "actual_completion_date"].isna().all()
    b = d["bills"]
    assert (b.work_period_start <= b.work_period_end).all()
    assert (b.work_period_end <= b.submission_date).all() and (b.submission_date <= b.approval_date).all()
    assert (b.bill_date >= b.work_period_end).all()
    pay = d["payments"].merge(b[["bill_id", "approval_date", "approved_amount"]], on="bill_id")
    assert (pay.payment_date >= pay.approval_date).all()
    asof = pd.Timestamp(K.AS_OF_DATE)
    assert (pay.payment_date <= asof).all() and (b.approval_date <= asof).all()
    assert (d["historical_projects"].completion_date < p.sanction_date.min()).all()


def test_numeric_values(d):
    p = d["projects"]
    for c in ["sanctioned_amount", "estimated_cost", "approved_amount", "actual_expenditure"]:
        assert (p[c] > 0).all(), c
    assert p.completion_percentage.between(0, 100).all()
    b = d["bills"]
    assert (b.claimed_amount > 0).all() and (b.approved_amount > 0).all() and (b.approved_amount <= b.claimed_amount).all()
    pay = d["payments"].groupby("bill_id").payment_amount.sum().reset_index().merge(b[["bill_id", "approved_amount"]])
    assert (pay.payment_amount <= pay.approved_amount + 0.01).all()
    h = d["historical_projects"]
    assert (h.sanctioned_amount > 0).all() and (h.actual_expenditure > 0).all()
    loc = d["locations"]
    assert loc.latitude.between(6, 38).all() and loc.longitude.between(68, 98).all()
    # project actual expenditure equals approved billing
    tot = d["bills"].groupby("project_id").approved_amount.sum()
    chk = p.set_index("project_id").actual_expenditure
    assert ((chk - tot.reindex(chk.index)).abs() < 0.05).all()


def test_contractor_aggregates(d):
    p = d["projects"].groupby("contractor_id").agg(n=("project_id", "size"), v=("sanctioned_amount", "sum"))
    c = d["contractors"].set_index("contractor_id")
    for cid, row in c.iterrows():
        n, v = (p.loc[cid, "n"], p.loc[cid, "v"]) if cid in p.index else (0, 0.0)
        assert row.total_projects == n and abs(row.total_project_value - v) < 0.05


def test_project_contractor_consistency(d):
    j = d["projects"].merge(d["project_contractors"], on="project_id", suffixes=("", "_rel"))
    assert (j.contractor_id == j.contractor_id_rel).all()
    assert (j.sanctioned_amount - j.contract_value).abs().max() < 0.01
    assert (j.work_order_date == j.award_date).all()


def test_ids_disjoint_from_v1_range(d):
    nums = d["projects"].project_id.str[2:].astype(int)
    assert nums.min() >= 5001, "evaluation project IDs must not collide with V1 P-1001..P-1200"


# --------------------------------------------------------------------------- #
# (b) leakage controls
# --------------------------------------------------------------------------- #
def test_no_label_columns_in_engine_input():
    for fn in ENGINE_FILES:
        if fn == "anomaly_signals.csv":
            continue   # V1-schema placeholder, header only; zero rows is asserted separately
        cols = set(pd.read_csv(os.path.join(ENG, fn), nrows=0).columns)
        assert not (cols & K.BANNED_ENGINE_COLUMNS), (fn, cols & K.BANNED_ENGINE_COLUMNS)


def test_labels_not_inside_engine_dir():
    assert not os.path.exists(os.path.join(ENG, "evaluation_labels.csv"))
    assert sorted(os.listdir(ENG)) == sorted(ENGINE_FILES)


def test_anomaly_signals_placeholder_is_empty():
    df = pd.read_csv(os.path.join(ENG, "anomaly_signals.csv"))
    assert len(df) == 0


def test_engine_input_has_no_scenario_words_in_text(d):
    banned = ["ANOMAL", "ADVERSARIAL", "GRP-", "OBVIOUS", "BORDERLINE", "COST_INFLATION", "DUPLICATE_LIKE"]
    for name in ("projects", "contractors", "locations", "bills", "payments"):
        txt = d[name].astype(str).to_csv()
        for w in banned:
            assert w not in txt.upper() or w == "ANOMAL" and False, (name, w)


def test_generator_and_runner_isolation():
    import ast
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def inspect(path):
        tree = ast.parse(open(path, encoding="utf-8").read())
        mods, names, consts = set(), set(), []
        docstrings = set()   # explanatory docstrings are documentation, not path access
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
                    and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) \
                    and isinstance(node.body[0].value.value, str):
                docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                consts.append(node.value)
        return mods, names, consts

    mods, names, consts = inspect(os.path.join(base, "generate_evaluation_data.py"))
    assert not any(m.startswith("intelligence") for m in mods), "generator must not import the V1 engine"
    assert "read_csv" not in names and "load_dataset" not in names, "generator must not read any CSV"
    assert not any(c.strip("/") == "data-source" or "data-source/data" in c or "data-source" + os.sep + "data" in c for c in consts), \
        "generator must not build paths into the V1 data folder"
    runner = os.path.join(base, "run_v1_predictions.py")
    if os.path.exists(runner):
        _, rnames, rconsts = inspect(runner)
        assert not any("evaluation_labels" in c or "ground_truth" in c for c in rconsts), "runner must not touch labels"


def test_ids_do_not_leak_scenario_order(d):
    """IDs were shuffled: scenario type must not correlate with ID rank."""
    m = d["m"].reset_index(drop=True).sort_values("project_id").reset_index(drop=True)
    ranks = pd.Series(range(len(m)), index=m.index)
    anomalous = (m.ground_truth_label == "ANOMALOUS").astype(int)
    corr = anomalous.corr(ranks)
    assert abs(corr) < 0.25, corr
    # first third of the file must not be dominated by one scenario
    first = m.iloc[: len(m) // 3].scenario_type.value_counts(normalize=True)
    assert first.max() < 0.7


# --------------------------------------------------------------------------- #
# metadata / determinism
# --------------------------------------------------------------------------- #
def test_metadata_matches_files(d):
    meta = json.load(open(os.path.join(EVAL_DIR, "evaluation_metadata.json"), encoding="utf-8"))
    L = d["labels"]
    assert meta["number_of_cases"] == len(L) == K.N_PROJECTS
    assert meta["number_anomalous"] == (L.ground_truth_label == "ANOMALOUS").sum()
    assert meta["number_normal"] == (L.ground_truth_label == "NORMAL").sum()
    assert meta["scenario_distribution"] == L.scenario_type.value_counts().sort_index().to_dict()
    assert meta["adversarial_negative_count"] == (L.scenario_type == "ADVERSARIAL_NORMAL").sum() >= 25
    for rel, h in meta["file_sha256"].items():
        assert hashlib.sha256(open(os.path.join(EVAL_DIR, rel), "rb").read()).hexdigest() == h, f"hash mismatch {rel}"
    for k in ["dataset_version", "creation_method", "label_definition", "independence_statement",
              "leakage_controls", "known_limitations", "scenario_construction"]:
        assert meta[k]
    assert "real MPLADS ground truth" in " ".join(meta["known_limitations"])


def test_label_vocabulary(d):
    L = d["labels"]
    assert set(L.ground_truth_label) == {"NORMAL", "ANOMALOUS"}
    assert set(L.scenario_type) <= {"NORMAL", "COST_ANOMALY", "BILLING_ANOMALY", "CONTRACTOR_PATTERN", "SIMILAR_PROJECT",
                                    "GEOGRAPHIC_PATTERN", "MULTI_SIGNAL", "ADVERSARIAL_NORMAL"}
    anom = L[L.ground_truth_label == "ANOMALOUS"]
    assert set(anom.difficulty) == {"OBVIOUS", "BORDERLINE"} and (anom.injected_signals != "").all()
    norm = L[L.ground_truth_label == "NORMAL"]
    assert (norm.injected_signals == "").all() and (norm.rationale != "").all()
    assert (L.rationale != "").all()
    for sc in ["COST_ANOMALY", "BILLING_ANOMALY", "CONTRACTOR_PATTERN", "SIMILAR_PROJECT", "GEOGRAPHIC_PATTERN", "MULTI_SIGNAL"]:
        diffs = set(L.loc[L.scenario_type == sc, "difficulty"])
        assert {"OBVIOUS", "BORDERLINE"} <= diffs or sc == "MULTI_SIGNAL", sc


def test_generation_is_deterministic():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        ma, mb = generate(a), generate(b)
        assert ma["file_sha256"] == mb["file_sha256"]


# --------------------------------------------------------------------------- #
# (c) label-consistency: every label rule re-derived from raw data
# --------------------------------------------------------------------------- #
def _members(m, sig_token):
    return m[m.injected_signals.str.contains(sig_token)]


def test_cost_rule(d):
    m = d["m"]
    c = _members(m, "COST_INFLATION")
    assert len(c) == 8 + 6 + 2   # COST_ANOMALY + MULTI cost+billing + MULTI duplicate pair
    assert (c.ratio >= K.COST_RATIO_MIN).all()
    assert (c.sig_ratio >= K.COST_SANCTION_OVER_ESTIMATE_MIN).all()
    for _, r in c[c.scenario_type == "COST_ANOMALY"].iterrows():
        lo, hi = K.COST_OBVIOUS if r.difficulty == "OBVIOUS" else K.COST_BORDERLINE
        assert lo - 1e-6 <= r.ratio <= hi + 1e-6


def test_billing_rules(d):
    m, b = d["m"], d["bills"]
    comp = _members(m, "BILLING_COMPRESSION")
    for pid, r in comp.iterrows():
        cfg = K.COMPRESS_OBVIOUS if r.difficulty == "OBVIOUS" else K.COMPRESS_BORDERLINE
        assert max_burst(bill_dates(b, pid), cfg["bills"]) <= cfg["span_days"], pid
        assert end_share(m, b, pid) < K.ENDLOAD_MIN_SHARE, f"{pid}: compression case should not also be end-loaded"
    endl = _members(m, "BILLING_ENDLOAD")
    for pid, r in endl.iterrows():
        s = end_share(m, b, pid)
        lo, hi = K.ENDLOAD_OBVIOUS if r.difficulty == "OBVIOUS" else K.ENDLOAD_BORDERLINE
        assert lo - 0.005 <= s <= hi + 0.12, (pid, s)
        assert s >= K.ENDLOAD_MIN_SHARE
        assert max_burst(bill_dates(b, pid), 3) > 20, f"{pid}: end-load case should not also be compressed"
    assert len(comp) == 4 + 2 and len(endl) == 4 + 4   # BILLING_ANOMALY + MULTI_SIGNAL members


def test_contractor_pattern_rule(d):
    m = d["m"]
    for gid, g in m[m.group_id.str.startswith("GRP-CP")].groupby("group_id"):
        assert len(g) >= K.CP_MIN_MEMBERS and g.contractor_id.nunique() == 1 and g.work_type.nunique() == 1
        assert (g.work_order_date.max() - g.work_order_date.min()).days <= K.CP_WORK_ORDER_SPAN_MAX
        assert (g.ratio >= K.CP_RATIO_MIN).all()
        assert (g.ratio < K.COST_RATIO_MIN).all(), "CP members must not also be cost anomalies"
        for a, b2 in itertools.combinations(g.index, 2):
            assert haversine_km(ll(m, a), ll(m, b2)) >= K.CP_MIN_DISTANCE_KM
        others = m[(m.contractor_id == g.contractor_id.iloc[0]) & ~m.index.isin(g.index)]
        assert len(others) == 2 and (others.scenario_type == "NORMAL").all()
        assert (others.ratio < g.ratio.min()).all(), "contractor's other projects are cheaper"
        for _, o in others.iterrows():
            assert abs((o.work_order_date - g.work_order_date).dt.days).min() >= 150 if hasattr(o.work_order_date, "dt") else \
                min(abs((o.work_order_date - w).days) for w in g.work_order_date) >= 150


def test_similar_rule(d):
    m = d["m"]
    for gid, g in m[m.group_id.str.match(r"GRP-(SIM|MULTI)")].groupby("group_id"):
        assert len(g) == 2
        a, c = g.iloc[0], g.iloc[1]
        assert a.work_type == c.work_type and a.district == c.district
        assert abs((a.sanction_date - c.sanction_date).days) <= K.SIM_MAX_SANCTION_GAP_DAYS
        assert haversine_km(ll(m, a.name), ll(m, c.name)) <= K.SIM_MAX_DISTANCE_KM
        mean = (a.sanctioned_amount + c.sanctioned_amount) / 2
        assert abs(a.sanctioned_amount - c.sanctioned_amount) / mean <= K.SIM_MAX_AMOUNT_DIFF
        if gid.startswith("GRP-SIM"):
            assert (g.ratio < K.COST_RATIO_MIN).all()


def test_geographic_rule(d):
    m = d["m"]
    for gid, g in m[m.group_id.str.startswith("GRP-GEO")].groupby("group_id"):
        assert len(g) >= K.GEO_MIN_MEMBERS and g.contractor_id.nunique() == 1 and g.work_type.nunique() == 1
        lat, lon = g.latitude.mean(), g.longitude.mean()
        assert max(haversine_km((r.latitude, r.longitude), (lat, lon)) for _, r in g.iterrows()) <= K.GEO_MAX_CENTROID_KM
        mean = g.sanctioned_amount.mean()
        assert ((g.sanctioned_amount - mean).abs() / mean <= K.GEO_MAX_AMOUNT_DEVIATION).all()
        dts = sorted(g.sanction_date)
        assert all((y - x).days >= K.GEO_MIN_SANCTION_GAP_DAYS for x, y in zip(dts, dts[1:]))
        assert g.project_description.nunique() == len(g)
        assert (g.ratio < K.COST_RATIO_MIN).all()


def test_plain_normal_rules(d):
    m, b = d["m"], d["bills"]
    n = m[m.scenario_type == "NORMAL"]
    assert len(n) >= 50
    for pid, r in n.iterrows():
        sig = K.SIGMA[r.work_type]
        assert abs(math.log(r.ratio)) <= K.PLAIN_Z_MAX * sig + 1e-6, pid
        assert r.sig_ratio <= K.PLAIN_SANCTION_OVER_ESTIMATE_MAX
        ds = bill_dates(b, pid)
        assert max_burst(ds, 3) >= K.PLAIN_MIN_BILL_SPAN_DAYS, pid
        if r.project_status == "Completed":
            assert end_share(m, b, pid) <= K.PLAIN_END_SHARE_MAX, pid
        others = [haversine_km(ll(m, pid), ll(m, o)) for o in m.index if o != pid]
        assert min(others) >= K.PLAIN_ISOLATION_KM - 1e-6, pid
    per_c = n.groupby("contractor_id").size()
    assert per_c.max() <= K.PLAIN_CONTRACTOR_CAP
    for cid, g in n.groupby("contractor_id"):
        w = sorted(g.work_order_date)
        assert all((y - x).days >= 120 for x, y in zip(w, w[1:]))


def test_adversarial_a(d):
    m = d["m"]
    a = m[m.adversarial_subtype == "A"]
    for gid, g in a.groupby("group_id"):
        assert len(g) >= K.ADVA_MIN_PROJECTS and g.contractor_id.nunique() == 1
        w = sorted(g.work_order_date)
        assert all((y - x).days >= K.ADVA_MIN_WO_GAP_DAYS for x, y in zip(w, w[1:]))
        assert g.work_type.nunique() >= K.ADVA_MIN_WORK_TYPES
        assert g.ratio.between(*K.ADVA_RATIO_RANGE).all()
        for x, y in itertools.combinations(g.index, 2):
            assert haversine_km(ll(m, x), ll(m, y)) >= K.ADVA_MIN_DISTANCE_KM


def test_adversarial_b(d):
    m = d["m"]
    for gid, g in m[m.adversarial_subtype == "B"].groupby("group_id"):
        assert len(g) == 3 and g.work_type.nunique() == 3 and g.contractor_id.nunique() == 3
        assert g.ratio.between(*K.ADVB_RATIO_RANGE).all()
        dts = sorted(g.sanction_date)
        assert all((y - x).days >= 60 for x, y in zip(dts, dts[1:]))
        for x, y in itertools.combinations(g.index, 2):
            assert haversine_km(ll(m, x), ll(m, y)) <= K.ADVB_MAX_PAIR_KM


def test_adversarial_c(d):
    m = d["m"]
    c = m[m.adversarial_subtype == "C"]
    assert len(c) == 5
    assert (c.ratio >= K.ADVC_RATIO_MIN).all() and (c.sig_ratio <= K.ADVC_SANCTION_OVER_ESTIMATE_MAX).all()
    assert c.project_description.str.contains(",").all()


def test_adversarial_d(d):
    m, b = d["m"], d["bills"]
    for pid, r in m[m.adversarial_subtype == "D"].iterrows():
        s = end_share(m, b, pid)
        assert K.ADVD_FINAL_SHARE[0] <= s <= K.ADVD_FINAL_SHARE[1] + 0.02, (pid, s)
        ds = bill_dates(b, pid)
        assert all((y - x).days >= K.ADVD_MIN_BILL_GAP_DAYS for x, y in zip(ds, ds[1:])), pid
        assert (b.project_id == pid).sum() == 4


def test_adversarial_e(d):
    m = d["m"]
    for gid, g in m[m.adversarial_subtype == "E"].groupby("group_id"):
        a, c = g.iloc[0], g.iloc[1]
        assert a.work_type == c.work_type and a.district == c.district and a.contractor_id != c.contractor_id
        assert haversine_km(ll(m, a.name), ll(m, c.name)) >= K.ADVE_MIN_DISTANCE_KM
        assert abs((a.sanction_date - c.sanction_date).days) >= K.ADVE_MIN_SANCTION_GAP_DAYS
        mean = (a.sanctioned_amount + c.sanctioned_amount) / 2
        assert abs(a.sanctioned_amount - c.sanctioned_amount) / mean >= K.ADVE_MIN_AMOUNT_DIFF
        # same wording template, different village
        assert a.project_description != c.project_description


def test_scenario_counts(d):
    L = d["labels"]
    vc = L.scenario_type.value_counts().to_dict()
    assert vc == {"NORMAL": 60, "ADVERSARIAL_NORMAL": 41, "COST_ANOMALY": 8, "BILLING_ANOMALY": 8,
                  "CONTRACTOR_PATTERN": 9, "SIMILAR_PROJECT": 8, "GEOGRAPHIC_PATTERN": 8, "MULTI_SIGNAL": 8}
    assert L.loc[L.adversarial_subtype != "", "adversarial_subtype"].value_counts().to_dict() == {"A": 14, "B": 9, "C": 5, "D": 5, "E": 8}


def test_engine_loader_can_read_input():
    """Loader smoke test only - no scoring."""
    try:
        from intelligence.data_loader import load_dataset
    except Exception:
        pytest.skip("intelligence package not importable")
    ds = load_dataset(ENG)
    assert len(ds.projects) == K.N_PROJECTS and len(ds.anomaly_signals) == 0
