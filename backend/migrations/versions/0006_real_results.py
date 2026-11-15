"""Minimal opt-in Kata MVP outcomes; preserve fake history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006_real_results'
down_revision = '0005_fake_results'
branch_labels = None
depends_on = None

OLD = "'queued','running','cancel_requested','cancelled','fake_completed','unknown'"


def upgrade():
    for column in (sa.Column('run_id', sa.Uuid(), unique=True),
                   sa.Column('real_result', JSONB), sa.Column('generated_code', sa.Text()),
                   sa.Column('answer', sa.Text()), sa.Column('error_code', sa.String(64))):
        op.add_column('request_intents', column)
    op.drop_constraint('ck_request_status', 'request_intents', type_='check')
    op.create_check_constraint('ck_request_status', 'request_intents',
                              f"status IN ({OLD},'completed','failed','needs_clarification')")
    op.create_check_constraint('ck_request_real_result', 'request_intents',
        "(status <> 'completed' OR (run_id IS NOT NULL AND real_result IS NOT NULL)) AND "
        "(real_result IS NULL OR (status='completed' AND jsonb_typeof(real_result) IN ('object','array'))) AND "
        "(generated_code IS NULL OR octet_length(generated_code) <= 16384) AND "
        "(answer IS NULL OR octet_length(answer) <= 8192) AND "
        "(status <> 'fake_completed' OR run_id IS NULL)")


def downgrade():
    op.execute('LOCK TABLE request_intents IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM request_intents WHERE run_id IS NOT NULL OR real_result IS NOT NULL
                   OR generated_code IS NOT NULL OR answer IS NOT NULL OR error_code IS NOT NULL
                   OR status IN ('completed','failed','needs_clarification')) THEN
            RAISE EXCEPTION 'irreversible real execution state';
        END IF;
    END $$""")
    op.drop_constraint('ck_request_real_result', 'request_intents', type_='check')
    op.drop_constraint('ck_request_status', 'request_intents', type_='check')
    op.create_check_constraint('ck_request_status', 'request_intents', f'status IN ({OLD})')
    for name in ('error_code', 'answer', 'generated_code', 'real_result', 'run_id'):
        op.drop_column('request_intents', name)
