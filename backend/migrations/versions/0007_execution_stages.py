"""Persist observed execution stage timing without changing request states."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_execution_stages'
down_revision = '0006_real_results'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('request_intents', sa.Column('execution_stages', JSONB, nullable=False,
                                             server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint('ck_execution_stages', 'request_intents',
                              "jsonb_typeof(execution_stages)='array' AND jsonb_array_length(execution_stages)<=16")


def downgrade():
    op.drop_constraint('ck_execution_stages', 'request_intents', type_='check')
    op.drop_column('request_intents', 'execution_stages')
