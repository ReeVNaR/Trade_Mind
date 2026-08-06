import math
from scipy.stats import norm

class BlackScholes:
    """Calculates Black-Scholes option premiums and Greeks for Indian Options Market."""

    @staticmethod
    def calculate_d1_d2(S: float, K: float, T: float, r: float, sigma: float):
        """
        S: Spot Price
        K: Strike Price
        T: Time to Expiration in Years (e.g., 7 days = 7/365)
        r: Risk-free Interest Rate (e.g. 0.07 for 7%)
        sigma: Implied Volatility (e.g. 0.15 for 15%)
        """
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return 0.0, 0.0
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return d1, d2

    @classmethod
    def option_price(cls, S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> float:
        """Returns theoretical option premium."""
        if T <= 0:
            if option_type.upper() == "CE":
                return max(0.0, S - K)
            else:
                return max(0.0, K - S)
                
        d1, d2 = cls.calculate_d1_d2(S, K, T, r, sigma)
        if option_type.upper() == "CE":
            price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        return max(0.05, round(price, 2)) # Min tick size ₹0.05

    @classmethod
    def greeks(cls, S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> dict:
        """Returns option Greeks: Delta, Gamma, Theta, Vega."""
        if T <= 0 or sigma <= 0:
            return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        d1, d2 = cls.calculate_d1_d2(S, K, T, r, sigma)
        pdf_d1 = norm.pdf(d1)

        gamma = pdf_d1 / (S * sigma * math.sqrt(T))
        vega = S * pdf_d1 * math.sqrt(T) / 100.0 # Per 1% IV change

        if option_type.upper() == "CE":
            delta = norm.cdf(d1)
            theta = (- (S * pdf_d1 * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365.0
        else:
            delta = norm.cdf(d1) - 1.0
            theta = (- (S * pdf_d1 * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365.0

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4)
        }
