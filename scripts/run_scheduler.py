"""Dedicated scheduler process (run exactly ONE instance). uv run python scripts/run_scheduler.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.workers.scheduler import start

if __name__ == "__main__":
    s = start()
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        s.shutdown()
