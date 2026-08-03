import pytest
from app.config import settings
from app.data.nifty_options import (
    get_nifty_itm_strike,
    get_nifty_atm_strike,
    calculate_fno_lot_allocation,
    NIFTY_LOT_SIZE
)
from app.portfolio.daily_risk import DailyRiskManager
from app.portfolio.engine import PortfolioEngine


def test_nifty_options_strike_selection():
    """Verify ITM Call and Put strike selection and lot calculations."""
    spot_price = 24962.50
    atm = get_nifty_atm_strike(spot_price)
    assert atm == 25000 or atm == 24950

    # ITM Call (CE): strike should be strictly BELOW spot price
    itm_ce = get_nifty_itm_strike(spot_price, "CE", itm_depth=1)
    assert itm_ce["strike_price"] < spot_price
    assert itm_ce["strike_price"] == 24950
    assert itm_ce["option_type"] == "CE"
    assert itm_ce["is_itm"] is True
    assert itm_ce["estimated_premium"] > 0
    assert itm_ce["lot_cost"] == round(itm_ce["estimated_premium"] * NIFTY_LOT_SIZE, 2)
    assert itm_ce["estimated_delta"] >= 0.50
    assert "Tuesday" in itm_ce["expiry_display"]

    # ITM Put (PE): strike should be strictly ABOVE spot price
    itm_pe = get_nifty_itm_strike(spot_price, "PE", itm_depth=1)
    assert itm_pe["strike_price"] > spot_price
    assert itm_pe["strike_price"] == 25000
    assert itm_pe["option_type"] == "PE"
    assert itm_pe["is_itm"] is True
    assert itm_pe["estimated_premium"] > 0
    assert itm_pe["lot_cost"] == round(itm_pe["estimated_premium"] * NIFTY_LOT_SIZE, 2)
    assert itm_pe["estimated_delta"] <= -0.50
    assert "Tuesday" in itm_pe["expiry_display"]


def test_fno_lot_allocation():
    """Verify margin allocation with 30k capital and 65-unit lot size."""
    available_cash = 30000.0
    premium = 100.0  # 1 lot = 65 * 100 = 6,500
    alloc = calculate_fno_lot_allocation(
        premium=premium,
        available_cash=available_cash,
        max_capital_ratio=0.35,
        lot_size=NIFTY_LOT_SIZE
    )
    
    # 35% of 30,000 = 10,500 max margin -> 1 lot = 6,500 (2 lots = 13,000 > 10,500)
    assert alloc["lots"] == 1
    assert alloc["quantity"] == 65
    assert alloc["total_cost"] == 6500.0
    assert alloc["can_afford"] is True


def test_daily_risk_circuit_breakers():
    """Verify daily circuit breaker rules: max 4 trades, -2k SL, +4k target."""
    risk_mgr = DailyRiskManager()
    
    # Verify defaults match configuration
    assert settings.INITIAL_BALANCE == 30000.0
    assert settings.MAX_DAILY_TRADES == 4
    assert settings.MAX_DAILY_LOSS == 2000.0
    assert settings.MAX_DAILY_PROFIT == 4000.0

    stats = risk_mgr.get_daily_trade_stats()
    assert "trades_today" in stats
    assert "max_daily_trades" in stats
    assert stats["max_daily_trades"] == 4
    assert stats["max_daily_loss"] == 2000.0
    assert stats["max_daily_profit"] == 4000.0


def test_portfolio_engine_nifty_setup():
    """Verify Portfolio Engine initial balance and summary."""
    engine = PortfolioEngine()
    summary = engine.get_portfolio_summary()

    assert summary["initial_balance"] == 30000.0
    assert "daily_risk" in summary
    assert summary["daily_risk"]["max_daily_trades"] == 4


def test_nifty_expiry_after_2pm_cutoff():
    """Verify that NO trades are permitted on NIFTY Expiry Day (Tuesday) after 2:00 PM IST (14:00)."""
    from datetime import datetime
    risk_mgr = DailyRiskManager()

    # 1. Tuesday at 11:30 AM IST (Expiry morning) -> Allowed
    tuesday_morning = datetime(2026, 8, 4, 11, 30)  # 2026-08-04 is a Tuesday
    stats_morn = risk_mgr.get_daily_trade_stats(current_datetime=tuesday_morning)
    assert stats_morn["can_trade"] is True
    assert stats_morn["circuit_status"] == "ACTIVE"
    assert stats_morn["is_expiry_day"] is True
    assert stats_morn["is_expiry_cutoff"] is False

    can_trade_morn, _ = risk_mgr.can_open_new_trade(current_datetime=tuesday_morning)
    assert can_trade_morn is True

    # 2. Tuesday at 14:00 (2:00 PM IST exact cutoff) -> Blocked
    tuesday_2pm = datetime(2026, 8, 4, 14, 0)
    stats_2pm = risk_mgr.get_daily_trade_stats(current_datetime=tuesday_2pm)
    assert stats_2pm["can_trade"] is False
    assert stats_2pm["circuit_status"] == "HALTED_EXPIRY_AFTER_2PM"
    assert stats_2pm["is_expiry_cutoff"] is True
    assert "EXPIRY CUTOFF ACTIVE" in stats_2pm["status_message"]

    can_trade_2pm, msg_2pm = risk_mgr.can_open_new_trade(current_datetime=tuesday_2pm)
    assert can_trade_2pm is False
    assert "EXPIRY CUTOFF" in msg_2pm

    # 3. Tuesday at 14:45 (2:45 PM IST afternoon) -> Blocked
    tuesday_late = datetime(2026, 8, 4, 14, 45)
    stats_late = risk_mgr.get_daily_trade_stats(current_datetime=tuesday_late)
    assert stats_late["can_trade"] is False
    assert stats_late["circuit_status"] == "HALTED_EXPIRY_AFTER_2PM"

    # 4. Wednesday at 14:30 (Non-expiry day afternoon) -> Allowed
    wednesday_afternoon = datetime(2026, 8, 5, 14, 30)  # 2026-08-05 is Wednesday
    stats_wed = risk_mgr.get_daily_trade_stats(current_datetime=wednesday_afternoon)
    assert stats_wed["can_trade"] is True
    assert stats_wed["circuit_status"] == "ACTIVE"
    assert stats_wed["is_expiry_day"] is False
    assert stats_wed["is_expiry_cutoff"] is False

