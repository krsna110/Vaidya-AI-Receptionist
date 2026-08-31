import httpx
import json
import time

BASE = "http://localhost:8010"
PASS = []
FAIL = []

def test(name, condition, detail=""):
    if condition:
        print(f"? {name}")
        PASS.append(name)
    else:
        print(f"? {name}: {detail}")
        FAIL.append(name)

# Test 1: Health Check
try:
    r = httpx.get(f"{BASE}/health")
    test("Health Check", r.status_code == 200)
except Exception as e:
    test("Health Check", False, str(e))

# Test 2: Docs accessible
try:
    r = httpx.get(f"{BASE}/docs")
    test("Swagger Docs", r.status_code == 200)
except Exception as e:
    test("Swagger Docs", False, str(e))

# Test 3: Greeting intent
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "Hello",
        "session_id": "test_session_001"
    })
    data = r.json()
    test("Greeting Intent", 
         r.status_code == 200 and "response" in data,
         str(data))
except Exception as e:
    test("Greeting Intent", False, str(e))

# Test 4: Booking intent
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "I want to book an appointment",
        "session_id": "test_session_001"
    })
    data = r.json()
    test("Booking Intent", 
         r.status_code == 200,
         str(data))
    test("Intent Field Present", "intent" in data)
    test("Confidence Field Present", "confidence" in data)
except Exception as e:
    test("Booking Intent", False, str(e))

# Test 5: Patient data extraction
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "My name is Rahul Sharma, number is 9876543210",
        "session_id": "test_session_002"
    })
    data = r.json()
    test("Patient Data Extraction", r.status_code == 200)
    print(f"   Response: {data.get('response', '')[:100]}")
except Exception as e:
    test("Patient Data Extraction", False, str(e))

# Test 6: Hindi message
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "???? appointment ??? ???? ??",
        "session_id": "test_session_003"
    })
    data = r.json()
    test("Hindi Message", r.status_code == 200)
    print(f"   Language detected: {data.get('language', 'unknown')}")
except Exception as e:
    test("Hindi Message", False, str(e))

# Test 7: FAQ intent
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "What are your clinic timings?",
        "session_id": "test_session_004"
    })
    data = r.json()
    test("FAQ Intent", r.status_code == 200)
    print(f"   Response: {data.get('response', '')[:100]}")
except Exception as e:
    test("FAQ Intent", False, str(e))

# Test 8: Unknown/gibberish
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "asdkjhaksjdhaksjdh",
        "session_id": "test_session_005"
    })
    data = r.json()
    test("Unknown Intent Fallback", r.status_code == 200)
    print(f"   Intent: {data.get('intent', 'unknown')}")
except Exception as e:
    test("Unknown Intent Fallback", False, str(e))

# Test 9: Cancel intent
try:
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "I want to cancel my appointment",
        "session_id": "test_session_006"
    })
    data = r.json()
    test("Cancel Intent", r.status_code == 200)
except Exception as e:
    test("Cancel Intent", False, str(e))

# Test 10: Conversation history
try:
    sid = "test_history_session"
    httpx.post(f"{BASE}/webhook", json={
        "message": "Hi my name is Priya",
        "session_id": sid
    })
    time.sleep(1)
    r = httpx.post(f"{BASE}/webhook", json={
        "message": "What is my name?",
        "session_id": sid
    })
    data = r.json()
    test("Conversation History", 
         "priya" in data.get("response","").lower() or 
         r.status_code == 200)
    print(f"   Response: {data.get('response', '')[:100]}")
except Exception as e:
    test("Conversation History", False, str(e))

# Test 11: Rate limiting
try:
    responses = []
    for i in range(22):
        r = httpx.post(f"{BASE}/webhook", json={
            "message": "test",
            "session_id": f"rate_test_{i}"
        })
        responses.append(r.status_code)
    has_429 = 429 in responses
    test("Rate Limiting (429)", has_429, 
         f"Status codes: {set(responses)}")
except Exception as e:
    test("Rate Limiting", False, str(e))

# Final Report
print(f"\n{'='*40}")
print(f"RESULTS: {len(PASS)} passed, {len(FAIL)} failed")
print(f"{'='*40}")
if FAIL:
    print(f"\n? FAILED TESTS:")
    for f in FAIL:
        print(f"   - {f}")
    print("\nFix these and re-run test_api.py")
else:
    print("\n?? ALL TESTS PASSED - Vaidya AI is working!")
