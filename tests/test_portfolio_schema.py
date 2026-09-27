import pytest
from pydantic import ValidationError

from src.schemas import PortfolioInput


def test_display_currency_defaults_and_normalizes():
    assert PortfolioInput(name='Long term').display_currency == 'BRL'
    assert PortfolioInput(name='Long term', display_currency='usd').display_currency == 'USD'
    with pytest.raises(ValidationError):
        PortfolioInput(name='Long term', display_currency='US1')
