import pandas as pd

from intelligence.billing_analysis import score_billing_anomaly, MIN_BILLS


def _project_row(**overrides):
    base = {
        "project_id": "P-A", "start_date": pd.Timestamp("2023-01-01"),
        "actual_completion_date": pd.Timestamp("2023-12-01"),
        "expected_completion_date": pd.Timestamp("2023-12-01"),
    }
    base.update(overrides)
    return pd.Series(base)


def test_too_few_bills_gives_zero_score():
    row = _project_row()
    bills = pd.DataFrame([{"bill_date": pd.Timestamp("2023-06-01"), "claimed_amount": 100_000.0}])
    result = score_billing_anomaly(row, bills)
    assert len(bills) < MIN_BILLS + 1  # sanity, not the actual assertion
    assert result.score == 0.0
    assert result.detected is False


def test_evenly_spread_bills_not_flagged():
    row = _project_row()
    dates = pd.date_range("2023-01-15", "2023-11-15", periods=5)
    bills = pd.DataFrame([{"bill_date": d, "claimed_amount": 100_000.0} for d in dates])
    result = score_billing_anomaly(row, bills)
    assert result.detected is False
    assert result.score == 0.0


def test_compressed_end_loaded_bills_are_detected():
    row = _project_row(start_date=pd.Timestamp("2023-01-01"), actual_completion_date=pd.Timestamp("2023-12-01"))
    bills = pd.DataFrame([
        {"bill_date": pd.Timestamp("2023-02-01"), "claimed_amount": 100_000.0},
        {"bill_date": pd.Timestamp("2023-11-20"), "claimed_amount": 400_000.0},
        {"bill_date": pd.Timestamp("2023-11-24"), "claimed_amount": 400_000.0},
        {"bill_date": pd.Timestamp("2023-11-27"), "claimed_amount": 400_000.0},
    ])
    result = score_billing_anomaly(row, bills)
    assert result.detected is True
    assert result.score > 0
    assert result.score <= result.max_score


def test_score_never_exceeds_max():
    row = _project_row(start_date=pd.Timestamp("2023-01-01"), actual_completion_date=pd.Timestamp("2023-12-31"))
    bills = pd.DataFrame([
        {"bill_date": pd.Timestamp("2023-12-29"), "claimed_amount": 1_000_000.0},
        {"bill_date": pd.Timestamp("2023-12-30"), "claimed_amount": 1_000_000.0},
        {"bill_date": pd.Timestamp("2023-12-30"), "claimed_amount": 1_000_000.0},
        {"bill_date": pd.Timestamp("2023-12-31"), "claimed_amount": 1_000_000.0},
    ])
    result = score_billing_anomaly(row, bills)
    assert result.score <= result.max_score


def test_real_dataset_p1023_billing_anomaly_detected(dataset):
    row = dataset.projects[dataset.projects.project_id == "P-1023"].iloc[0]
    bills = dataset.bills[dataset.bills.project_id == "P-1023"]
    result = score_billing_anomaly(row, bills)
    assert result.detected is True
    assert result.score > 0


def test_real_dataset_p1001_billing_not_necessarily_flagged(dataset):
    row = dataset.projects[dataset.projects.project_id == "P-1001"].iloc[0]
    bills = dataset.bills[dataset.bills.project_id == "P-1001"]
    result = score_billing_anomaly(row, bills)
    # No assertion that it MUST be zero (some ordinary projects can have mild
    # timing variance) — just confirm it doesn't crash and respects bounds.
    assert 0.0 <= result.score <= result.max_score
