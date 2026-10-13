import pandas as pd

from intelligence.project_similarity import SimilarityIndex


def _projects_df(rows):
    return pd.DataFrame(rows)


def _locations_df(rows):
    return pd.DataFrame(rows)


def test_identical_description_and_attributes_produce_high_similarity():
    projects = _projects_df([
        {"project_id": "P-A", "project_description": "Construction of Concrete Road at Nallur",
         "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Testland",
         "sanctioned_amount": 1_000_000.0, "sanction_date": pd.Timestamp("2023-01-01")},
        {"project_id": "P-B", "project_description": "Construction of Concrete Road at Nallur",
         "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Testland",
         "sanctioned_amount": 1_020_000.0, "sanction_date": pd.Timestamp("2023-01-15")},
        {"project_id": "P-C", "project_description": "Installation of solar street lights",
         "work_type": "Street Lighting", "district_id": "DIST-02", "state": "Testland",
         "sanctioned_amount": 400_000.0, "sanction_date": pd.Timestamp("2023-06-01")},
    ])
    locations = _locations_df([
        {"project_id": "P-A", "latitude": 10.0, "longitude": 78.0},
        {"project_id": "P-B", "latitude": 10.001, "longitude": 78.001},
        {"project_id": "P-C", "latitude": 22.0, "longitude": 88.0},
    ])
    idx = SimilarityIndex(projects, locations)
    result = idx.score("P-A")
    assert result.detected is True
    assert result.matches[0].project_id == "P-B"
    assert result.score > 0


def test_dissimilar_projects_score_zero():
    projects = _projects_df([
        {"project_id": "P-A", "project_description": "Construction of Concrete Road at Nallur",
         "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Testland",
         "sanctioned_amount": 1_000_000.0, "sanction_date": pd.Timestamp("2023-01-01")},
        {"project_id": "P-C", "project_description": "Installation of solar street lights at a village far away",
         "work_type": "Street Lighting", "district_id": "DIST-09", "state": "Otherland",
         "sanctioned_amount": 9_000_000.0, "sanction_date": pd.Timestamp("2021-01-01")},
    ])
    locations = _locations_df([
        {"project_id": "P-A", "latitude": 10.0, "longitude": 78.0},
        {"project_id": "P-C", "latitude": 30.0, "longitude": 90.0},
    ])
    idx = SimilarityIndex(projects, locations)
    result = idx.score("P-A")
    assert result.score == 0.0
    assert result.detected is False


def test_score_never_exceeds_max():
    projects = _projects_df([
        {"project_id": "P-A", "project_description": "Same text here",
         "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Testland",
         "sanctioned_amount": 1_000_000.0, "sanction_date": pd.Timestamp("2023-01-01")},
        {"project_id": "P-B", "project_description": "Same text here",
         "work_type": "Concrete Road", "district_id": "DIST-01", "state": "Testland",
         "sanctioned_amount": 1_000_000.0, "sanction_date": pd.Timestamp("2023-01-01")},
    ])
    locations = _locations_df([
        {"project_id": "P-A", "latitude": 10.0, "longitude": 78.0},
        {"project_id": "P-B", "latitude": 10.0, "longitude": 78.0},
    ])
    idx = SimilarityIndex(projects, locations)
    result = idx.score("P-A")
    assert result.score <= result.max_score


def test_real_dataset_p1023_similarity_detected(dataset):
    from intelligence.project_similarity import build_similarity_index
    idx = build_similarity_index(dataset.projects, dataset.locations)
    result = idx.score("P-1023")
    assert result.score > 0
    assert len(result.matches) > 0
