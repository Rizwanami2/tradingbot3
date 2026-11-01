"""
core/lock.py
Single-instance lock for tradingbot3 Precision Engine.
Prevents two bot instances from sending duplicate orders simultaneously.
Uses a platform-safe lockfile with PID tracking and stale-lock detection.
"""

import os
import time
import sys
from typing import Optional

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    from utils.logger import get_logger
    logger = get_logger("lock")
except Exception:
    import logging
    logger = logging.getLogger("lock")

LOCK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tradingbot.lock")
STALE_LOCK_SECONDS = 300  # Lock older than 5 min is considered stale


class SingleInstanceLock:
    """
    Ensures only one instance of the trading bot runs at a time.
    Uses a non-blocking lockfile. If another instance holds the lock
    and hasn't renewed it within STALE_LOCK_SECONDS, the lock is stolen.
    """

    def __init__(self, lock_file: str = LOCK_FILE):
        self.lock_file = lock_file
        self._fd: Optional[int] = None
        self._locked = False

    def acquire(self, block: bool = False) -> bool:
        """Attempt to acquire the single-instance lock."""
        try:
            # Windows doesn't support fcntl.flock well; use file creation check
            if sys.platform == "win32":
                return self._acquire_windows(block)
            return self._acquire_unix(block)
        except Exception as exc:
            logger.error(f"Lock acquisition error: {exc}")
            return False

    def _acquire_unix(self, block: bool) -> bool:
        """Unix-style flock lock."""
        if not HAS_FCNTL:
            return self._acquire_windows(block)
        self._fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o644)
        flags = fcntl.LOCK_EX if block else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(self._fd, flags)
            self._locked = True
            # Write PID for debugging
            os.ftruncate(self._fd, 0)
            os.write(self._fd, str(os.getpid()).encode())
            os.fsync(self._fd)
            logger.info(f"Single-instance lock acquired (PID {os.getpid()})")
            return True
        except (BlockingIOError, OSError):
            # Check if lock is stale
            if self._is_stale_unix():
                try:
                    os.close(self._fd)
                    self._fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o644)
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._locked = True
                    os.ftruncate(self._fd, 0)
                    os.write(self._fd, str(os.getpid()).encode())
                    os.fsync(self._fd)
                    logger.warning("Stale lock detected and stolen.")
                    return True
                except Exception:
                    pass
            logger.warning("Another bot instance holds the single-instance lock.")
            return False

    def _acquire_windows(self, block: bool) -> bool:
        """Windows-style lock using exclusive file creation + PID check."""
        try:
            # Try to create lock file exclusively
            if os.path.exists(self.lock_file):
                # Check if lock is stale
                if self._is_stale_windows():
                    try:
                        os.remove(self.lock_file)
                    except Exception:
                        pass
                else:
                    logger.warning("Another bot instance holds the single-instance lock.")
                    return False

            self._fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
            os.write(self._fd, str(os.getpid()).encode())
            os.fsync(self._fd)
            self._locked = True
            logger.info(f"Single-instance lock acquired (PID {os.getpid()})")
            return True
        except FileExistsError:
            logger.warning("Another bot instance holds the single-instance lock.")
            return False
        except Exception as exc:
            logger.error(f"Windows lock error: {exc}")
            return False

    def _is_stale_unix(self) -> bool:
        """Check if unix lock file is stale based on modification time."""
        try:
            mtime = os.path.getmtime(self.lock_file)
            age = time.time() - mtime
            return age > STALE_LOCK_SECONDS
        except Exception:
            return False

    def _is_stale_windows(self) -> bool:
        """Check if windows lock file is stale based on modification time."""
        try:
            mtime = os.path.getmtime(self.lock_file)
            age = time.time() - mtime
            return age > STALE_LOCK_SECONDS
        except Exception:
            return False

    def release(self) -> None:
        """Release the single-instance lock."""
        if self._fd is not None:
            try:
                if sys.platform != "win32":
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
        self._locked = False
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception:
            pass
        logger.info("Single-instance lock released.")

    @property
    def is_locked(self) -> bool:
        return self._locked

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Could not acquire single-instance lock. Another instance may be running.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# Global lock instance
single_instance_lock = SingleInstanceLock()
