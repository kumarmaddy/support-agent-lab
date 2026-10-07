# scripts/smoke_test.py
import json
import time
import requests

URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2:3b"

ticket = "Hi, my order #1042 hasn't arrived yet and it's been 10 days. Where is it?"

payload = {
    "model": MODEL,
    "stream": False,
    "format": "json",
    "messages": [
        {"role": "system",
         "content": 'Classify the support ticket. Reply ONLY with JSON: '
                    '{"category": "order_status|refund|return|account|other", '
                    '"priority": "low|medium|high"}'},
        {"role": "user", "content": ticket},
    ],
}

start = time.time()
resp = requests.post(URL, json=payload, timeout=600)
resp.raise_for_status()
elapsed = time.time() - start
data = resp.json()

text = data["message"]["content"]
print("Model output:", text)
try:
    json.loads(text)
    print("Valid JSON: yes")
except json.JSONDecodeError:
    print("Valid JSON: NO")

tokens = data.get("eval_count", 0)
gen_seconds = data.get("eval_duration", 0) / 1e9
print(f"Total seconds: {elapsed:.1f}")
if gen_seconds:
    print(f"Generation speed: {tokens / gen_seconds:.1f} tokens/sec")