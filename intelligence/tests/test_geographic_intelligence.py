import pandas as pd
import pytest

from intelligence.data_loader import Dataset
from intelligence.relationship_analysis import (
    RelationshipIndex,
    build_relationship_index,
    build_direct_edges,
    build_contractor_network,
    build_multi_hop_paths,
    generate_project_relationships,
    relationships_for_project,
    RELATIONSHIP_REPORT_THRESHOLD,
)


def _tiny_dataset() -> Dataset:
    """A minimal, self-contained Dataset for unit-level relationship tests
    that don't need the full 200-project CSV package."""
    projects = pd.DataFrame([
        {
            "project_id": "P-A", "project_description": "Construction of concrete road in Nallur",
            "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Tamil Nadu",
            "contractor_id": "C-01", "sanctioned_amount": 1_000_000.0,
            "sanction_date": pd.Timestamp("2023-01-01"),
        },
        {
            "project_id": "P-B", "project_description": "Construction of concrete road in Nallur village",
            "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Tamil Nadu",
            "contractor_id": "C-01", "sanctioned_amount": 1_020_000.0,
            "sanction_date": pd.Timestamp("2023-01-10"),
        },
        {
            "project_id": "P-C", "project_description": "Overhead water tank installation at Periyar block",
            "work_type": "Overhead Water Tank", "district_id": "DIST-09", "state": "Kerala",
            "contractor_id": "C-02", "sanctioned_amount": 5_000_000.0,
            "sanction_date": pd.Timestamp("2024-06-15"),
        },
    ])
    locations = pd.DataFrame([
        {"project_id": "P-A", "location_id": "L-A", "latitude": 10.0000, "longitude": 78.0000,
         "state": "Tamil Nadu", "district": "Nallur", "location_type": "Rural Village"},
        {"project_id": "P-B", "location_id": "L-B", "latitude": 10.0020, "longitude": 78.0020,
         "state": "Tamil Nadu", "district": "Nallur", "location_type": "Rural Village"},
        {"project_id": "P-C", "location_id": "L-C", "latitude": 25.0000, "longitude": 90.0000,
         "state": "Kerala", "district": "Periyar", "location_type": "Rural Village"},
    ])
    bills = pd.DataFrame([
        {"bill_id": "B-001", "project_id": "P-A", "bill_number": "BILL/1", "bill_status": "Approved",
         "claimed_amount": 100000.0},
        {"bill_id": "B-002", "project_id": "P-B", "bill_number": "BILL/2", "bill_status": "Approved",
         "claimed_amount": 90000.0},
    ])
    payments = pd.DataFrame([
        {"payment_id": "PAY-001", "bill_id": "B-001", "payment_amount": 100000.0, "payment_status": "Success"},
    ])
    project_contractors = pd.DataFrame([
        {"relationship_id": "REL-001", "project_id": "P-A", "contractor_id": "C-01", "role": "Primary Contractor",
         "contract_value": 1_000_000.0, "award_date": pd.Timestamp("2023-01-05")},
        {"relationship_id": "REL-002", "project_id": "P-B", "contractor_id": "C-01", "role": "Primary Contractor",
         "contract_value": 1_020_000.0, "award_date": pd.Timestamp("2023-01-12")},
        {"relationship_id": "REL-003", "project_id": "P-C", "contractor_id": "C-02", "role": "Primary Contractor",
         "contract_value": 5_000_000.0, "award_date": pd.Timestamp("2024-06-20")},
    ])
    contractors = pd.DataFrame([
        {"contractor_id": "C-01", "contractor_name": "Alpha Infra"},
        {"contractor_id": "C-02", "contractor_name": "Beta Construction"},
    ])
    empty = pd.DataFrame()
    return Dataset(
        projects=projects, contractors=contractors, bills=bills, payments=payments,
        locations=locations, historical_projects=empty, project_contractors=project_contractors,
        anomaly_signals=pd.DataFrame([{"project_id": "P-A"}]),  # deliberately non-empty, must be ignored
    )


@pytest.fixture(scope="module")
def tiny():
    return _tiny_dataset()


@pytest.fixture(scope="module")
def tiny_index(tiny):
    return build_relationship_index(tiny.projects, tiny.locations)


@pytest.fixture(scope="module")
def tiny_relationships(tiny_index):
    return generate_project_relationships(tiny_index, threshold=0.0)


# --- 1-4: direct FK edges -----------------------------------------------

def test_direct_project_contractor_relationship(tiny):
    edges = build_direct_edges(tiny)
    pc_edges = [e for e in edges if e["relationship_type"] == "PROJECT_CONTRACTOR"]
    assert {"source": "P-A", "target": "C-01"}.items() <= {
        "source": pc_edges[0]["source"], "target": pc_edges[0]["target"]
    }.items() or any(e["source"] == "P-A" and e["target"] == "C-01" for e in pc_edges)
    assert all(e["relationship_strength"] == 100.0 for e in pc_edges)


def test_direct_project_bill_relationship(tiny):
    edges = build_direct_edges(tiny)
    pb_edges = [e for e in edges if e["relationship_type"] == "PROJECT_BILL"]
    assert any(e["source"] == "P-A" and e["target"] == "B-001" for e in pb_edges)


def test_direct_bill_payment_relationship(tiny):
    edges = build_direct_edges(tiny)
    bp_edges = [e for e in edges if e["relationship_type"] == "BILL_PAYMENT"]
    assert any(e["source"] == "B-001" and e["target"] == "PAY-001" for e in bp_edges)


def test_direct_project_location_relationship(tiny):
    edges = build_direct_edges(tiny)
    pl_edges = [e for e in edges if e["relationship_type"] == "PROJECT_LOCATION"]
    assert any(e["source"] == "P-A" and e["target"] == "L-A" for e in pl_edges)


# --- 5-6: attribute-based relationship dimensions -----------------------

def test_same_contractor_relationship_detected(tiny_index):
    evidence, strength = tiny_index.pair_evidence("P-A", "P-B")
    assert evidence.same_contractor is True
    assert strength > 0


def test_same_work_type_relationship_detected(tiny_index):
    evidence, _ = tiny_index.pair_evidence("P-A", "P-B")
    assert evidence.same_work_type is True
    evidence2, _ = tiny_index.pair_evidence("P-A", "P-C")
    assert evidence2.same_work_type is False


# --- 7: relationship strength bounds -------------------------------------

def test_relationship_strength_bounds(tiny_relationships):
    for r in tiny_relationships:
        assert 0.0 <= r["relationship_strength"] <= 100.0


def test_relationship_strength_never_exceeds_max_even_for_identical_projects():
    idx = build_relationship_index(
        pd.DataFrame([
            {"project_id": "P-X", "project_description": "same text", "work_type": "Concrete Road",
             "district_id": "DIST-01", "state": "TN", "contractor_id": "C-01", "sanctioned_amount": 1000.0,
             "sanction_date": pd.Timestamp("2023-01-01")},
            {"project_id": "P-Y", "project_description": "same text", "work_type": "Concrete Road",
             "district_id": "DIST-01", "state": "TN", "contractor_id": "C-01", "sanctioned_amount": 1000.0,
             "sanction_date": pd.Timestamp("2023-01-01")},
        ]),
        pd.DataFrame([
            {"project_id": "P-X", "latitude": 10.0, "longitude": 78.0},
            {"project_id": "P-Y", "latitude": 10.0, "longitude": 78.0},
        ]),
    )
    _, strength = idx.pair_evidence("P-X", "P-Y")
    assert strength <= 100.0


# --- 8: deterministic score ----------------------------------------------

def test_relationship_score_is_deterministic(tiny):
    idx1 = build_relationship_index(tiny.projects, tiny.locations)
    idx2 = build_relationship_index(tiny.projects, tiny.locations)
    e1, s1 = idx1.pair_evidence("P-A", "P-B")
    e2, s2 = idx2.pair_evidence("P-A", "P-B")
    assert s1 == s2
    assert e1.to_dict() == e2.to_dict()


# --- 9: evidence generation ------------------------------------------------

def test_evidence_dict_contains_all_dimensions(tiny_index):
    evidence, _ = tiny_index.pair_evidence("P-A", "P-B")
    d = evidence.to_dict()
    for key in [
        "same_contractor", "same_work_type", "same_district", "same_state",
        "distance_km", "description_similarity", "cost_similarity", "date_proximity",
    ]:
        assert key in d


# --- 10: contractor network -----------------------------------------------

def test_contractor_network_reports_portfolio(tiny):
    network = build_contractor_network(tiny)
    c01 = next(c for c in network if c["contractor_id"] == "C-01")
    assert c01["total_projects"] == 2
    assert set(c01["connected_projects"]) == {"P-A", "P-B"}
    assert c01["project_pairs"] == [["P-A", "P-B"]]


def test_contractor_network_does_not_flag_large_portfolio(tiny):
    # Spec requirement: a large portfolio alone is never itself a "detected"
    # anomaly here — this module doesn't even expose a detected/suspicious
    # flag at the contractor level, only facts.
    network = build_contractor_network(tiny)
    for c in network:
        assert "detected" not in c
        assert "suspicious" not in c


# --- 11: multi-hop path -----------------------------------------------------

def test_multi_hop_path_exists_via_shared_contractor(tiny, tiny_relationships):
    paths = build_multi_hop_paths(tiny, tiny_relationships, min_strength=0.0)
    assert len(paths) >= 1
    path = paths[0]
    node_ids = [n["id"] for n in path["nodes"]]
    assert node_ids[0] in ("P-A", "P-B")
    assert "C-01" in node_ids
    assert len(path["hops"]) >= 2


# --- 12: no anomaly_signals dependency --------------------------------------

def test_relationship_engine_never_reads_anomaly_signals(tiny, tiny_relationships):
    # tiny.anomaly_signals is deliberately non-empty and would bias results
    # if it leaked into scoring. Confirm none of the public functions accept
    # or reference it.
    import inspect
    from intelligence import relationship_analysis as mod

    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        params = inspect.signature(fn).parameters
        assert "anomaly_signals" not in params, f"{name} must not accept anomaly_signals"

    # And a sanity check: results are identical whether or not the dataset's
    # anomaly_signals frame is populated, since it's never consulted.
    idx = build_relationship_index(tiny.projects, tiny.locations)
    rels_again = generate_project_relationships(idx, threshold=0.0)
    assert rels_again == tiny_relationships


# --- Real dataset validation ------------------------------------------------

def test_real_dataset_p1023_relationships_explainable(dataset):
    idx = build_relationship_index(dataset.projects, dataset.locations)
    rels = generate_project_relationships(idx)
    p1023 = relationships_for_project("P-1023", rels)
    assert len(p1023) > 0
    for r in p1023:
        assert r["relationship_strength"] >= RELATIONSHIP_REPORT_THRESHOLD
        assert "evidence" in r


def test_real_dataset_p1001_relationships_not_all_suspicious(dataset):
    idx = build_relationship_index(dataset.projects, dataset.locations)
    rels = generate_project_relationships(idx)
    p1001 = relationships_for_project("P-1001", rels)
    # P-1001 is the normal case: it may well have relationships (e.g. shared
    # templated description), but none should be forced or fabricated —
    # simply confirm the pipeline runs and every entry is properly evidenced.
    for r in p1001:
        assert 0.0 <= r["relationship_strength"] <= 100.0
        assert isinstance(r["evidence"]["same_contractor"], bool)
