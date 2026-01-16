#!/usr/bin/env python3
"""
Test OLD O-Dengi API (api.dengi.o.kg) - IT WORKS!
"""
import hmac
import hashlib
import json
import time
import subprocess

USER_SID = "5796540861"
USER_PASSWORD = "&NY&|BODP8TLF{7"

OLD_API_URL = "https://api.dengi.o.kg/api/json/json.php"

def generate_hash(payload: dict, password: str) -> str:
    """Generate HMAC-MD5 signature"""
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    print(f"JSON for hash:\n{json_string}\n")
    signature = hmac.new(
        password.encode('utf-8'),
        json_string.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    print(f"Generated hash: {signature}")
    return signature

mktime = str(int(time.time()))

print("="*70)
print("🧪 TESTING OLD API: api.dengi.o.kg")
print("="*70)

# Test createInvoice
print("\n\n📋 TEST: createInvoice")
data = {
    "order_id": f"TULPAR-{mktime}",
    "desc": "Оплата доставки Tulpar Express",
    "amount": 10000,  # 100 som in tiyin
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

# Generate hash (without the hash field itself)
payload["hash"] = generate_hash(payload, USER_PASSWORD)

request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
print(f"\nFull request:\n{request_json}\n")

result = subprocess.run([
    "curl", "-s", "-L",
    "-X", "POST",
    OLD_API_URL,
    "-H", "Content-Type: application/json",
    "-d", request_json
], capture_output=True, text=True, timeout=30)

print(f"\n✅ RESPONSE:\n{result.stdout}")

# Try to parse response
try:
    resp = json.loads(result.stdout)
    if "error" in resp.get("data", {}):
        print(f"\n❌ Error: {resp['data'].get('desc', 'Unknown error')}")
    else:
        print(f"\n✅ SUCCESS! Response data: {resp}")
except Exception as e:
    print(f"\n❌ Parse error: {e}")

print("\n" + "="*70)
