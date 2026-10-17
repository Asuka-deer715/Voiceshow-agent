"""Add authentication fields to users."""

from alembic import op
import sqlalchemy as sa

revision = "0002_auth_fields"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text, nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.Text, nullable=True))
    op.add_column("users", sa.Column("role", sa.Text, nullable=False, server_default="user"))
    op.create_index("uq_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_email", table_name="users")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
