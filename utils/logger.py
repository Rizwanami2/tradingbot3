import os
import sys
import logging
from logging.handlers import RotatingFileHandler

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
os.makedirs(_LOG_DIR, exist_ok=True)

_LOG_FILE = os.path.join(_LOG_DIR, "tradingbot.log")
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

_FILE_HANDLER = None
_CONSOLE_HANDLER = None

def _get_shared_handlers():
    global _FILE_HANDLER, _CONSOLE_HANDLER
    if _FILE_HANDLER is None:
        _FILE_HANDLER = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
            encoding="utf-8"
        )
        _FILE_HANDLER.setFormatter(_FORMATTER)
        _FILE_HANDLER.setLevel(logging.INFO)

    if _CONSOLE_HANDLER is None:
        _CONSOLE_HANDLER = logging.StreamHandler(sys.stdout)
        _CONSOLE_HANDLER.setFormatter(_FORMATTER)
        _CONSOLE_HANDLER.setLevel(logging.INFO)

    return _FILE_HANDLER, _CONSOLE_HANDLER

def get_logger(name: str = "tradingbot") -> logging.Logger:
    """
    Returns a configured thread-safe logger writing to logs/tradingbot.log
    and standard output with rotating file handling.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_h, console_h = _get_shared_handlers()
        logger.addHandler(file_h)
        logger.addHandler(console_h)
        logger.propagate = False

    return logger
