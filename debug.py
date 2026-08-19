"""
the diagnostic prints, behind a flag.

    DEBUG=1     in the .env, or in the environment
"""

import os

from dotenv import load_dotenv

load_dotenv()

DEBUG = os.getenv("DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def debug_log(label, value):
    """print only when DEBUG is on. Never call this with a credential as the value."""
    if DEBUG:
        print(f"[DEBUG] {label}: {value}")
