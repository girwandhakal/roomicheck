"""Revoke public execution of the RLS event-trigger function.

Revision ID: f5b9d2e8c741
Revises: e278c5f13a3b
Create Date: 2026-07-10 17:20:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f5b9d2e8c741"
down_revision: Union[str, Sequence[str], None] = "e278c5f13a3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC")


def downgrade() -> None:
    op.execute("GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO PUBLIC")
