"""Provisional dataset metadata only.

Revision ID: 0001_datasets
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0001_datasets'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'datasets',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('storage_key', UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('lifecycle', sa.String(16), nullable=False, server_default='active'),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("char_length(display_name) BETWEEN 1 AND 255 AND "
                           "display_name = btrim(display_name) AND "
                           "display_name !~ '[[:cntrl:]/\\\\]' AND "
                           "display_name NOT IN ('.', '..')", name='ck_dataset_display_name'),
        sa.CheckConstraint("(lifecycle = 'active' AND deleted_at IS NULL) OR "
                           "(lifecycle = 'deleted' AND deleted_at IS NOT NULL)",
                           name='ck_dataset_lifecycle'),
    )


def downgrade():
    op.drop_table('datasets')
