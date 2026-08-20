"""
db.py — Supabase client singleton for the entire app.

Import with:
    from db import get_sb

Returns the Supabase client when SUPABASE_URL + SUPABASE_KEY are set and the
Harbour schema is reachable, or None otherwise — so every caller can fall back
to local JSON files without partially configured database failures.
"""
from __future__ import annotations
import os

# Load .env if python-dotenv is installed (it is in requirements.txt).
# This must run before os.environ.get() calls.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

_client = None
_configuration_checked = False


def get_sb():
    """Return the Supabase client, or None if not configured."""
    global _client, _configuration_checked
    if _configuration_checked:
        return _client
    _configuration_checked = True
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if url and key:
        valid_prefixes = ("eyJ", "sb_publishable_", "sb_secret_")
        if not key.startswith(valid_prefixes):
            print("[db] SUPABASE_KEY is not a supported project API key; falling back to JSON files.")
            return None
        try:
            from supabase import create_client
            # Strip any path suffix the user may have copied from the dashboard
            url = url.rstrip("/").removesuffix("/rest/v1")
            candidate = create_client(url, key)
            for table in ("resources", "cases", "escalations"):
                candidate.table(table).select("*", count="exact").limit(1).execute()
            _client = candidate
        except Exception as e:
            _client = None
            print(f"[db] Supabase unavailable or Harbour schema incomplete: {e}. "
                  "Falling back to JSON files.")
    return _client
