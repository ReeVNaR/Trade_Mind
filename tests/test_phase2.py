import pytest
from broker.paper_broker import PaperBroker
from paper_trading.options_pricing import BlackScholes

def test_black_scholes_pricing_and_greeks():
    """Verify Black-Scholes pricing and option Greeks."""
    spot = 22500.0
    strike = 22500.0
    T = 7 / 365.0 # 7 days
    r = 0.07
    sigma = 0.15

    ce_price = BlackScholes.option_price(spot, strike, T, r, sigma, "CE")
    pe_price = BlackScholes.option_price(spot, strike, T, r, sigma, "PE")
    greeks_ce = BlackScholes.greeks(spot, strike, T, r, sigma, "CE")

    assert ce_price > 0
    assert pe_price > 0
    # ATM Call Delta should be approximately 0.5
    assert 0.45 <= greeks_ce["delta"] <= 0.60
    assert greeks_ce["gamma"] > 0
    assert greeks_ce["vega"] > 0

def test_paper_broker_workflow():
    """Test full paper broker order execution, PnL tracking, and position management."""
    broker = PaperBroker(initial_capital=30000.0)
    assert broker.connect() is True

    balance = broker.get_balance()
    assert balance["cash_balance"] == 30000.0
    assert balance["available_margin"] == 30000.0

    # 1. Place Market BUY order for NIFTY Call Option
    sym = "NIFTY24AUG22500CE"
    broker.set_mock_quote(sym, 100.0)
    
    order = broker.place_order(
        symbol=sym,
        order_type="MARKET",
        direction="BUY",
        quantity=65,
        price=100.0
    )

    assert order["status"] == "EXECUTED"
    # Fill price includes ~0.05% slippage (approx 100.05)
    assert order["fill_price"] >= 100.0

    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 65
    assert positions[0]["symbol"] == sym

    # Available margin should decrease by position cost
    used_margin = positions[0]["average_price"] * 65
    bal_after_buy = broker.get_balance()
    assert abs(bal_after_buy["used_margin"] - used_margin) < 1.0

    # 2. Simulate price movement up to 120.0
    broker.set_mock_quote(sym, 120.0)
    pos_updated = broker.get_positions()[0]
    assert pos_updated["unrealized_pnl"] > 1000.0 # (120 - ~100.05) * 65

    # 3. Close position with Market SELL order
    sell_order = broker.place_order(
        symbol=sym,
        order_type="MARKET",
        direction="SELL",
        quantity=65,
        price=120.0
    )
    assert sell_order["status"] == "EXECUTED"

    final_positions = broker.get_positions()
    assert len(final_positions) == 0

    final_balance = broker.get_balance()
    assert final_balance["used_margin"] == 0.0
    assert final_balance["realized_pnl"] > 1000.0
    assert final_balance["cash_balance"] > 30000.0

def test_paper_broker_insufficient_margin():
    """Verify order rejection when required margin exceeds available margin."""
    broker = PaperBroker(initial_capital=5000.0)
    broker.connect()
    
    # Required margin = 200 * 65 = ₹13,000 > ₹5,000 capital
    order = broker.place_order(
        symbol="NIFTY24AUG22500CE",
        order_type="MARKET",
        direction="BUY",
        quantity=65,
        price=200.0
    )
    assert order["status"] == "REJECTED"

def test_synthetic_option_chain():
    """Verify synthetic option chain generation."""
    broker = PaperBroker()
    chain = broker.get_option_chain(spot_price=22500.0, expiry_days=7)
    assert len(chain) == 11 # 11 strikes (-5 to +5)
    atm_item = [item for item in chain if item["strike"] == 22500][0]
    assert atm_item["CE"]["price"] > 0
    assert atm_item["PE"]["price"] > 0
