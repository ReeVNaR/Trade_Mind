# TradeMind-AI: Production-Ready NIFTY F&O AI Trading Bot

An advanced, production-ready, modular, and secure AI-powered NIFTY F&O Trading Bot designed for the Indian Stock Market.

## Key Features

- **Multi-Strategy Technical Engine**: EMA Crossovers, VWAP, Supertrend, ADX, Opening Range Breakout (ORB), RSI Divergence, Bollinger Bands.
- **AI Decision Engine**: Multi-factor scoring (PCR, India VIX, Trend, Greeks) with confidence thresholding (≥ 80%) and plain-English trade explanations.
- **Risk Management Circuit Breakers**: Daily loss circuit breaker (₹2,000), profit target lock (₹4,000), max trades per day (4), consecutive loss lockout, dynamic position sizer, and trailing stop loss.
- **Paper & Live Trading Adapter**: Simulation engine with Black-Scholes option pricing (Delta, Gamma, Theta, Vega), bid-ask slippage, and margin checks.
- **Telegram Notifications**: Real-time alerts for bot startup, trade signals, order fills, risk circuit triggers, and end-of-day reports.
- **REST API & Live Dashboard**: FastAPI backend with live web dashboard featuring dark glassmorphism design.
- **Render Ready**: Cloud deployment ready with Docker and `render.yaml`.

---

## Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite
Execute the full test suite across all 7 phases:
```bash
python -m pytest tests/ -v
```

### 3. Start REST API & Web Dashboard
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```
Access the Dashboard at: `http://localhost:8000/dashboard`  
Access API Documentation at: `http://localhost:8000/docs`

---

## Project Structure
```
config/             # Configuration & Pydantic settings loader
broker/             # Abstract broker interface & paper broker adapter
market_data/        # yfinance fetcher, indicators & PCR/Max Pain analytics
strategies/         # Trend following, breakout, reversal & strategy engine
ai_engine/          # Multi-factor AI confidence scoring & explanations
risk_management/    # Circuit breakers, dynamic lot sizing & trailing SL
orders/             # Order execution state machine & trade persistence
paper_trading/      # Simulator & Black-Scholes option greeks engine
telegram/           # Telegram bot notification dispatcher
database/           # SQLAlchemy models & database connection setup
dashboard/          # Live web dashboard (Dark glassmorphism UI)
api/                # FastAPI endpoints
tests/              # Comprehensive test suite (Phases 1 - 7)
```
