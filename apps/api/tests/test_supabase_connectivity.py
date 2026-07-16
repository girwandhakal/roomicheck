"""Read-only connectivity check for the configured Supabase PostgreSQL database."""

from __future__ import annotations

import pytest
from sqlalchemy import text


def test_configured_supabase_database_is_reachable() -> None:
    """Verify that the API can open a connection and execute a harmless query."""
    from app.config import get_settings
    from app.database import engine

    settings = get_settings()
    safe_url = settings.sqlalchemy_database_url.render_as_string(hide_password=True)

    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    except Exception as error:  # pragma: no cover - exercised by unavailable environments
        pytest.fail(
            "Configured Supabase PostgreSQL is unreachable. "
            f"Connection: {safe_url}. Error type: {type(error).__name__}."
        )
