#!/usr/bin/env python3
"""
Direct test of O-Dengi API with proper hash
"""
import hmac
import hashlib
import json
import time
import subprocess

# Credentials from user
SID = "5796540861"
PASSWORD = "&NY&|BODP8TLF{7"
API_URL = "https://mw-api-test.dengi.kg/api"

def generate_hash(payload: dict, password: str) -> str:
    """Generate HMAC-MD5 signature"""
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    print(f"JSON for hash: {json_string}")
    signature = hmac.new(
        password.encode('utf-8'),
        json_string.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    return signature

# Build request
mktime = str(int(time.time()))
data = {
    "order_id": f"TEST-{mktime}",
    "desc": "Test payment",
    "amount": 10000,  # 100 som in tiyin
    "currency": "KGS",
    "test": 1
}

payload = {
    "cmd": "createInvoice",
    "version": 1005,
    "lang": "ru",
    "sid": SID,
    "mktime": mktime,
    "data": data,
}

# Generate hash
payload["hash"] = generate_hash(payload, PASSWORD)

# Full request JSON
request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
print(f"\nFull request JSON:\n{request_json}")

# Test with curl
print(f"\n\nTesting with curl to {API_URL}...")
result = subprocess.run([
    "curl", "-s", "-v",
    "-X", "POST",
    API_URL,
    "-H", "Content-Type: application/json; charset=utf-8",
    "-d", request_json
], capture_output=True, text=True)

print(f"\nSTDOUT:\n{result.stdout}")
print(f"\nSTDERR:\n{result.stderr}")
