"""Persist provisional request intents.

Revision ID: 0003_request_intents
Revises: 0002_publication_state
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_request_intents'
down_revision = '0002_publication_state'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'request_intents',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('client_request_id', sa.Uuid(), nullable=False, unique=True),
        sa.Column('dataset_id', sa.Uuid(), sa.ForeignKey('datasets.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('claim_token', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint('char_length(question) BETWEEN 1 AND 4096', name='ck_request_question'),
        sa.CheckConstraint("status IN ('queued', 'running', 'fake_completed', 'unknown')", name='ck_request_status'),
        sa.CheckConstraint("(status = 'running') = (claim_token IS NOT NULL)", name='ck_request_claim'),
    )
    op.create_index('uq_request_single_running', 'request_intents', [sa.text('(1)')],
                    unique=True, postgresql_where=sa.text("status = 'running'"))
    op.create_index('ix_request_fifo', 'request_intents', ['created_at', 'id'])


def downgrade():
    op.drop_table('request_intents')
