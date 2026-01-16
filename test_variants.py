#!/usr/bin/env python3
"""
Test O-Dengi API with multiple variants
"""
import hmac
import hashlib
import json
import time
import subprocess

# Credentials
USER_SID = "5796540861"
USER_PASSWORD = "&NY&|BODP8TLF{7"

SANDBOX_SID = "4672496329"
SANDBOX_PASSWORD = "F7XFA4O5AljCS2W"

# API URLs to try
URLS = [
    "https://mw-api-test.dengi.kg/api",
    "https://mw-api-test.dengi.kg/api/",
    "https://mw-api.dengi.kg/api",
    "https://api.dengi.kg/api",
    "https://dengi.kg/api",
]

def generate_hash_v1(payload: dict, password: str) -> str:
    """HMAC-MD5 of JSON without hash field"""
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return hmac.new(password.encode(), json_string.encode(), hashlib.md5).hexdigest()

def generate_hash_v2(payload: dict, password: str) -> str:
    """HMAC-MD5 with sorted keys"""
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False, sort_keys=True)
    return hmac.new(password.encode(), json_string.encode(), hashlib.md5).hexdigest()

def test_request(url: str, payload: dict, desc: str):
    """Test a single request"""
    print(f"\n{'='*60}")
    print(f"TEST: {desc}")
    print(f"URL: {url}")
    print(f"{'='*60}")

    request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    print(f"Request (first 300 chars): {request_json[:300]}...")

    try:
        result = subprocess.run([
            "curl", "-s", "-m", "10",
            "-X", "POST", url,
            "-H", "Content-Type: application/json",
            "-d", request_json
        ], capture_output=True, text=True, timeout=15)

        response = result.stdout[:500] if result.stdout else "(empty)"
        print(f"Response: {response}")

        # Check if it's valid JSON
        if result.stdout and not result.stdout.startswith("<"):
            try:
                parsed = json.loads(result.stdout)
                print(f"✅ Valid JSON response!")
                return True
            except:
                pass
        return False
    except subprocess.TimeoutExpired:
        print("⏱️ Timeout")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

# Run tests
mktime = str(int(time.time()))

print("\n" + "="*70)
print("🧪 ТЕСТИРОВАНИЕ O-DENGI API - РАЗНЫЕ ВАРИАНТЫ")
print("="*70)

# Test 1: User credentials, format from documentation
print("\n\n📋 ВАРИАНТ 1: User SID + Стандартный формат")
for url in URLS[:2]:
    data = {
        "order_id": f"TEST-V1-{mktime}",
        "desc": "Test",
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
    payload["hash"] = generate_hash_v1(payload, USER_PASSWORD)
    if test_request(url, payload, f"User SID, URL: {url}"):
        break

# Test 2: Sandbox credentials
print("\n\n📋 ВАРИАНТ 2: Sandbox SID + Стандартный формат")
for url in URLS[:2]:
    data = {
        "order_id": f"TEST-V2-{mktime}",
        "desc": "Test",
        "amount": 10000,
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
    payload["hash"] = generate_hash_v1(payload, SANDBOX_PASSWORD)
    if test_request(url, payload, f"Sandbox SID, URL: {url}"):
        break

# Test 3: Flat structure (no "data" wrapper)
print("\n\n📋 ВАРИАНТ 3: Плоская структура без 'data' wrapper")
payload = {
    "cmd": "createInvoice",
    "version": 1005,
    "lang": "ru",
    "sid": SANDBOX_SID,
    "mktime": mktime,
    "order_id": f"TEST-V3-{mktime}",
    "desc": "Test",
    "amount": 10000,
    "currency": "KGS",
    "test": 1
}
payload["hash"] = generate_hash_v1(payload, SANDBOX_PASSWORD)
test_request(URLS[0], payload, "Flat structure")

# Test 4: Different version
print("\n\n📋 ВАРИАНТ 4: Version как string")
data = {
    "order_id": f"TEST-V4-{mktime}",
    "desc": "Test",
    "amount": 10000,
    "currency": "KGS",
    "test": 1
}
payload = {
    "cmd": "createInvoice",
    "version": "1005",  # String instead of int
    "lang": "ru",
    "sid": SANDBOX_SID,
    "mktime": mktime,
    "data": data,
}
payload["hash"] = generate_hash_v1(payload, SANDBOX_PASSWORD)
test_request(URLS[0], payload, "Version as string")

# Test 5: getOTP command (simpler test)
print("\n\n📋 ВАРИАНТ 5: getOTP команда (простой тест)")
payload = {
    "cmd": "getOTP",
    "version": 1005,
    "lang": "ru",
    "sid": SANDBOX_SID,
    "mktime": mktime,
    "data": {
        "phone": "996555123456"
    }
}
payload["hash"] = generate_hash_v1(payload, SANDBOX_PASSWORD)
test_request(URLS[0], payload, "getOTP command")

# Test 6: Amount in som not tiyin
print("\n\n📋 ВАРИАНТ 6: Amount в сомах (не тыйынах)")
data = {
    "order_id": f"TEST-V6-{mktime}",
    "desc": "Test",
    "amount": 100,  # 100 som, not 10000 tiyin
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
payload["hash"] = generate_hash_v1(payload, SANDBOX_PASSWORD)
test_request(URLS[0], payload, "Amount in som")

print("\n\n" + "="*70)
print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("="*70)
