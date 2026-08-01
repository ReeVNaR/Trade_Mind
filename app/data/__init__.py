"""
Market Data module for TradeMind-AI.
Live real-time National Stock Exchange (NSE) and Bombay Stock Exchange (BSE) feed.
"""
from .fetcher import DataFetcher, LiveStockTrace, data_fetcher

# Backwards compatibility alias
MarketData = LiveStockTrace

__all__ = ["DataFetcher", "LiveStockTrace", "MarketData", "data_fetcher"]
