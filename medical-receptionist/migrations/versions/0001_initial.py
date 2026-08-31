"""Initial Vaidya schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("patients", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String()), sa.Column("phone_number", sa.String()), sa.Column("email", sa.String()))
    op.create_index("ix_patients_id", "patients", ["id"])
    op.create_index("ix_patients_name", "patients", ["name"])
    op.create_index("ix_patients_phone_number", "patients", ["phone_number"], unique=True)
    op.create_index("ix_patients_email", "patients", ["email"], unique=True)
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("username", sa.String()), sa.Column("email", sa.String()), sa.Column("hashed_password", sa.String()), sa.Column("created_at", sa.DateTime()))
    op.create_index("ix_users_id", "users", ["id"]); op.create_index("ix_users_username", "users", ["username"], unique=True); op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("appointments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id")), sa.Column("session_id", sa.String()), sa.Column("start_time", sa.DateTime()), sa.Column("end_time", sa.DateTime()), sa.Column("description", sa.String()), sa.Column("is_confirmed", sa.Boolean()), sa.Column("status", sa.String()), sa.Column("date", sa.String()), sa.Column("time", sa.String()), sa.Column("reason", sa.String()), sa.Column("google_event_id", sa.String()), sa.Column("reminder_status", sa.String()), sa.Column("followup_status", sa.String()))
    op.create_index("ix_appointments_id", "appointments", ["id"]); op.create_index("ix_appointments_session_id", "appointments", ["session_id"]); op.create_index("ix_appointments_description", "appointments", ["description"]); op.create_index("ix_appointments_status", "appointments", ["status"])
    op.create_index("uq_active_appointment_slot", "appointments", ["date", "time"], unique=True, sqlite_where=sa.text("is_confirmed = 1"), postgresql_where=sa.text("is_confirmed = true"))
    op.create_table("conversations", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id")), sa.Column("session_id", sa.String()), sa.Column("timestamp", sa.DateTime()), sa.Column("sender_type", sa.String()), sa.Column("speaker", sa.String()), sa.Column("message", sa.Text()))
    op.create_index("ix_conversations_id", "conversations", ["id"]); op.create_index("ix_conversations_session_id", "conversations", ["session_id"])
    op.create_table("conversation_states", sa.Column("user_id", sa.String(), primary_key=True), sa.Column("state", sa.String()), sa.Column("last_updated", sa.DateTime()), sa.Column("data", sa.String()))
    op.create_index("ix_conversation_states_user_id", "conversation_states", ["user_id"])

def downgrade():
    op.drop_table("conversation_states"); op.drop_table("conversations"); op.drop_index("uq_active_appointment_slot", table_name="appointments"); op.drop_table("appointments"); op.drop_table("users"); op.drop_table("patients")
