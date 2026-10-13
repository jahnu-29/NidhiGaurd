import math

import pandas as pd

from intelligence.risk_engine import classify_risk_level, DISCLAIMER


def test_risk_level_classification_boundaries():
    assert classify_risk_level(0) == "LOW"
    assert classify_risk_level(29.9) == "LOW"
    assert classify_risk_level(30) == "MEDIUM"
    assert classify_risk_level(59.9) == "MEDIUM"
    assert classify_risk_level(60) == "HIGH"
    assert classify_risk_level(79.9) == "HIGH"
    assert classify_risk_level(80) == "CRITICAL"
    assert classify_risk_level(100) == "CRITICAL"


def test_risk_score_is_sum_of_components(engine):
    result = engine.score_project("P-1023")
    component_sum = sum(c["score"] for c in result.components.values())
    assert math.isclose(result.risk_score, min(100.0, component_sum), rel_tol=1e-6)


def test_disclaimer_present_on_every_result(all_results):
    for r in all_results:
        assert r.disclaimer == DISCLAIMER


def test_p1023_is_high_or_critical_and_all_five_detectors_fire(engine):
    result = engine.score_project("P-1023")
    assert result.risk_level in ("HIGH", "CRITICAL")
    for name, comp in result.components.items():
        assert comp["detected"] is True, f"{name} did not independently detect a signal for the hero case"


def test_p1001_scores_materially_lower_than_p1023(engine):
    p1023 = engine.score_project("P-1023")
    p1001 = engine.score_project("P-1001")
    assert p1001.risk_score < p1023.risk_score
    assert p1001.risk_level in ("LOW", "MEDIUM")


def test_p1023_ranks_at_or_near_top_of_full_batch(all_results):
    ranked = sorted(all_results, key=lambda r: r.risk_score, reverse=True)
    top_ids = [r.project_id for r in ranked[:5]]
    assert "P-1023" in top_ids


def test_no_result_exceeds_100(all_results):
    for r in all_results:
        assert 0.0 <= r.risk_score <= 100.0


def test_no_component_exceeds_its_max(all_results):
    for r in all_results:
        for name, comp in r.components.items():
            assert 0.0 <= comp["score"] <= comp["max_score"], f"{r.project_id} {name} out of bounds"


def test_all_200_projects_scored(all_results, dataset):
    assert len(all_results) == len(dataset.projects)
    assert len({r.project_id for r in all_results}) == len(all_results)


def test_engine_does_not_crash_on_project_missing_optional_dates(dataset, engine):
    # Simulate missing dates on a copy of the dataset used only by this test.
    from intelligence.data_loader import Dataset
    from intelligence.risk_engine import build_engine as _build

    projects = dataset.projects.copy()
    projects.loc[projects["project_id"] == "P-1002", "actual_completion_date"] = pd.NaT
    projects.loc[projects["project_id"] == "P-1002", "work_order_date"] = pd.NaT

    broken_dataset = Dataset(
        projects=projects, contractors=dataset.contractors, bills=dataset.bills,
        payments=dataset.payments, locations=dataset.locations,
        historical_projects=dataset.historical_projects,
        project_contractors=dataset.project_contractors, anomaly_signals=dataset.anomaly_signals,
    )
    broken_engine = _build(broken_dataset)
    result = broken_engine.score_project("P-1002")  # should not raise
    assert 0.0 <= result.risk_score <= 100.0


def test_engine_does_not_crash_on_project_with_no_bills(dataset):
    from intelligence.data_loader import Dataset
    from intelligence.risk_engine import build_engine as _build

    bills = dataset.bills[dataset.bills["project_id"] != "P-1001"].copy()
    broken_dataset = Dataset(
        projects=dataset.projects, contractors=dataset.contractors, bills=bills,
        payments=dataset.payments, locations=dataset.locations,
        historical_projects=dataset.historical_projects,
        project_contractors=dataset.project_contractors, anomaly_signals=dataset.anomaly_signals,
    )
    broken_engine = _build(broken_dataset)
    result = broken_engine.score_project("P-1001")  # should not raise, billing score should be 0
    assert result.components["billing_anomaly"]["score"] == 0.0


def test_anomaly_signals_not_used_as_scoring_input():
    """Static check: no detector's public scoring function accepts the
    anomaly_signals dataframe as a parameter. Module docstrings are allowed
    to mention anomaly_signals.csv for documentation purposes; what matters
    is that it's never wired in as an argument to a score_* function."""
    import inspect
    from intelligence import cost_anomaly, project_similarity, contractor_analysis, billing_analysis, geographic_analysis

    modules = (cost_anomaly, project_similarity, contractor_analysis, billing_analysis, geographic_analysis)
    checked_any = False
    for module in modules:
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("score_") and not name.startswith("build_"):
                continue
            checked_any = True
            params = inspect.signature(obj).parameters
            for pname in params:
                assert "signal" not in pname.lower(), (
                    f"{module.__name__}.{name} takes a parameter '{pname}' — "
                    f"detectors must not take anomaly_signals as an input."
                )
    assert checked_any, "expected at least one score_*/build_* function to check"
