from dotenv import load_dotenv
import os

load_dotenv()

required_vars = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY", 
    "JWT_SECRET",
]

missing = []
for var in required_vars:
    val = os.getenv(var)
    if val:
        print(f"? {var} = {val[:8]}...")
    else:
        print(f"? {var} = MISSING")
        missing.append(var)

if missing:
    print(f"\n??  Missing vars: {missing}")
    print("Add them to your .env file")
else:
    print("\n? All env variables loaded")
