import pandas as pd

from intelligence.cost_anomaly import score_cost_anomaly, MIN_COMPARABLES, LOW_PCT


def _project_row(**overrides):
    base = {
        "project_id": "P-TEST", "work_type": "Concrete Road", "state": "Testland",
        "sanctioned_amount": 1_000_000.0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_insufficient_comparables_gives_zero_score():
    row = _project_row(sanctioned_amount=5_000_000.0)
    projects = pd.DataFrame([{"project_id": "P-OTHER", "work_type": "Concrete Road",
                               "state": "Testland", "sanctioned_amount": 1_000_000.0}])
    historical = pd.DataFrame(columns=["work_type", "state", "sanctioned_amount"])
    result = score_cost_anomaly(row, projects, historical)
    assert result.comparable_count < MIN_COMPARABLES
    assert result.score == 0.0
    assert result.detected is False


def test_normal_cost_scores_zero():
    row = _project_row(sanctioned_amount=1_050_000.0)  # 5% above benchmark
    comparables = [{"project_id": f"P-{i}", "work_type": "Concrete Road", "state": "Testland",
                     "sanctioned_amount": 1_000_000.0} for i in range(6)]
    projects = pd.DataFrame(comparables)
    historical = pd.DataFrame(columns=["work_type", "state", "sanctioned_amount"])
    result = score_cost_anomaly(row, projects, historical)
    assert result.comparable_count >= MIN_COMPARABLES
    assert result.percentage_difference < LOW_PCT
    assert result.score == 0.0
    assert result.detected is False


def test_large_cost_overrun_produces_high_score_and_detection():
    row = _project_row(sanctioned_amount=2_000_000.0)  # 100% above benchmark
    comparables = [{"project_id": f"P-{i}", "work_type": "Concrete Road", "state": "Testland",
                     "sanctioned_amount": 1_000_000.0} for i in range(8)]
    projects = pd.DataFrame(comparables)
    historical = pd.DataFrame(columns=["work_type", "state", "sanctioned_amount"])
    result = score_cost_anomaly(row, projects, historical)
    assert result.detected is True
    assert result.score > 15  # meaningfully elevated
    assert result.score <= result.max_score


def test_score_never_exceeds_max_for_extreme_outlier():
    row = _project_row(sanctioned_amount=50_000_000.0)  # absurdly above benchmark
    comparables = [{"project_id": f"P-{i}", "work_type": "Concrete Road", "state": "Testland",
                     "sanctioned_amount": 1_000_000.0} for i in range(8)]
    projects = pd.DataFrame(comparables)
    historical = pd.DataFrame(columns=["work_type", "state", "sanctioned_amount"])
    result = score_cost_anomaly(row, projects, historical)
    assert result.score == result.max_score


def test_real_dataset_p1023_cost_anomaly_detected(dataset):
    row = dataset.projects[dataset.projects.project_id == "P-1023"].iloc[0]
    result = score_cost_anomaly(row, dataset.projects, dataset.historical_projects)
    assert result.comparable_count >= MIN_COMPARABLES
    assert result.percentage_difference is not None and result.percentage_difference > 0
    assert result.detected is True


def test_real_dataset_p1001_cost_anomaly_not_detected(dataset):
    row = dataset.projects[dataset.projects.project_id == "P-1001"].iloc[0]
    result = score_cost_anomaly(row, dataset.projects, dataset.historical_projects)
    assert result.detected is False
