from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from database import Base
import datetime

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    phone_number = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)

    appointments = relationship("Appointment", back_populates="patient")
    conversations = relationship("Conversation", back_populates="patient")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime)
    description = Column(String, index=True)
    is_confirmed = Column(Boolean, default=False)
    date = Column(String)  # Storing date as string for simplicity with current calendar_service
    time = Column(String)  # Storing time as string
    reason = Column(String) # Storing reason directly
    google_event_id = Column(String, nullable=True)
    reminder_status = Column(String, nullable=True) # e.g., "pending_reminder", "sent", "failed"
    followup_status = Column(String, nullable=True) # e.g., "pending_followup", "sent", "failed"

    patient = relationship("Patient", back_populates="appointments")





class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    speaker = Column(String)  # 'patient' or 'receptionist'
    message = Column(Text)

    patient = relationship("Patient", back_populates="conversations")
