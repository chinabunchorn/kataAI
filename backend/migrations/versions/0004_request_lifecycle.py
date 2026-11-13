"""Add cancellable claims and retained hidden terminal history.

Revision ID: 0004_request_lifecycle
Revises: 0003_request_intents
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_request_lifecycle'
down_revision = '0003_request_intents'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('request_intents', sa.Column('hidden_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_index('uq_request_single_running', table_name='request_intents')
    op.drop_constraint('ck_request_status', 'request_intents', type_='check')
    op.drop_constraint('ck_request_claim', 'request_intents', type_='check')
    op.create_check_constraint('ck_request_status', 'request_intents',
                               "status IN ('queued','running','cancel_requested','cancelled','fake_completed','unknown')")
    op.create_check_constraint('ck_request_claim', 'request_intents',
                               "(status IN ('running','cancel_requested')) = (claim_token IS NOT NULL)")
    op.create_check_constraint('ck_request_hidden', 'request_intents',
                               "hidden_at IS NULL OR status IN ('cancelled','fake_completed')")
    op.create_index('uq_request_single_running', 'request_intents', [sa.text('(1)')], unique=True,
                    postgresql_where=sa.text("status IN ('running','cancel_requested')"))


def downgrade():
    # Hold the lock through the migration so no concurrent writer can make the
    # precondition false after it is checked. Never erase retained visibility.
    op.execute('LOCK TABLE request_intents IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM request_intents WHERE hidden_at IS NOT NULL
                   OR status IN ('cancel_requested','cancelled')) THEN
            RAISE EXCEPTION 'irreversible request lifecycle state';
        END IF;
    END $$""")
    op.drop_index('uq_request_single_running', table_name='request_intents')
    op.drop_constraint('ck_request_hidden', 'request_intents', type_='check')
    op.drop_constraint('ck_request_claim', 'request_intents', type_='check')
    op.drop_constraint('ck_request_status', 'request_intents', type_='check')
    op.create_check_constraint('ck_request_status', 'request_intents',
                               "status IN ('queued','running','fake_completed','unknown')")
    op.create_check_constraint('ck_request_claim', 'request_intents',
                               "(status = 'running') = (claim_token IS NOT NULL)")
    op.create_index('uq_request_single_running', 'request_intents', [sa.text('(1)')], unique=True,
                    postgresql_where=sa.text("status = 'running'"))
    op.drop_column('request_intents', 'hidden_at')
