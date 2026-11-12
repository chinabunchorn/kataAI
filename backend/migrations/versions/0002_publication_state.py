"""Separate file-publication readiness from dataset lifecycle.

Revision ID: 0002_publication_state
Revises: 0001_datasets
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_publication_state'
down_revision = '0001_datasets'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('datasets', sa.Column('publication_state', sa.String(16), nullable=False,
                                        server_default='unknown'))
    op.create_check_constraint('ck_dataset_publication_state', 'datasets',
                               "publication_state IN ('unknown', 'pending', 'ready')")


def downgrade():
    op.drop_constraint('ck_dataset_publication_state', 'datasets', type_='check')
    op.drop_column('datasets', 'publication_state')
