import os
import sys
import re
import logging
from logging.handlers import RotatingFileHandler
from config.settings import settings

class SensitiveDataFilter(logging.Filter):
    """Filter that redacts sensitive information such as Telegram tokens and API keys."""

    def __init__(self, secrets_to_mask=None):
        super().__init__()
        self.secrets = [s for s in (secrets_to_mask or []) if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for secret in self.secrets:
                if len(secret) > 4:
                    masked = secret[:3] + "..." + secret[-3:]
                    record.msg = record.msg.replace(secret, masked)
            # Also catch standard bot token pattern (e.g., 123456789:ABCdef...)
            record.msg = re.sub(r'(\d{8,10}:[A-Za-z0-9_-]{35})', r'\1[:masked]', record.msg)
        return True

def setup_logger(name: str = "trademind") -> logging.Logger:
    """Configures dual console and rotating file logger with secret masking."""
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    # Sensitive data masking
    secrets = [settings.TELEGRAM_TOKEN]
    sensitive_filter = SensitiveDataFilter(secrets)
    logger.addFilter(sensitive_filter)

    # Formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler (10MB max, 5 backups)
    log_file = os.path.join(settings.LOG_DIR, "trademind.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

logger = setup_logger()
