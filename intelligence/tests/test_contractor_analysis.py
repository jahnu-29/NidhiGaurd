import pandas as pd

from intelligence.contractor_analysis import score_contractor_pattern, MIN_PORTFOLIO_SIZE


def _row(**overrides):
    base = {"project_id": "P-A", "contractor_id": "C-01", "work_type": "Concrete Road",
            "work_order_date": pd.Timestamp("2023-01-01"), "sanctioned_amount": 1_000_000.0}
    base.update(overrides)
    return pd.Series(base)


def test_small_portfolio_gives_zero_score():
    row = _row()
    projects = pd.DataFrame([row.to_dict()])
    result = score_contractor_pattern(row, projects)
    assert result.portfolio_size < MIN_PORTFOLIO_SIZE
    assert result.score == 0.0
    assert result.detected is False


def test_large_ordinary_portfolio_not_flagged_just_for_size():
    # 10 projects, different work types, spread-out award dates, similar cost -> no cluster
    rows = []
    for i in range(10):
        rows.append({
            "project_id": f"P-{i}", "contractor_id": "C-01",
            "work_type": ["Concrete Road", "Street Lighting", "Drainage System"][i % 3],
            "work_order_date": pd.Timestamp("2023-01-01") + pd.Timedelta(days=i * 90),
            "sanctioned_amount": 1_000_000.0 + i * 1000,
        })
    projects = pd.DataFrame(rows)
    row = pd.Series(rows[0])
    result = score_contractor_pattern(row, projects)
    assert result.portfolio_size == 10
    assert result.detected is False
    assert result.score == 0.0


def test_closely_awarded_higher_cost_cluster_is_detected():
    rows = []
    # 5 unremarkable projects at normal cost, spread out
    for i in range(5):
        rows.append({
            "project_id": f"P-N{i}", "contractor_id": "C-02", "work_type": "Drainage System",
            "work_order_date": pd.Timestamp("2022-01-01") + pd.Timedelta(days=i * 200),
            "sanctioned_amount": 1_000_000.0,
        })
    # 3 closely-awarded, same-work-type, high-cost projects
    for i in range(3):
        rows.append({
            "project_id": f"P-C{i}", "contractor_id": "C-02", "work_type": "Concrete Road",
            "work_order_date": pd.Timestamp("2023-06-01") + pd.Timedelta(days=i * 5),
            "sanctioned_amount": 2_000_000.0,
        })
    projects = pd.DataFrame(rows)
    row = pd.Series(rows[-1])  # one of the clustered high-cost projects
    result = score_contractor_pattern(row, projects)
    assert result.detected is True
    assert result.score > 0
    assert result.score <= result.max_score
    assert len(result.cluster_project_ids) == 3


def test_score_never_exceeds_max_with_extreme_premium():
    rows = []
    for i in range(5):
        rows.append({
            "project_id": f"P-N{i}", "contractor_id": "C-03", "work_type": "Drainage System",
            "work_order_date": pd.Timestamp("2022-01-01") + pd.Timedelta(days=i * 200),
            "sanctioned_amount": 500_000.0,
        })
    for i in range(4):
        rows.append({
            "project_id": f"P-C{i}", "contractor_id": "C-03", "work_type": "Concrete Road",
            "work_order_date": pd.Timestamp("2023-06-01") + pd.Timedelta(days=i * 2),
            "sanctioned_amount": 50_000_000.0,
        })
    projects = pd.DataFrame(rows)
    row = pd.Series(rows[-1])
    result = score_contractor_pattern(row, projects)
    assert result.score <= result.max_score


def test_real_dataset_p1023_contractor_pattern_detected(dataset):
    row = dataset.projects[dataset.projects.project_id == "P-1023"].iloc[0]
    result = score_contractor_pattern(row, dataset.projects)
    assert result.contractor_id == "C-054"
    assert result.detected is True
