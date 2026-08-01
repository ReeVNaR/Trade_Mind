# TradeMind-AI 🇮🇳 🚀
> **Autonomous AI-Powered Algorithmic Trading & Live Market Tracing Engine for Indian Stock Markets (NSE / BSE)**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com)
[![Render](https://img.shields.io/badge/Render-Deploy%20Ready-black.svg?logo=render)](https://render.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

TradeMind-AI is an institutional-grade algorithmic trading and portfolio management framework specialized for the **Indian Stock Market (NSE / BSE)**. It integrates real-time National Stock Exchange ticks, quantitative multi-indicator technical analysis (Supertrend, VWAP, RSI, EMA, MACD, Bollinger Bands), risk-managed paper trading in **₹ INR**, and **Google Gemini LLM reasoning** with **Telegram bot execution and alerts**.

---

## 🌟 Key Capabilities

- 🇮🇳 **Indian Stock Market Specialization**: Real-time tick ingestion and historical OHLCV data for NSE/BSE equities (e.g., `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS`, `INFY.NS`, `^NSEI`, `^NSEBANK`).
- 📐 **Institutional Quantitative Strategies**:
  - **Supertrend + VWAP Strategy**: Specially tuned for Indian market volatility and intraday momentum.
  - **EMA Crossover + MACD Momentum**: 9/21 EMA crossover trend filtering.
  - **RSI + Bollinger Bands Mean Reversion**: Overbought/oversold bounce detection.
- 🧠 **Google Gemini AI Reasoning**: Multi-factor signal validation reviewing market sentiment, risk-to-reward ratios, and macro catalysts before placing trades.
- 💼 **Risk-Managed Virtual Portfolio**: Starting capital of **₹2,000 INR**, dynamic 20% max allocation per trade, automated 1.5% stop-loss and 3.5% take-profit safeguards.
- 📱 **Interactive Telegram Bot**: Instant push notifications for trade entries/exits, AI rationales, and interactive commands (`/status`, `/portfolio`, `/scan`, `/trades`, `/help`).
- ⚡ **Real-Time Live Web Dashboard & REST API**: Modern dark glassmorphism interface with live stock tracing, on-demand backtesting engine, and manual trade execution.
- ☁️ **Cloud Ready**: Configured for instant 1-click deployment on **Render** (free/standard tier) and Docker containers.

---

## 📁 Project Architecture

```
TradeMind-AI/
├── app/
│   ├── config.py                 # Configuration & Indian symbol normalizer
│   ├── data/
│   │   └── fetcher.py            # Real-time NSE/BSE live quote & candle fetcher
│   ├── indicators/
│   │   └── technical.py          # Vectorized Supertrend, VWAP, RSI, EMA, MACD, BB, ATR
│   ├── strategies/
│   │   ├── base.py               # Signal dataclass & BaseStrategy interface
│   │   ├── supertrend_vwap.py    # Supertrend + VWAP strategy (NSE spec)
│   │   ├── trend_following.py    # EMA (9/21) + MACD Trend strategy
│   │   └── rsi_reversal.py       # RSI + Bollinger Bands mean reversion strategy
│   ├── ai/
│   │   └── gemini_analyst.py     # Gemini AI signal reasoning & confirmation
│   ├── portfolio/
│   │   └── engine.py             # Paper trading engine, risk sizing & INR accounting
│   ├── database/
│   │   ├── models.py             # SQLAlchemy models (Trade, Position, SignalLog, Snapshot)
│   │   └── session.py            # SQLite / PostgreSQL session management
│   ├── telegram/
│   │   └── bot.py                # Telegram interactive bot listener & broadcast alerts
│   ├── scheduler/
│   │   └── runner.py             # Autonomous market scanning loop
│   ├── backtesting/
│   │   └── engine.py             # Quantitative historical backtesting engine
│   ├── utils/
│   │   └── logger.py             # Rotating file & console logger
│   └── api/
│       └── routes.py             # FastAPI endpoints, health check & Live Dashboard UI
├── tests/                        # Full test suite (24 passing unit & integration tests)
├── .env.example                  # Environment configuration template
├── .gitignore                    # Git security filter (blocks .env and databases)
├── .dockerignore                 # Docker build ignore rules
├── Dockerfile                    # Containerization specification
├── Procfile                      # Process file for Render web service
├── render.yaml                   # Render Blueprint Infrastructure-as-Code
├── requirements.txt              # Production Python dependencies
├── main.py                       # Application runner & background orchestrator
└── README.md                     # Project documentation
```

---

## 🚀 Quick Start (Local Development)

### 1. Clone & Setup Virtual Environment
```bash
# Clone repository
git clone https://github.com/your-username/TradeMind-AI.git
cd TradeMind-AI

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure `.env`
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in your keys:
- `TELEGRAM_TOKEN`: (Optional) Bot token from [@BotFather](https://t.me/BotFather)
- `CHAT_ID`: (Optional) Your Chat ID from [@userinfobot](https://t.me/userinfobot)
- `GEMINI_API_KEY`: (Optional) Free API key from [Google AI Studio](https://aistudio.google.com/)

### 4. Run Verification & Launch
```bash
# Verify startup checks
python main.py --verify

# Launch Web Server, Autonomous Scanner & Telegram Listener
python main.py
```
Visit the live interface:
- **Live Dashboard:** [http://localhost:8000](http://localhost:8000)
- **API Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

## ☁️ Deploying on Render

TradeMind-AI is configured for seamless deployment on **Render** as a Python Web Service.

### Option A: 1-Click / Blueprint Deploy (Recommended)
1. Push your repository to **GitHub** (see instructions below).
2. Log in to [Render Dashboard](https://dashboard.render.com/).
3. Click **New +** -> **Blueprint**.
4. Connect your GitHub repository.
5. Render will automatically detect `render.yaml` and set up the build & start commands!
6. Under **Environment Variables**, provide:
   - `TELEGRAM_TOKEN`: Your Telegram Bot token.
   - `CHAT_ID`: Your Telegram Chat ID.
   - `GEMINI_API_KEY`: Your Google Gemini API Key.
7. Click **Apply**. Render will build and deploy your live trading engine.

### Option B: Manual Web Service Setup on Render
1. Go to [Render Dashboard](https://dashboard.render.com/) and click **New +** -> **Web Service**.
2. Select your `TradeMind-AI` GitHub repository.
3. Configure the following fields:
   - **Name**: `trademind-ai`
   - **Region**: Any (e.g., `Oregon (US West)` or `Frankfurt (EU Central)`)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Plan**: `Free`
4. Expand **Advanced** -> **Health Check Path**: `/health`
5. Add Environment Variables:
   - `ENVIRONMENT` = `production`
   - `API_HOST` = `0.0.0.0`
   - `INITIAL_BALANCE` = `2000.0`
   - `TELEGRAM_TOKEN` = `<your_token>`
   - `CHAT_ID` = `<your_chat_id>`
   - `GEMINI_API_KEY` = `<your_gemini_key>`
6. Click **Create Web Service**.

---

## 🐙 Pushing to GitHub

Follow these steps to initialize and push your repository to GitHub:

### 1. Initialize Git (if not already done)
```bash
git init
git branch -M main
```

### 2. Verify Sensitive Files are Ignored
```bash
# Check git status (Verify .env and trademind.db are NOT listed)
git status
```

### 3. Stage and Commit Files
```bash
git add .
git commit -m "feat: initial release of TradeMind-AI with Render and NSE live trading support"
```

### 4. Link Remote Repository and Push
Create a new repository on [GitHub](https://github.com/new) named `TradeMind-AI`, then run:
```bash
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/TradeMind-AI.git
git push -u origin main
```

---

## 🧪 Running Automated Tests

Run the comprehensive 24-test suite covering indicators, strategies, backtesting, database operations, and API endpoints:
```bash
pytest tests/ -v
```

---

## 📡 REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web Dashboard with Real-Time Stock Tracer & Portfolio View |
| `GET` | `/health` | Cloud health check & uptime monitor endpoint |
| `GET` | `/api/status` | System status, version, market status & watchlist |
| `GET` | `/api/trace/{symbol}` | Real-time live exchange quote, VWAP, Supertrend & RSI metrics |
| `GET` | `/api/market-data` | Bulk 24h market metrics for NSE watchlist |
| `GET` | `/api/portfolio` | Virtual portfolio balance, open positions, and PnL in ₹ INR |
| `GET` | `/api/trades` | Historical executed trade audit log |
| `GET` | `/api/signals` | Algorithmic strategy & Gemini AI signal log |
| `POST` | `/api/scan` | Trigger immediate market scan across NSE watchlist |
| `POST` | `/api/analyze/{symbol}` | Instant multi-indicator + Gemini AI reasoning analysis |
| `POST` | `/api/backtest` | Quantitative historical backtest on real NSE data |
| `POST` | `/api/trade/buy` | Manual paper BUY order in ₹ INR |
| `POST` | `/api/trade/sell` | Manual paper SELL order in ₹ INR |

---

## 🛡️ Risk Safeguards & Indian Market Rules

1. **Strict Market Filter**: Only verified NSE/BSE equities (e.g. `RELIANCE.NS`, `TCS.NS`, `^NSEI`) can be analyzed or traded.
2. **Capital Protection**: Never allocates more than 20% of portfolio equity to a single trade.
3. **Automated Stop Loss (SL)**: 1.5% fixed or ATR-calculated safety exit.
4. **Automated Take Profit (TP)**: 3.5% reward target.
5. **AI Conviction Filter**: Technical signals are verified against Gemini AI reasoning before execution.

---

## 📜 License
MIT License. Built for algorithmic trading research and quantitative analysis.
