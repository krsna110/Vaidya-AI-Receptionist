"""Track pending bookings and keep slot reservations unique across retries.

Revision ID: 0003_booking_status
Revises: 0002_booking_safety
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_booking_status"
down_revision = "0002_booking_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("appointments")}
    if "booking_status" not in columns:
        op.add_column(
            "appointments",
            sa.Column("booking_status", sa.String(length=20), nullable=True),
        )

    # Preserve the meaning of rows that predate the explicit booking lifecycle.
    op.execute(sa.text("""
        UPDATE appointments
        SET booking_status = CASE
            WHEN is_confirmed IS TRUE THEN 'confirmed'
            ELSE 'cancelled'
        END
        WHERE booking_status IS NULL
    """))

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("appointments")}
    if "uq_confirmed_appointment_slot" in indexes:
        op.drop_index("uq_confirmed_appointment_slot", table_name="appointments")

    with op.batch_alter_table("appointments") as batch_op:
        batch_op.alter_column(
            "booking_status",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default="pending",
        )

    duplicates = op.get_bind().execute(sa.text("""
        SELECT date, time, COUNT(*) AS total
        FROM appointments
        WHERE booking_status IN ('pending', 'confirmed')
          AND date IS NOT NULL AND time IS NOT NULL
        GROUP BY date, time
        HAVING COUNT(*) > 1
    """)).fetchall()
    if duplicates:
        raise RuntimeError(
            "Cannot enforce active booking slot uniqueness: duplicate date/time rows exist. "
            "Resolve these appointments manually, then rerun the migration."
        )

    op.create_index(
        "uq_confirmed_appointment_slot",
        "appointments",
        ["date", "time"],
        unique=True,
        sqlite_where=sa.text("booking_status IN ('pending', 'confirmed')"),
        postgresql_where=sa.text("booking_status IN ('pending', 'confirmed')"),
    )


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("appointments")}
    if "uq_confirmed_appointment_slot" in indexes:
        op.drop_index("uq_confirmed_appointment_slot", table_name="appointments")
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_column("booking_status")
