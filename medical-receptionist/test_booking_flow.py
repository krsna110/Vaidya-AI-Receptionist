import os
import uuid
import httpx

BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://127.0.0.1:8123")
SESSION_ID = f"booking-regression-{uuid.uuid4().hex[:8]}"


def post_message(message: str) -> dict:
    response = httpx.post(
        f"{BASE_URL}/webhook",
        json={"message": message, "session_id": SESSION_ID},
        timeout=30,
    )
    return {
        "status_code": response.status_code,
        "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else {"raw": response.text},
    }


def assert_ok(step: str, payload: dict) -> None:
    if payload["status_code"] != 200:
        raise AssertionError(f"{step} failed with status {payload['status_code']}: {payload['body']}")


def main() -> None:
    print(f"Running booking regression on {BASE_URL} (session={SESSION_ID})")

    step1 = post_message("i want to book a appointment")
    assert_ok("step1 booking intent", step1)
    print("step1:", step1["body"].get("response"))

    step2 = post_message("my name is krishna")
    assert_ok("step2 provide name", step2)
    print("step2:", step2["body"].get("response"))

    step3 = post_message("i want to book a appointment")
    assert_ok("step3 continue booking", step3)
    response3 = (step3["body"].get("response") or "").lower()
    print("step3:", step3["body"].get("response"))

    if "may i have your name" in response3:
        raise AssertionError("Regression detected: bot asked for name again after it was already provided.")

    print("PASS: booking flow preserved collected name and moved forward.")


if __name__ == "__main__":
    main()
