#!/usr/bin/env python3
"""Seed admin user and welcome flow (also runs on API startup)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.bootstrap import init_db
from app.config import get_settings

if __name__ == "__main__":
    init_db()
    s = get_settings()
    print(f"Admin ready: {s.admin_email}")
    print("Welcome Flow ensured.")
