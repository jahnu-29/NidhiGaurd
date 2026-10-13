import pytest

from intelligence.data_loader import load_dataset
from intelligence.risk_engine import build_engine


@pytest.fixture(scope="session")
def dataset():
    return load_dataset()


@pytest.fixture(scope="session")
def engine(dataset):
    return build_engine(dataset)


@pytest.fixture(scope="session")
def all_results(engine):
    return engine.score_all()
