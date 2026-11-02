"""Initial Vaidya AI schema baseline.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("phone_number", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.UniqueConstraint("phone_number", name="uq_patients_phone_number"),
        sa.UniqueConstraint("email", name="uq_patients_email"),
    )
    op.create_index("ix_patients_id", "patients", ["id"])
    op.create_index("ix_patients_name", "patients", ["name"])
    op.create_index("ix_patients_phone_number", "patients", ["phone_number"])
    op.create_index("ix_patients_email", "patients", ["email"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=True),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("time", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("google_event_id", sa.String(), nullable=True),
        sa.Column("reminder_status", sa.String(), nullable=True),
        sa.Column("followup_status", sa.String(), nullable=True),
    )
    op.create_index("ix_appointments_id", "appointments", ["id"])
    op.create_index("ix_appointments_description", "appointments", ["description"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("sender_type", sa.String(), nullable=True),
        sa.Column("speaker", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"])
    op.create_index("ix_conversations_session_id", "conversations", ["session_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "conversation_states",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.Column("data", sa.String(), nullable=True),
    )
    op.create_index("ix_conversation_states_user_id", "conversation_states", ["user_id"])

    op.create_table(
        "processed_webhook_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "message_id", name="uq_processed_webhook_provider_message"),
    )
    op.create_index("ix_processed_webhook_messages_id", "processed_webhook_messages", ["id"])


def downgrade() -> None:
    op.drop_table("processed_webhook_messages")
    op.drop_index("ix_conversation_states_user_id", table_name="conversation_states")
    op.drop_table("conversation_states")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_conversations_session_id", table_name="conversations")
    op.drop_index("ix_conversations_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_appointments_description", table_name="appointments")
    op.drop_index("ix_appointments_id", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_patients_email", table_name="patients")
    op.drop_index("ix_patients_phone_number", table_name="patients")
    op.drop_index("ix_patients_name", table_name="patients")
    op.drop_index("ix_patients_id", table_name="patients")
    op.drop_table("patients")
