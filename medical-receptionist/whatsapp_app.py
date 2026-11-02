"""ASGI entrypoint that adds WhatsApp media routes without replacing the existing app."""
from main import app
from whatsapp_routes import router as whatsapp_router

app.include_router(whatsapp_router)
