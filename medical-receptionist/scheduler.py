import asyncio
import logging
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from database import SessionLocal, engine
from models import Appointment, Base
from calendar_service import GoogleCalendarService

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        try:
            self.calendar_service = GoogleCalendarService()
        except Exception as e:
            logger.warning(f"Calendar service unavailable in scheduler: {e}")
            self.calendar_service = None
        self._create_db_tables()

    def _create_db_tables(self):
        # Ensure tables are created if they don't exist
        Base.metadata.create_all(bind=engine)

    async def reminder_job(self):
        logger.info("Running reminder job...")
        session = SessionLocal()
        try:
            tomorrow = datetime.now().date() + timedelta(days=1)
            appointments = (
                session.query(Appointment)
                .filter(
                    Appointment.date == tomorrow.isoformat(),
                    Appointment.reminder_status == None,
                )
                .all()
            )

            for appt in appointments:
                try:
                    # Get patient info via relationship (may be None)
                    patient_name = appt.patient.name if appt.patient else "Patient"
                    patient_phone = appt.patient.phone_number if appt.patient else "N/A"

                    reminder_message = (
                        f"Reminder: Your appointment for {appt.reason} "
                        f"is tomorrow, {appt.date} at {appt.time}."
                    )
                    logger.info(
                        f"Reminder for {patient_name} ({patient_phone}): {reminder_message}"
                    )

                    appt.reminder_status = "pending_reminder"
                    session.add(appt)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(
                        f"Error processing reminder for appointment {appt.id}: {e}"
                    )
        except Exception as e:
            logger.error(f"Error in reminder job: {e}")
        finally:
            session.close()

    async def followup_job(self):
        logger.info("Running follow-up job...")
        session = SessionLocal()
        try:
            today = datetime.now().date()
            appointments = (
                session.query(Appointment)
                .filter(
                    Appointment.date == today.isoformat(),
                    Appointment.followup_status == None,
                )
                .all()
            )

            for appt in appointments:
                try:
                    patient_name = appt.patient.name if appt.patient else "Patient"
                    patient_phone = appt.patient.phone_number if appt.patient else "N/A"

                    followup_message = (
                        f"Hello {patient_name}, how was your {appt.reason} "
                        f"appointment today? We appreciate your feedback."
                    )
                    logger.info(
                        f"Follow-up for {patient_name} ({patient_phone}): {followup_message}"
                    )

                    appt.followup_status = "pending_followup"
                    session.add(appt)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(
                        f"Error processing follow-up for appointment {appt.id}: {e}"
                    )
        except Exception as e:
            logger.error(f"Error in follow-up job: {e}")
        finally:
            session.close()

    def start(self):
        if self.scheduler.running:
            logger.info("Scheduler already running; skipping start.")
            return
        self.scheduler.add_job(self.reminder_job, "cron", hour=9, minute=0)
        self.scheduler.add_job(self.followup_job, "cron", hour=18, minute=0)
        logger.info("Scheduler started with reminder (9 AM) and follow-up (6 PM) jobs.")
        self.scheduler.start()

    def shutdown(self):
        if not self.scheduler.running:
            logger.info("Scheduler is not running; skipping shutdown.")
            return
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scheduler_instance = Scheduler()
    scheduler_instance.start()

    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler_instance.shutdown()
