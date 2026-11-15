"""Persist optional bounded fake-only result envelopes.

Revision ID: 0005_fake_results
Revises: 0004_request_lifecycle
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0005_fake_results'
down_revision = '0004_request_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('request_intents', sa.Column('fake_result', JSONB, nullable=True))
    op.create_check_constraint(
        'ck_request_fake_result', 'request_intents',
        "fake_result IS NULL OR (status = 'fake_completed' AND jsonb_typeof(fake_result) = 'object' "
        "AND fake_result @> jsonb_build_object('fake', true) AND octet_length(fake_result::text) <= 131072)")


def downgrade():
    op.execute('LOCK TABLE request_intents IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM request_intents WHERE fake_result IS NOT NULL) THEN
            RAISE EXCEPTION 'irreversible fake result state';
        END IF;
    END $$""")
    op.drop_constraint('ck_request_fake_result', 'request_intents', type_='check')
    op.drop_column('request_intents', 'fake_result')
