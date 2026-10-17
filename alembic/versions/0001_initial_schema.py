"""Create the initial VoiceShop schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("nickname", sa.Text),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("slots_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("phase", sa.Text, nullable=False, server_default="INTENT"),
        sa.Column("updated_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text),
        sa.Column("role", sa.Text),
        sa.Column("content", sa.Text),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Integer, primary_key=True),
        sa.Column("profile_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "behaviors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("product_id", sa.Integer),
        sa.Column("event", sa.Text),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_no", sa.Text, unique=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("session_id", sa.Text),
        sa.Column("product_id", sa.Integer),
        sa.Column("quantity", sa.Integer),
        sa.Column("status", sa.Text),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_no", sa.Text),
        sa.Column("event", sa.Text),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "faqs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("question", sa.Text),
        sa.Column("answer", sa.Text),
        sa.Column("category", sa.Text),
    )
    op.create_table(
        "traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.Text),
        sa.Column("session_id", sa.Text),
        sa.Column("payload_json", sa.Text),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.Text),
        sa.Column("node", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("prompt_version", sa.Text),
        sa.Column("latency_ms", sa.Float),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("total_tokens", sa.Integer),
        sa.Column("estimated_cost", sa.Float),
        sa.Column("status", sa.Text),
        sa.Column("error_type", sa.Text),
        sa.Column("fallback", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.Text, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.get_bind().exec_driver_sql(
        "INSERT INTO users(id, nickname) VALUES (1, 'Demo User') ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    for name in (
        "model_calls",
        "traces",
        "faqs",
        "order_events",
        "orders",
        "behaviors",
        "profiles",
        "messages",
        "sessions",
        "users",
    ):
        op.drop_table(name)
