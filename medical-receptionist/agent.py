import os
import json
import re
import logging

from google import genai
from groq import Groq
from langdetect import detect

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logger = logging.getLogger(__name__)
CLINIC_INFO_PATH = os.path.join(BASE_DIR, "data", "clinic_info.json")


class Agent:
    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.groq_api_key = os.getenv("GROQ_API_KEY")

        if not self.gemini_api_key and not self.groq_api_key:
            logger.warning(
                "Both GEMINI_API_KEY and GROQ_API_KEY are missing. "
                "The agent will return fallback responses."
            )

        self.clinic_info = self._load_clinic_info()

        # --- NEW Gemini SDK (google-genai) ---
        self.gemini_client = None
        if self.gemini_api_key:
            try:
                self.gemini_client = genai.Client(api_key=self.gemini_api_key)
                logger.info("Gemini client initialized (google-genai SDK).")
            except Exception as e:
                logger.warning(f"Could not initialise Gemini client: {e}")

        # Groq client (fallback)
        self.groq_client = None
        if self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
                logger.info("Groq client initialized.")
            except Exception as e:
                logger.warning(f"Could not initialise Groq client: {e}")

        self.system_prompt = f"""You are Vaidya AI, an intelligent medical receptionist for 
Indian dental and medical clinics. 

PERSONALITY:
- Warm, professional, and empathetic
- Respond in the SAME language as the patient
  (English, Hindi, or Hinglish)
- Keep responses concise — max 3 sentences
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
            logger.warning(f"Could not load clinic info: {e}")
            return {}

    def detect_language(self, text):
        try:
            lang = detect(text)
            if lang == "hi":
                return "Hindi"
            elif lang == "en":
                return "English"
            else:
                # Basic Hinglish detection (can be improved)
                if any(word in text.lower() for word in ["kya", "aap", "hai", "kaise"]):
                    return "Hinglish"
                return "English"
        except Exception:
            return "English"

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """Strip markdown fences and parse the first JSON object found."""
        # Remove ```json ... ``` fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw_text)
        cleaned = cleaned.strip()
        # Find the first { ... } block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(cleaned)

    def extract_patient_data(self, message: str, history: list = None) -> dict:
        if history is None:
            history = []

        name = None
        phone = None
        date = None
        time = None
        reason = None

        # Regex for Indian phone numbers (10 digits, starting with 6-9)
        phone_match = re.search(r"\b([6-9]\d{9})\b", message)
        if phone_match:
            phone = phone_match.group(1)

        # NLP prompt to extract name from message
        # This will be replaced by a more robust entity extraction system in future improvements
        name_prompt = f"""Extract the patient's name from the following message. 
        If no name is present, return null. Return only the name, no other text.
        Message: """{message}"""
        """
        if self.gemini_client:
            try:
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=name_prompt,
                )
                extracted_name = response.text.strip()
                if extracted_name and extracted_name.lower() != "null":
                    name = extracted_name
            except Exception as e:
                logger.warning(f"Gemini name extraction failed: {e}")

        # Simplified date, time, reason extraction (can be improved with more advanced NLP)
        date_match = re.search(r"\b(today|tomorrow|\d{4}-\d{2}-\d{2})\b", message, re.IGNORECASE)
        if date_match:
            date = date_match.group(1)

        time_match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)\b", message, re.IGNORECASE)
        if time_match:
            time = time_match.group(1)

        # Basic reason extraction (can be improved)
        reason_match = re.search(r"for (\w[\w\s-]+)", message, re.IGNORECASE)
        if reason_match:
            reason = reason_match.group(1).strip()

        return {"name": name, "phone": phone, "date": date, "time": time, "reason": reason}


    def generate_response(self, user_message: str, conversation_history: list = None) -> dict:
        if conversation_history is None:
            conversation_history = []

        detected_lang = self.detect_language(user_message)

        # Regex for Indian phone numbers (10 digits, starting with 6-9)
        phone_match = re.search(r"\b([6-9]\d{9})\b", message)
        if phone_match:
            phone = phone_match.group(1)

        # NLP prompt to extract name from message
        name_prompt = f"""Extract the patient's name from the following message. 
        If no name is present, return null. Return only the name, no other text.
        Message: """{message}"""
        "
        response = self.gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=name_prompt,
        )
        extracted_name = response.text.strip()
        if extracted_name and extracted_name.lower() != "null":
            name = extracted_name

        # Use existing utility for date and time extraction
        extracted_details = self.extract_booking_details_from_message(message)
        date = extracted_details.get("date")
        time = extracted_details.get("time")
        reason = extracted_details.get("reason")

        return {"name": name, "phone": phone, "date": date, "time": time, "reason": reason}

    def extract_booking_details_from_message(self, message: str) -> dict:
        """Extract booking fields from common free-text patient replies, using regex for basic extraction."""
        text = (message or "").strip()
        lowered = text.lower()
        details: dict[str, str] = {}

        name_match = re.search(
            r"\\b(?:my name is|name is|name)\\s+([a-z][a-z .\'-]{1,60}?)(?=\\s+(?:and|phone|number|mobile|want|for|at|on|tomorrow|today)\\b|$)",
            lowered,
            re.IGNORECASE,
        )
        if name_match:
            details["name"] = " ".join(part.capitalize() for part in name_match.group(1).strip().split())

        phone_match = re.search(
            r"(?:\\+?\\d[\\d\\s-]{7,}\\d)",
            text,
        )
        if phone_match:
            details["phone"] = phone_match.group(0)

        date_match = re.search(
            r"\\b(today|tomorrow|tommorrow|\\d{4}-\\d{1,2}-\\d{1,2})\\b",
            lowered,
            re_IGNORECASE,
        )
        if date_match:
            details["date"] = date_match.group(1)

        time_match = re.search(r"\\b(\\d{1,2}(?::\\d{2})?\\s*(?:am|pm|a\\.m\\.|p\\.m\\.)?)\\b", lowered, re_IGNORECASE)
        if time_match:
            details["time"] = time_match.group(1)

        reason_match = re.search(
            r"\\b(?:about|for|regarding|because of|consult about|consult for)\\s+([a-z][a-z .\'-]{1,80}?)(?=\\s+(?:on|at|today|tomorrow|tommorrow)\\b|$)",
            lowered,
            re_IGNORECASE,
        )
        if reason_match:
            details["reason"] = reason_match.group(1).strip()
        elif any(word in lowered for word in ["piles", "fever", "pain", "cough", "dermatologist", "consult"]):
            symptom_match = re.search(r"\\b(?:piles|fever|pain|cough|dermatologist|consultation)\\b", lowered)
            if symptom_match:
                details["reason"] = symptom_match.group(0)

        return {key: value for key, value in details.items() if value}


    def generate_response(self, user_message: str, conversation_history: list = None) -> dict:
        if conversation_history is None:
            conversation_history = []

        detected_lang = self.detect_language(user_message)

        # Build conversation string from history (last 6 messages max)
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
            f"Respond as Vaidya AI receptionist. Ensure the output is a valid JSON object."
        )

        # ---- Try Gemini first (new SDK) ----
        if self.gemini_client and self.gemini_api_key:
            try:
                logger.info("Using Gemini (gemini-2.0-flash) for response generation...")
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=full_prompt,
                )
                json_response = self._extract_json(response.text)
                # Add language and confidence if missing (Gemini doesn't always provide)
                if "language" not in json_response:
                    json_response["language"] = detected_lang.lower()
                if "confidence" not in json_response:
                    json_response["confidence"] = 0.9 # Default high confidence for Gemini
                return json_response
            except Exception as e:
                logger.warning(f"Gemini failed: {e}. Falling back to Groq...")

        # ---- Fallback to Groq ----
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
                # Add language and confidence if missing
                if "language" not in json_response:
                    json_response["language"] = detected_lang.lower()
                if "confidence" not in json_response:
                    json_response["confidence"] = 0.7 # Default confidence for Groq
                return json_response
            except Exception as groq_e:
                logger.error(f"Groq also failed: {groq_e}")

        # ---- Final Fallback (both failed) ----
        logger.warning("Both AI services are unavailable; using hardcoded fallback response.")
        return {
            "intent": "UNKNOWN",
            "response": "I\"m having trouble right now. Please call us directly or try again in a moment.",
            "confidence": 0.0,
            "data": {}
        }

    def _fallback_response(self, user_message: str) -> dict:
        text = (user_message or "").strip().lower()
        clinic_name = self.clinic_info.get("clinic_name", "our clinic")
        phone = self.clinic_info.get("phone", "the clinic")
        faqs = self.clinic_info.get("faqs", [])

        if any(word in text for word in ["hello", "hi", "hey", "namaste"]):
            return {
                "intent": "GREETING",
                "response": f"Hello! Welcome to {clinic_name}. How may I assist you today?",
                "data": {},
            }

        if any(word in text for word in ["book", "appointment", "schedule"]):
            return {
                "intent": "BOOKING",
                "response": "Sure, I can help book an appointment. Please share your name, phone number, preferred date, time, and reason for the visit.",
                "data": {},
            }

        if any(word in text for word in ["cancel", "reschedule"]):
            return {
                "intent": "CANCEL",
                "response": "I can help with that. Please share your appointment ID.",
                "data": {},
            }

        for faq in faqs:
            question = faq.get("question", "").lower()
            if "hours" in text and "hours" in question:
                return {"intent": "FAQ", "response": faq.get("answer", ""), "data": {}}
            if "insurance" in text and "insurance" in question:
                return {"intent": "FAQ", "response": faq.get("answer", ""), "data": {}}
            if "cost" in text and ("cost" in question or "cleaning" in question):
                return {"intent": "FAQ", "response": faq.get("answer", ""), "data": {}}

        return {
            "intent": "FAQ",
            "response": f"I can help with appointments, clinic hours, services, cancellations, and general questions. You can also call us at {phone}.",
            "data": {},
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = Agent()
    print(agent.generate_response("Hello, I want to book an appointment for dental cleaning."))
    print(agent.generate_response("What are your clinic hours?"))
