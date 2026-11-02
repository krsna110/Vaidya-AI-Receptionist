"""ASGI entrypoint that adds WhatsApp media routes without replacing the existing app."""
import asyncio

from main import app
from whatsapp_routes import process_pending_whatsapp_messages, router as whatsapp_router

app.include_router(whatsapp_router)
_whatsapp_worker_task: asyncio.Task | None = None


@app.on_event("startup")
async def start_whatsapp_queue_worker():
    global _whatsapp_worker_task
    if _whatsapp_worker_task is None or _whatsapp_worker_task.done():
        _whatsapp_worker_task = asyncio.create_task(process_pending_whatsapp_messages())


@app.on_event("shutdown")
async def stop_whatsapp_queue_worker():
    global _whatsapp_worker_task
    if _whatsapp_worker_task is not None:
        _whatsapp_worker_task.cancel()
        try:
            await _whatsapp_worker_task
        except asyncio.CancelledError:
            pass
        _whatsapp_worker_task = None
