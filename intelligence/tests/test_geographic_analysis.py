import pandas as pd

from intelligence.geographic_analysis import GeographicIndex


def _projects_df(rows):
    return pd.DataFrame(rows)


def test_isolated_project_scores_zero():
    projects = _projects_df([
        {"project_id": "P-A", "work_type": "Concrete Road", "contractor_id": "C-01", "sanctioned_amount": 1_000_000.0},
        {"project_id": "P-B", "work_type": "Street Lighting", "contractor_id": "C-02", "sanctioned_amount": 500_000.0},
    ])
    locations = pd.DataFrame([
        {"project_id": "P-A", "latitude": 10.0, "longitude": 78.0},
        {"project_id": "P-B", "latitude": 25.0, "longitude": 90.0},  # far away
    ])
    idx = GeographicIndex(projects, locations)
    result = idx.score("P-A")
    assert result.score == 0.0
    assert result.detected is False


def test_proximity_alone_without_shared_attributes_not_flagged():
    projects = _projects_df([
        {"project_id": "P-A", "work_type": "Concrete Road", "contractor_id": "C-01", "sanctioned_amount": 1_000_000.0},
        {"project_id": "P-B", "work_type": "Street Lighting", "contractor_id": "C-02", "sanctioned_amount": 5_000_000.0},
        {"project_id": "P-C", "work_type": "Drainage System", "contractor_id": "C-03", "sanctioned_amount": 8_000_000.0},
    ])
    locations = pd.DataFrame([
        {"project_id": "P-A", "latitude": 10.0000, "longitude": 78.0000},
        {"project_id": "P-B", "latitude": 10.0050, "longitude": 78.0050},
        {"project_id": "P-C", "latitude": 10.0080, "longitude": 78.0080},
    ])
    idx = GeographicIndex(projects, locations)
    result = idx.score("P-A")
    # Nearby, but nothing shares work type, contractor, or comparable cost
    assert result.detected is False


def test_tight_cluster_with_shared_attributes_is_detected():
    projects = _projects_df([
        {"project_id": "P-A", "work_type": "Concrete Road", "contractor_id": "C-01", "sanctioned_amount": 1_000_000.0},
        {"project_id": "P-B", "work_type": "Concrete Road", "contractor_id": "C-01", "sanctioned_amount": 1_050_000.0},
        {"project_id": "P-C", "work_type": "Concrete Road", "contractor_id": "C-01", "sanctioned_amount": 980_000.0},
    ])
    locations = pd.DataFrame([
        {"project_id": "P-A", "latitude": 10.0000, "longitude": 78.0000},
        {"project_id": "P-B", "latitude": 10.0020, "longitude": 78.0020},
        {"project_id": "P-C", "latitude": 10.0030, "longitude": 78.0010},
    ])
    idx = GeographicIndex(projects, locations)
    result = idx.score("P-A")
    assert result.detected is True
    assert result.score > 0
    assert result.score <= result.max_score


def test_score_never_exceeds_max():
    projects = _projects_df([
        {"project_id": f"P-{i}", "work_type": "Concrete Road", "contractor_id": "C-01", "sanctioned_amount": 1_000_000.0}
        for i in range(6)
    ])
    locations = pd.DataFrame([
        {"project_id": f"P-{i}", "latitude": 10.0 + i * 0.0001, "longitude": 78.0 + i * 0.0001}
        for i in range(6)
    ])
    idx = GeographicIndex(projects, locations)
    result = idx.score("P-0")
    assert result.score <= result.max_score


def test_real_dataset_p1023_geographic_signal_detected(dataset):
    from intelligence.geographic_analysis import build_geographic_index
    idx = build_geographic_index(dataset.projects, dataset.locations)
    result = idx.score("P-1023")
    assert result.detected is True
    assert result.score > 0
