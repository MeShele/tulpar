#!/usr/bin/env python3
"""
Test following redirects properly
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

# Build request
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

print("="*70)
print("Testing with redirect following and verbose output")
print("="*70)

# Test 1: Follow redirects with verbose
print("\n\n📋 TEST 1: Follow redirects (-L)")
result = subprocess.run([
    "curl", "-v", "-L", "-k",
    "-X", "POST",
    "https://mw-api-test.dengi.kg/api",
    "-H", "Content-Type: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=30)
print(f"STDOUT:\n{result.stdout}")
print(f"\nSTDERR (last 2000 chars):\n{result.stderr[-2000:]}")

# Test 2: Direct to internal URL with HTTPS
print("\n\n📋 TEST 2: Direct to internal URL (HTTPS)")
result = subprocess.run([
    "curl", "-v", "-k",
    "-X", "POST",
    "https://test4-mwallet.dengi.kg:8080/api",
    "-H", "Content-Type: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"STDOUT:\n{result.stdout[:500]}")
print(f"\nSTDERR (last 1000 chars):\n{result.stderr[-1000:]}")

# Test 3: Direct to internal URL with HTTP
print("\n\n📋 TEST 3: Direct to internal URL (HTTP)")
result = subprocess.run([
    "curl", "-v",
    "-X", "POST",
    "http://test4-mwallet.dengi.kg:8080/api",
    "-H", "Content-Type: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=15)
print(f"STDOUT:\n{result.stdout[:500]}")
print(f"\nSTDERR (last 1000 chars):\n{result.stderr[-1000:]}")

# Test 4: With --post301 and --post302 to preserve POST method
print("\n\n📋 TEST 4: Force POST on redirect")
result = subprocess.run([
    "curl", "-v", "-L", "-k",
    "--post301", "--post302", "--post303",
    "-X", "POST",
    "https://mw-api-test.dengi.kg/api",
    "-H", "Content-Type: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=30)
print(f"STDOUT:\n{result.stdout}")
print(f"\nSTDERR (last 2000 chars):\n{result.stderr[-2000:]}")
