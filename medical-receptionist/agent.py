import asyncio
import json
import logging
import os
import re
from typing import Literal

from dotenv import load_dotenv
from google import genai
from groq import Groq
from langdetect import detect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY not set")
if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY not set")

logger = logging.getLogger(__name__)
CLINIC_INFO_PATH = os.path.join(BASE_DIR, "data", "clinic_info.json")


class PatientData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    phone: str | None = None
    date: str | None = None
    time: str | None = None
    reason: str | None = None


class ReceptionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    intent: Literal["BOOKING", "FAQ", "CANCEL", "RESCHEDULE", "GREETING", "UNKNOWN"] = "UNKNOWN"
    response: str = ""
    language: str = "en"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    data: PatientData = Field(default_factory=PatientData)


class Agent:
    def __init__(self):
        self.gemini_api_key = GEMINI_API_KEY
        self.groq_api_key = GROQ_API_KEY

        if not self.gemini_api_key and not self.groq_api_key:
            logger.warning(
                "Both GEMINI_API_KEY and GROQ_API_KEY are missing. "
                "The agent will return fallback responses."
            )

        self.clinic_info = self._load_clinic_info()

        self.gemini_client = None
        if self.gemini_api_key:
            try:
                self.gemini_client = genai.Client(api_key=self.gemini_api_key)
                logger.info("Gemini client initialized (google-genai SDK).")
            except Exception as e:
                logger.warning("Could not initialise Gemini client: %s", type(e).__name__)

        self.groq_client = None
        if self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
                logger.info("Groq client initialized.")
            except Exception as e:
                logger.warning("Could not initialise Groq client: %s", type(e).__name__)

        self.system_prompt = f"""You are Vaidya AI, an intelligent medical receptionist for
Indian dental and medical clinics.

PERSONALITY:
- Warm, professional, and empathetic
- Respond in the SAME language as the patient (English, Hindi, or Hinglish)
- Keep responses concise - max 3 sentences
- Never make up medical information

YOUR CAPABILITIES:
1. Book appointments (collect: name, phone, date, time, reason)
2. Answer FAQs about clinic (use clinic_info only)
3. Cancel/reschedule appointments
4. Send reminders and follow-ups

RESPONSE FORMAT (ALWAYS return valid JSON):
{{
  "intent": "BOOKING|FAQ|CANCEL|GREETING|UNKNOWN",
  "response": "your message to patient",
  "language": "en|hi|hinglish",
  "confidence": 0.0-1.0,
  "data": {{
    "name": null,
    "phone": null,
    "date": null,
    "time": null,
    "reason": null
  }}
}}

RULES:
- If confidence < 0.6, set intent to UNKNOWN and ask to clarify
- Never invent clinic information not in the context
- Always collect name and phone before confirming booking
- If patient seems distressed, respond with extra empathy
- For UNKNOWN intent, ask ONE clarifying question only

CLINIC CONTEXT:
{json.dumps(self.clinic_info, indent=2)}
"""

    @staticmethod
    def _load_clinic_info() -> dict:
        try:
            with open(CLINIC_INFO_PATH, "r", encoding="utf-8") as clinic_file:
                return json.load(clinic_file)
        except Exception as e:
            logger.warning("Could not load clinic info: %s", type(e).__name__)
            return {}

    def detect_language(self, text: str) -> str:
        # Short mixed-script messages are frequently misclassified by statistical
        # language detectors. Prefer explicit script/clinic markers first so the
        # receptionist remains predictable for Hindi and Hinglish patients.
        value = (text or "").strip().lower()
        if re.search(r"[\u0900-\u097f]", value):
            return "Hindi"
        hinglish_markers = ("kya", "aap", "hai", "kaise", "mujhe", "kal", "baje", "chahiye", "karna")
        if any(re.search(rf"\b{re.escape(word)}\b", value) for word in hinglish_markers):
            return "Hinglish"
        try:
            lang = detect(text)
            if lang == "hi":
                return "Hindi"
            if lang == "en":
                return "English"
            return "English"
        except Exception:
            return "English"

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(cleaned)

    @staticmethod
    def _validate_response(payload: dict) -> dict:
        parsed = ReceptionResponse.model_validate(payload)
        return parsed.model_dump(exclude_none=True)

    def extract_patient_data(self, message: str, history: list | None = None) -> dict:
        if history is None:
            history = []

        name = None
        phone = None
        date = None
        time = None
        reason = None

        phone_match = re.search(r"\b([6-9]\d{9})\b", message)
        if phone_match:
            phone = phone_match.group(1)

        name_prompt = (
            "Extract the patient's name from the following message. "
            "If no name is present, return null. Return only the name, no other text. "
            f"Message: {message}"
        )
        if self.gemini_client:
            try:
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=name_prompt,
                )
                extracted_name = (response.text or "").strip()
                if extracted_name and extracted_name.lower() != "null":
                    name = extracted_name
            except Exception as e:
                logger.warning("Gemini name extraction failed: %s", type(e).__name__)

        date_match = re.search(r"\b(today|tomorrow|\d{4}-\d{2}-\d{2})\b", message, re.IGNORECASE)
        if date_match:
            date = date_match.group(1)

        time_match = re.search(r"(?<![-\d])\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))\b", message, re.IGNORECASE)
        if time_match:
            time = time_match.group(1)

        reason_match = re.search(r"for (\w[\w\s-]+)", message, re.IGNORECASE)
        if reason_match:
            reason = reason_match.group(1).strip()

        return {key: value for key, value in {"name": name, "phone": phone, "date": date, "time": time, "reason": reason}.items() if value}

    def generate_response(self, user_message: str, conversation_history: list | None = None) -> dict:
        if conversation_history is None:
            conversation_history = []

        detected_lang = self.detect_language(user_message)

        history_string = ""
        if conversation_history:
            history_string = "Previous conversation:\n"
            for msg in conversation_history[-6:]:
                history_string += f"{msg['role'].capitalize()}: {msg['content']}\n"
            history_string += "\n"

        full_prompt = (
            f"{self.system_prompt}\n"
            f"{history_string}"
            f"Current message: {user_message}\n\n"
            "Respond as Vaidya AI receptionist. Ensure the output is a valid JSON object."
        )

        if self.gemini_client and self.gemini_api_key:
            try:
                logger.info("Using Gemini (gemini-2.0-flash) for response generation...")

                async def gemini_call() -> dict:
                    response = await asyncio.to_thread(
                        self.gemini_client.models.generate_content,
                        model="gemini-2.0-flash",
                        contents=full_prompt,
                    )
                    parsed = self._extract_json(response.text)
                    if "language" not in parsed:
                        parsed["language"] = detected_lang.lower()
                    if "confidence" not in parsed:
                        parsed["confidence"] = 0.9
                    return self._validate_response(parsed)

                return asyncio.run(asyncio.wait_for(gemini_call(), timeout=10.0))
            except TimeoutError:
                logger.warning("Gemini call timed out after 10 seconds. Falling back to Groq...")
            except Exception as e:
                logger.warning("Gemini failed: %s. Falling back to Groq...", type(e).__name__)

        if self.groq_client and self.groq_api_key:
            try:
                logger.info("Using Groq (llama-3.3-70b-versatile) for response generation...")
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": full_prompt},
                    ],
                    model="llama-3.3-70b-versatile",
                    response_format={"type": "json_object"},
                )
                json_response = json.loads(chat_completion.choices[0].message.content)
                if "language" not in json_response:
                    json_response["language"] = detected_lang.lower()
                if "confidence" not in json_response:
                    json_response["confidence"] = 0.7
                return self._validate_response(json_response)
            except Exception as groq_e:
                logger.error("Groq also failed: %s", type(groq_e).__name__)

        logger.warning("AI providers unavailable; using deterministic receptionist fallback.")
        text = user_message.strip().lower()
        data = self.extract_patient_data(user_message, conversation_history)
        if any(word in text for word in ("hello", "hi", "namaste", "hey", "नमस्ते", "नमस्कार")) and not any(word in text for word in ("book", "appointment", "schedule", "अपॉइंटमेंट")):
            return {"intent": "GREETING", "response": "Namaste! I’m Vaidya AI. Would you like to book an appointment or ask about the clinic?", "language": "en", "confidence": 0.95, "data": data}
        if "reschedule" in text or "reschedule" in text:
            return {"intent": "RESCHEDULE", "response": "I can help reschedule that. Please provide the appointment ID, new date, and new time.", "language": "en", "confidence": 0.9, "data": data}
        if any(word in text for word in ("cancel", "cancellation")):
            return {"intent": "CANCEL", "response": "I can help with that. Please share your appointment ID or the phone number used for booking.", "language": "en", "confidence": 0.9, "data": data}
        if any(word in text for word in ("book", "appointment", "schedule", "consult", "visit", "अपॉइंटमेंट", "मुलाकात")) or any(data.values()):
            return {"intent": "BOOKING", "response": "Sure, I can help you book an appointment.", "language": "en", "confidence": 0.9, "data": data}
        if any(word in text for word in ("hours", "timing", "open", "address", "location", "fee", "services")):
            return {"intent": "FAQ", "response": self._faq_response(text), "language": "en", "confidence": 0.85, "data": data}
        return {"intent": "UNKNOWN", "response": "I can help book an appointment or answer questions about our clinic. Which would you prefer?", "language": "en", "confidence": 0.4, "data": data}

    def _faq_response(self, text: str) -> str:
        info = self.clinic_info
        if any(word in text for word in ("hours", "timing", "open")):
            hours = info.get("hours") or info.get("timings")
            if isinstance(hours, dict):
                return "Our hours are Monday to Friday, 9 AM to 6 PM, and Saturday 10 AM to 3 PM. We’re closed Sundays."
            return str(hours or "Please call the clinic for today’s timings.")
        if any(word in text for word in ("address", "location")):
            return str(info.get("address") or info.get("location") or "Please call the clinic for the address.")
        if "fee" in text or "price" in text:
            return str(info.get("fees") or info.get("pricing") or "Please call the clinic for fee details.")
        return "I can share clinic timings, location, services, and fees. What would you like to know?"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = Agent()
    print(agent.generate_response("Hello, I want to book an appointment for dental cleaning."))
    print(agent.generate_response("What are your clinic hours?"))
