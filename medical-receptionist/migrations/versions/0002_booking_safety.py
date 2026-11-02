"""Add compatibility columns and enforce unique active booking slots.

Revision ID: 0002_booking_safety
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_booking_safety"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    # Compatibility for databases that were created before Alembic was adopted.
    appointment_columns = _columns("appointments")
    for name in ("date", "time", "reason", "google_event_id", "reminder_status", "followup_status"):
        if name not in appointment_columns:
            op.add_column("appointments", sa.Column(name, sa.String(), nullable=True))

    conversation_columns = _columns("conversations")
    for name in ("session_id", "sender_type"):
        if name not in conversation_columns:
            op.add_column("conversations", sa.Column(name, sa.String(), nullable=True))

    if "processed_webhook_messages" not in sa.inspect(op.get_bind()).get_table_names():
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

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("appointments")}
    if "uq_confirmed_appointment_slot" not in indexes:
        duplicate_slots = op.get_bind().execute(sa.text("""
            SELECT date, time, COUNT(*) AS total
            FROM appointments
            WHERE is_confirmed = 1 AND date IS NOT NULL AND time IS NOT NULL
            GROUP BY date, time
            HAVING COUNT(*) > 1
        """)).fetchall()
        if duplicate_slots:
            raise RuntimeError(
                "Cannot enforce unique confirmed appointment slots: duplicate date/time rows exist. "
                "Resolve these appointments manually, then rerun the migration."
            )
        op.create_index(
            "uq_confirmed_appointment_slot",
            "appointments",
            ["date", "time"],
            unique=True,
            sqlite_where=sa.text("is_confirmed = 1"),
            postgresql_where=sa.text("is_confirmed IS TRUE"),
        )


def downgrade() -> None:
    # Keep additive columns and the idempotency ledger during downgrade to avoid
    # deleting operational data. Only remove the uniqueness enforcement index.
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("appointments")}
    if "uq_confirmed_appointment_slot" in indexes:
        op.drop_index("uq_confirmed_appointment_slot", table_name="appointments")
