import pytest
from telegram.bot_commands import TelegramCommandHandler
from broker.paper_broker import PaperBroker
from risk_management.risk_manager import RiskManager
from scheduler.live_scanner import LiveMarketScanner

def test_telegram_command_handler_execution():
    """Verify all Telegram bot commands (/status, /balance, /positions, /scan, /pause, /resume, /report)."""
    broker = PaperBroker(initial_capital=30000.0)
    broker.connect()
    rm = RiskManager()
    scanner = LiveMarketScanner(broker=broker, risk_manager=rm)

    cmd_handler = TelegramCommandHandler(scanner=scanner, broker=broker, risk_manager=rm)
    
    # Test executing command handlers directly
    cmd_handler._cmd_help("12345")
    cmd_handler._cmd_status("12345")
    cmd_handler._cmd_balance("12345")
    cmd_handler._cmd_positions("12345")
    cmd_handler._cmd_orders("12345")
    cmd_handler._cmd_scan("12345")
    cmd_handler._cmd_pause("12345")
    cmd_handler._cmd_resume("12345")
    cmd_handler._cmd_report("12345")
