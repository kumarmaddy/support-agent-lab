# scripts/smoke_test_v2.py
# Purpose: check that the local model (a) returns a VALID category and (b) the CORRECT one,
# and measure speed. Uses a JSON schema so the model can only pick allowed values.
import json
import time
import requests

URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"

CATEGORIES = ["order_status", "refund", "return", "account", "other"]
PRIORITIES = ["low", "medium", "high"]

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "priority": {"type": "string", "enum": PRIORITIES},
    },
    "required": ["category", "priority"],
}

SYSTEM = (
    "You classify customer support tickets for an online retailer. "
    "Choose exactly one category and one priority for the ticket. "
    "order_status = where is my order; refund = wants money back; "
    "return = wants to send an item back; account = login/profile/address issues; "
    "other = anything else."
)

# (ticket text, expected category) - ground truth written by you, not by the model
TESTS = [
    ("Hi, my order #1042 hasn't arrived and it's been 10 days. Where is it?", "order_status"),
    ("I was charged twice for order #2201. Please refund the duplicate payment.", "refund"),
    ("The jacket is too small. How do I send it back for a different size?", "return"),
    ("I can't log in, it says my password is wrong and the reset email never comes.", "account"),
    ("Do you sell gift cards?", "other"),
]


def classify(ticket: str):
    payload = {
        "model": MODEL,
        "stream": False,
        "format": SCHEMA,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": ticket},
        ],
    }
    start = time.time()
    resp = requests.post(URL, json=payload, timeout=600)
    resp.raise_for_status()
    elapsed = time.time() - start
    data = resp.json()
    out = json.loads(data["message"]["content"])
    gen = data.get("eval_duration", 0) / 1e9
    tps = data.get("eval_count", 0) / gen if gen else 0.0
    return out, elapsed, tps


def main():
    correct = valid = 0
    for ticket, expected in TESTS:
        try:
            out, secs, tps = classify(ticket)
        except Exception as exc:  # network, JSON, or schema-support errors
            print(f"ERROR on ticket: {ticket[:40]}... -> {exc}")
            continue
        is_valid = out.get("category") in CATEGORIES and out.get("priority") in PRIORITIES
        is_correct = out.get("category") == expected
        valid += is_valid
        correct += is_correct
        print(f"{'OK ' if is_correct else 'BAD'} expected={expected:<12} got={out} "
              f"({secs:.1f}s, {tps:.1f} tok/s)")
    print(f"\nValid outputs: {valid}/{len(TESTS)}  Correct category: {correct}/{len(TESTS)}")


if __name__ == "__main__":
    main()