import pytest
from app.portfolio.engine import portfolio_engine
from app.config import settings


@pytest.fixture(scope="session", autouse=True)
def clean_portfolio_after_test_suite():
    """Ensures test runs never leave residual test trades in the live paper portfolio."""
    yield
    portfolio_engine.reset_portfolio(settings.INITIAL_BALANCE)
