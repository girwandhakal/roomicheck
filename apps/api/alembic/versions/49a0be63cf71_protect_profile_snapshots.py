"""Protect immutable profile snapshots.

Revision ID: 49a0be63cf71
Revises: d3367e937062
Create Date: 2026-07-10 16:48:27.555118
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '49a0be63cf71'
down_revision: Union[str, Sequence[str], None] = 'd3367e937062'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_profile_snapshot_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'profile snapshots are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER prevent_profile_snapshot_update
        BEFORE UPDATE ON profile_snapshots
        FOR EACH ROW EXECUTE FUNCTION prevent_profile_snapshot_update();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER prevent_profile_snapshot_update ON profile_snapshots")
    op.execute("DROP FUNCTION prevent_profile_snapshot_update()")
