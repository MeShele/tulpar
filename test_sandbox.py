#!/usr/bin/env python3
"""
Test O-Dengi Sandbox API with documented credentials
"""
import hmac
import hashlib
import json
import time
import subprocess

# SANDBOX credentials from documentation (screenshot 4)
SANDBOX_SID = "4672496329"
SANDBOX_PASSWORD = "F7XFA4O5AljCS2W"
API_URL = "https://mw-api-test.dengi.kg/api"

def generate_hash(payload: dict, password: str) -> str:
    """Generate HMAC-MD5 signature"""
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    signature = hmac.new(
        password.encode('utf-8'),
        json_string.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    return signature

# Build request
mktime = str(int(time.time()))
data = {
    "order_id": f"TEST-SANDBOX-{mktime}",
    "desc": "Тестовый платёж Tulpar Express",
    "amount": 10000,  # 100 som in tiyin
    "currency": "KGS",
    "test": 1
}

payload = {
    "cmd": "createInvoice",
    "version": 1005,
    "lang": "ru",
    "sid": SANDBOX_SID,
    "mktime": mktime,
    "data": data,
}

# Generate hash
payload["hash"] = generate_hash(payload, SANDBOX_PASSWORD)

# Full request JSON
request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
print(f"Request: {request_json[:200]}...")
print(f"\nTesting SANDBOX with curl (following redirects)...")

# Test with curl following redirects
result = subprocess.run([
    "curl", "-s", "-L",  # -L follows redirects
    "-X", "POST",
    API_URL,
    "-H", "Content-Type: application/json; charset=utf-8",
    "-d", request_json
], capture_output=True, text=True, timeout=30)

print(f"\nResponse:\n{result.stdout}")
if result.stderr:
    print(f"\nErrors:\n{result.stderr}")
