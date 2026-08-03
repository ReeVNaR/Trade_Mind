"""
NIFTY 50 Futures & Options (F&O) Module.
Provides In-The-Money (ITM) strike calculation, expiry determination,
option pricing/greeks estimation, and lot-size management for NIFTY derivatives.
"""

from datetime import datetime, timedelta, time
from typing import Dict, Any, Optional
import math

# IST Timezone Helper
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")


NIFTY_LOT_SIZE = 25
NIFTY_STRIKE_STEP = 50


def get_nifty_atm_strike(spot_price: float) -> int:
    """Returns the At-The-Money (ATM) strike price rounded to nearest 50 points."""
    return int(round(spot_price / float(NIFTY_STRIKE_STEP)) * NIFTY_STRIKE_STEP)


def get_current_weekly_expiry(base_date: Optional[datetime] = None) -> datetime:
    """
    Returns the nearest upcoming NSE Thursday weekly expiry date.
    NSE Index Options expire on Thursdays (or preceding Wednesday if Thursday is a holiday).
    """
    now = base_date or datetime.now(IST)
    # weekday(): Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
    days_ahead = (3 - now.weekday()) % 7
    if days_ahead == 0 and now.time() > time(15, 30):
        days_ahead = 7  # If today is Thursday after market close, take next Thursday
    expiry = now + timedelta(days=days_ahead)
    return expiry.replace(hour=15, minute=30, second=0, microsecond=0)


def format_expiry_string(expiry_dt: datetime) -> str:
    """Formats datetime into standard NSE contract expiry code, e.g. '07NOV'."""
    return expiry_dt.strftime("%d%b").upper()


def get_nifty_itm_strike(
    spot_price: float,
    option_type: str,
    itm_depth: int = 1
) -> Dict[str, Any]:
    """
    Calculates In-The-Money (ITM) strike for NIFTY options.
    
    - For CALL (CE / Bullish): ITM strike is BELOW spot (e.g. Spot 24,920 -> Strike 24,850 CE).
      Has high Delta (~0.68-0.75), high intrinsic value, lower theta decay.
    - For PUT (PE / Bearish): ITM strike is ABOVE spot (e.g. Spot 24,920 -> Strike 25,000 PE).
      Has high Delta (~ -0.68 to -0.75), high intrinsic value.
    """
    opt_type = option_type.strip().upper()
    if opt_type not in ["CE", "PE", "CALL", "PUT"]:
        raise ValueError(f"Invalid option type '{option_type}'. Must be CE/CALL or PE/PUT.")
    
    is_call = opt_type in ["CE", "CALL"]
    opt_code = "CE" if is_call else "PE"
    
    # Calculate base ATM strike
    atm_strike = get_nifty_atm_strike(spot_price)
    
    # ITM Shift: For Call subtract (itm_depth * 50), for Put add (itm_depth * 50)
    # Ensure minimum 1 strike deep (50 to 100 pts)
    depth_multiplier = max(1, itm_depth)
    if is_call:
        # If spot is 24920, ATM is 24900 -> 1 strike ITM is 24850
        floor_strike = int(spot_price // NIFTY_STRIKE_STEP) * NIFTY_STRIKE_STEP
        strike = floor_strike - ((depth_multiplier - 1) * NIFTY_STRIKE_STEP)
        # Verify strictly below spot
        if strike >= spot_price:
            strike -= NIFTY_STRIKE_STEP
        intrinsic_value = max(0.0, spot_price - strike)
        estimated_delta = min(0.85, max(0.60, 0.50 + (intrinsic_value / (NIFTY_STRIKE_STEP * 3.0))))
    else:
        # If spot is 24920, ATM is 24950 -> 1 strike ITM is 25000
        ceil_strike = int(math.ceil(spot_price / NIFTY_STRIKE_STEP)) * NIFTY_STRIKE_STEP
        strike = ceil_strike + ((depth_multiplier - 1) * NIFTY_STRIKE_STEP)
        # Verify strictly above spot
        if strike <= spot_price:
            strike += NIFTY_STRIKE_STEP
        intrinsic_value = max(0.0, strike - spot_price)
        estimated_delta = max(-0.85, min(-0.60, -0.50 - (intrinsic_value / (NIFTY_STRIKE_STEP * 3.0))))

    expiry_dt = get_current_weekly_expiry()
    expiry_str = format_expiry_string(expiry_dt)
    symbol_name = f"NIFTY {strike} {opt_code}"
    trading_symbol = f"NIFTY{expiry_str}{strike}{opt_code}"

    # Estimate option premium
    days_to_exp = max(1, (expiry_dt - datetime.now(IST)).days)
    premium = estimate_option_premium(
        spot_price=spot_price,
        strike_price=strike,
        option_type=opt_code,
        days_to_expiry=days_to_exp
    )

    return {
        "symbol": symbol_name,
        "trading_symbol": trading_symbol,
        "underlying": "NIFTY 50",
        "spot_price": round(spot_price, 2),
        "strike_price": strike,
        "option_type": opt_code,
        "moneyness": "ITM",
        "is_itm": True,
        "itm_depth": itm_depth,
        "intrinsic_value": round(intrinsic_value, 2),
        "estimated_premium": round(premium, 2),
        "estimated_delta": round(estimated_delta, 2),
        "lot_size": NIFTY_LOT_SIZE,
        "lot_cost": round(premium * NIFTY_LOT_SIZE, 2),
        "expiry_date": expiry_dt.strftime("%Y-%m-%d"),
        "expiry_display": expiry_dt.strftime("%d %b %Y (Thursday)")
    }


def estimate_option_premium(
    spot_price: float,
    strike_price: int,
    option_type: str,
    days_to_expiry: int = 4,
    implied_volatility: float = 0.135
) -> float:
    """
    Estimates realistic NIFTY option premium based on Intrinsic Value + Extrinsic Time Value.
    """
    is_call = option_type.upper() in ["CE", "CALL"]
    if is_call:
        intrinsic = max(0.0, spot_price - strike_price)
    else:
        intrinsic = max(0.0, strike_price - spot_price)

    # Time value decay model
    t = max(0.5, float(days_to_expiry)) / 365.0
    time_value = (spot_price * implied_volatility * math.sqrt(t)) * 0.38
    
    # ITM options have reduced extrinsic time value proportional to moneyness
    time_value_discount = max(0.35, 1.0 - (intrinsic / (spot_price * 0.04)))
    effective_time_value = time_value * time_value_discount

    premium = max(15.0, intrinsic + effective_time_value)
    return round(premium, 2)


def calculate_fno_lot_allocation(
    premium: float,
    available_cash: float,
    max_capital_ratio: float = 0.35,
    lot_size: int = NIFTY_LOT_SIZE
) -> Dict[str, Any]:
    """
    Computes exact lot sizing and risk allocation for ₹30,000 budget.
    Ensures safe margin allocation (typically 1 lot = ₹4,000-₹6,000) leaving ample liquid buffer.
    """
    lot_cost = premium * lot_size
    if lot_cost <= 0 or available_cash < lot_cost:
        return {
            "lots": 0,
            "quantity": 0,
            "lot_cost": round(lot_cost, 2),
            "total_cost": 0.0,
            "can_afford": False
        }

    max_allocation = available_cash * max_capital_ratio
    lots = max(1, int(max_allocation // lot_cost))
    # Cap at available cash
    while lots * lot_cost > available_cash * 0.95 and lots > 1:
        lots -= 1

    total_cost = lots * lot_cost
    return {
        "lots": lots,
        "quantity": lots * lot_size,
        "lot_cost": round(lot_cost, 2),
        "total_cost": round(total_cost, 2),
        "can_afford": True
    }
