"""Create missing Vaidya tables and upgrade legacy booking columns.

Revision ID: 0001_baseline
Revises:
"""
from alembic import op
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, inspect, text

from database import Base
import models
import state

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _add_missing_columns(connection, table_name, columns):
    inspector = inspect(connection)
    if not inspector.has_table(table_name):
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def upgrade():
    connection = op.get_bind()

    # Upgrade the legacy columns that the previous app attempted to add only on SQLite.
    _add_missing_columns(connection, "appointments", [
        Column("patient_id", Integer(), nullable=True),
        Column("start_time", DateTime(), nullable=True),
        Column("end_time", DateTime(), nullable=True),
        Column("description", String(), nullable=True),
        Column("is_confirmed", Boolean(), nullable=True),
        Column("date", String(), nullable=True),
        Column("time", String(), nullable=True),
        Column("reason", String(), nullable=True),
        Column("google_event_id", String(), nullable=True),
        Column("reminder_status", String(), nullable=True),
        Column("followup_status", String(), nullable=True),
    ])
    _add_missing_columns(connection, "conversations", [
        Column("patient_id", Integer(), nullable=True),
        Column("session_id", String(), nullable=True),
        Column("timestamp", DateTime(), nullable=True),
        Column("sender_type", String(), nullable=True),
        Column("speaker", String(), nullable=True),
        Column("message", Text(), nullable=True),
    ])

    # Preserve the oldest active booking if a legacy database already contains
    # duplicate confirmed slots, then let metadata create the partial unique index.
    inspector = inspect(connection)
    if inspector.has_table("appointments"):
        cols = {column["name"] for column in inspector.get_columns("appointments")}
        if {"id", "date", "time", "is_confirmed"}.issubset(cols):
            confirmed = "1" if connection.dialect.name == "sqlite" else "TRUE"
            not_confirmed = "0" if connection.dialect.name == "sqlite" else "FALSE"
            connection.execute(text(f"""
                UPDATE appointments
                SET is_confirmed = {not_confirmed}
                WHERE is_confirmed = {confirmed}
                  AND id NOT IN (
                    SELECT MIN(id)
                    FROM appointments
                    WHERE is_confirmed = {confirmed}
                    GROUP BY date, time
                  )
            """))

    Base.metadata.create_all(bind=connection)


def downgrade():
    # This baseline may be applied to an existing production database. Automatic
    # table drops would destroy patient and appointment records, so downgrade is
    # intentionally non-destructive; roll back with a reviewed forward migration.
    pass
