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

        self.system_prompt = """You are an AI medical receptionist for a dental/medical clinic. Your purpose is to assist patients with booking appointments, answering frequently asked questions, and managing cancellations. You should be polite, helpful, and efficient. You need to detect the user's language (English, Hindi, or Hinglish) and respond in the same language. Your responses should be structured as a JSON object with the following keys:
            - "intent": One of "BOOKING", "FAQ", "CANCEL", "GREETING", "UNKNOWN"
            - "response": The natural language response to the user.
            - "data": A dictionary containing any extracted entities relevant to the intent (e.g., {"date": "2024-12-25", "time": "10:00 AM"} for BOOKING).
            
            For booking appointments, try to extract name, phone, date, time, and reason for the visit.
            Phone should be plain text as spoken by user (the backend will normalize it).
            For cancellations, try to extract appointment ID or relevant details to find the appointment.
            For FAQ, provide concise and helpful answers based on the clinic information.

            Example JSON response:
            ```json
            {
                "intent": "BOOKING",
                "response": "Certainly! What date and time would you like to book your appointment, and for what reason?",
                "data": {}
            }
            ```
            ```json
            {
                "intent": "FAQ",
                "response": "Our clinic hours are Monday to Friday, 9 AM to 6 PM.",
                "data": {}
            }
            ```
            ```json
            {
                "intent": "GREETING",
                "response": "Hello! Welcome to our clinic. How may I assist you today?",
                "data": {}
            }
            ```
            ```json
            {
                "intent": "UNKNOWN",
                "response": "I'm sorry, I don't understand. Could you please rephrase your request?",
                "data": {}
            }
            ```
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

    def generate_response(self, user_message: str) -> dict:
        detected_lang = self.detect_language(user_message)

        full_prompt = (
            f"{self.system_prompt}\nUser: {user_message}\n"
            f"Respond in {detected_lang}. Ensure the output is a valid JSON object."
        )

        # ---- Try Gemini first (new SDK) ----
        if self.gemini_client and self.gemini_api_key:
            try:
                logger.info("Using Gemini (gemini-2.0-flash) for response generation...")
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=full_prompt,
                )
                return self._extract_json(response.text)
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
                return json.loads(chat_completion.choices[0].message.content)
            except Exception as groq_e:
                logger.error(f"Groq also failed: {groq_e}")

        # ---- Both failed ----
        logger.warning("Both AI services are unavailable; using local fallback response.")
        return self._fallback_response(user_message)

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
