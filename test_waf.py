#!/usr/bin/env python3
"""
Test bypassing WAF with different headers
"""
import hmac
import hashlib
import json
import time
import subprocess

SANDBOX_SID = "4672496329"
SANDBOX_PASSWORD = "F7XFA4O5AljCS2W"

USER_SID = "5796540861"
USER_PASSWORD = "&NY&|BODP8TLF{7"

def generate_hash(payload: dict, password: str) -> str:
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return hmac.new(password.encode(), json_string.encode(), hashlib.md5).hexdigest()

mktime = str(int(time.time()))

# Build request with USER credentials
data = {
    "order_id": f"TEST-{mktime}",
    "desc": "Тестовый платёж",
    "amount": 10000,
    "currency": "KGS",
    "test": 1
}
payload = {
    "cmd": "createInvoice",
    "version": 1005,
    "lang": "ru",
    "sid": USER_SID,
    "mktime": mktime,
    "data": data,
}
payload["hash"] = generate_hash(payload, USER_PASSWORD)
request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

# Build request with SANDBOX credentials
payload_sb = {
    "cmd": "createInvoice",
    "version": 1005,
    "lang": "ru",
    "sid": SANDBOX_SID,
    "mktime": mktime,
    "data": data,
}
payload_sb["hash"] = generate_hash(payload_sb, SANDBOX_PASSWORD)
request_json_sb = json.dumps(payload_sb, separators=(',', ':'), ensure_ascii=False)

base_url = "https://test4-mwallet.dengi.kg:8080"

print("="*70)
print("Testing direct API with different headers/paths")
print("="*70)

# Test 1: Without trailing slash
print("\n\n📋 TEST 1: Without trailing slash, User SID")
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api",
    "-H", "Content-Type: application/json",
    "-H", "Accept: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

# Test 2: With trailing slash
print("\n\n📋 TEST 2: With trailing slash, User SID")
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api/",
    "-H", "Content-Type: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

# Test 3: Sandbox credentials
print("\n\n📋 TEST 3: Sandbox SID")
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api",
    "-H", "Content-Type: application/json",
    "-d", request_json_sb
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

# Test 4: With Origin header (like from sandbox.dengi.kg)
print("\n\n📋 TEST 4: With Origin header")
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api",
    "-H", "Content-Type: application/json",
    "-H", "Origin: https://sandbox.dengi.kg",
    "-H", "Referer: https://sandbox.dengi.kg/",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

# Test 5: Browser User-Agent
print("\n\n📋 TEST 5: Browser User-Agent")
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api",
    "-H", "Content-Type: application/json",
    "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "-H", "Origin: https://sandbox.dengi.kg",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

# Test 6: With X-Forwarded headers
print("\n\n📋 TEST 6: With X-Forwarded headers")
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api",
    "-H", "Content-Type: application/json",
    "-H", "X-Forwarded-For: 194.152.37.1",
    "-H", "X-Forwarded-Proto: https",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

# Test 7: Minimal simple request
print("\n\n📋 TEST 7: Minimal request - just status check")
simple_payload = {
    "cmd": "statusPayment",
    "version": 1005,
    "lang": "ru",
    "sid": USER_SID,
    "mktime": mktime,
    "data": {"order_id": "TEST-123"}
}
simple_payload["hash"] = generate_hash(simple_payload, USER_PASSWORD)
simple_json = json.dumps(simple_payload, separators=(',', ':'), ensure_ascii=False)
result = subprocess.run([
    "curl", "-s", "-k",
    "-X", "POST",
    f"{base_url}/api",
    "-H", "Content-Type: application/json",
    "-d", simple_json
], capture_output=True, text=True, timeout=15)
print(f"Response: {result.stdout[:600]}")

print("\n\n" + "="*70)
print("DONE")
print("="*70)
