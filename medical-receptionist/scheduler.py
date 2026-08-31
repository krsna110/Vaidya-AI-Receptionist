import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from database import SessionLocal
from models import Appointment
from calendar_service import GoogleCalendarService

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logger = logging.getLogger(__name__)
CLINIC_TIMEZONE = ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))


class Scheduler:
    def __init__(self):
        self.enabled = os.getenv("SCHEDULER_ENABLED", "false").lower() == "true"
        self.scheduler = AsyncIOScheduler(timezone=CLINIC_TIMEZONE)
        try:
            self.calendar_service = GoogleCalendarService()
        except Exception as e:
            logger.warning(f"Calendar service unavailable in scheduler: {e}")
            self.calendar_service = None

    async def reminder_job(self):
        logger.info("Running reminder job...")
        session = SessionLocal()
        try:
            tomorrow = datetime.now(CLINIC_TIMEZONE).date() + timedelta(days=1)
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
                    # Delivery is intentionally delegated to a worker/provider;
                    # this web process only records an idempotent queue state.
                    appt.reminder_status = "pending_reminder"
                    session.add(appt)
                    session.commit()
                    logger.info("Reminder queued")
                except Exception as e:
                    session.rollback()
                    logger.error("Reminder processing failed: %s", type(e).__name__)
        except Exception as e:
            logger.error(f"Error in reminder job: {e}")
        finally:
            session.close()

    async def followup_job(self):
        logger.info("Running follow-up job...")
        session = SessionLocal()
        try:
            today = datetime.now(CLINIC_TIMEZONE).date()
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
                    appt.followup_status = "pending_followup"
                    session.add(appt)
                    session.commit()
                    logger.info("Follow-up queued")
                except Exception as e:
                    session.rollback()
                    logger.error("Follow-up processing failed: %s", type(e).__name__)
        except Exception as e:
            logger.error(f"Error in follow-up job: {e}")
        finally:
            session.close()

    def start(self):
        if not self.enabled:
            logger.info("Scheduler disabled for this web process")
            return
        if self.scheduler.running:
            logger.info("Scheduler already running; skipping start.")
            return
        self.scheduler.add_job(self.reminder_job, "cron", hour=9, minute=0)
        self.scheduler.add_job(self.followup_job, "cron", hour=18, minute=0)
        logger.info("Scheduler started with reminder (9 AM) and follow-up (6 PM) jobs.")
        self.scheduler.start()

    def shutdown(self):
        if not self.enabled:
            return
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
