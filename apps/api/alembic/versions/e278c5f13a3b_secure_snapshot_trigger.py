"""Secure the immutable profile snapshot trigger.

Revision ID: e278c5f13a3b
Revises: 49a0be63cf71
Create Date: 2026-07-10 17:10:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e278c5f13a3b"
down_revision: Union[str, Sequence[str], None] = "49a0be63cf71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER FUNCTION public.prevent_profile_snapshot_update() "
        "SET search_path = pg_catalog"
    )


def downgrade() -> None:
    op.execute(
        "ALTER FUNCTION public.prevent_profile_snapshot_update() "
        "RESET search_path"
    )
