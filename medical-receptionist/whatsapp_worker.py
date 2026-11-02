"""Run the durable WhatsApp webhook queue as a separate worker service."""
import asyncio
import logging
import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

from whatsapp_routes import process_next_whatsapp_message

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("whatsapp_worker")


async def run() -> None:
    poll_seconds = max(0.5, float(os.getenv("WHATSAPP_QUEUE_POLL_SECONDS", "2")))
    while True:
        try:
            worked = await process_next_whatsapp_message()
        except Exception as exc:
            logger.error("WhatsApp queue poll failed | error_type=%s", type(exc).__name__)
            worked = False
        if not worked:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(run())
