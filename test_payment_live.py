#!/usr/bin/env python3
"""
Create a LIVE test payment for manual testing
"""
import hmac
import hashlib
import json
import time
import subprocess

SID = "5796540861"
PASSWORD = "&NY&|BODP8TLF{7"
API_URL = "https://api.dengi.o.kg/api/json/json.php"

def generate_hash(payload: dict, password: str) -> str:
    json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return hmac.new(password.encode(), json_string.encode(), hashlib.md5).hexdigest()

def create_invoice(amount_som: int, description: str):
    mktime = str(int(time.time()))
    order_id = f"TULPAR-TEST-{mktime}"

    data = {
        "order_id": order_id,
        "desc": description,
        "amount": amount_som * 100,  # Convert to tiyin
        "currency": "KGS",
        "test": 1  # Test mode
    }

    payload = {
        "cmd": "createInvoice",
        "version": 1005,
        "lang": "ru",
        "sid": SID,
        "mktime": mktime,
        "data": data,
    }
    payload["hash"] = generate_hash(payload, PASSWORD)

    request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

    result = subprocess.run([
        "curl", "-s", "-L",
        "-X", "POST", API_URL,
        "-H", "Content-Type: application/json",
        "-d", request_json
    ], capture_output=True, text=True, timeout=30)

    return json.loads(result.stdout), order_id

def check_status(order_id: str):
    mktime = str(int(time.time()))

    payload = {
        "cmd": "statusPayment",
        "version": 1005,
        "lang": "ru",
        "sid": SID,
        "mktime": mktime,
        "data": {"order_id": order_id}
    }
    payload["hash"] = generate_hash(payload, PASSWORD)

    request_json = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

    result = subprocess.run([
        "curl", "-s", "-L",
        "-X", "POST", API_URL,
        "-H", "Content-Type: application/json",
        "-d", request_json
    ], capture_output=True, text=True, timeout=30)

    return json.loads(result.stdout)

# Create test payment
print("=" * 70)
print("🧪 СОЗДАНИЕ ТЕСТОВОГО ПЛАТЕЖА")
print("=" * 70)

response, order_id = create_invoice(10, "Тест оплаты Tulpar Express - 10 сом")
data = response.get("data", {})

if "error" in data:
    print(f"\n❌ Ошибка: {data.get('desc')}")
else:
    invoice_id = data.get("invoice_id")

    print(f"""
✅ ПЛАТЁЖ СОЗДАН!

📋 Данные платежа:
   Order ID:    {order_id}
   Invoice ID:  {invoice_id}
   Сумма:       10 сом
   Режим:       ТЕСТОВЫЙ (test: 1)

🔗 ССЫЛКИ ДЛЯ ОПЛАТЫ:

   1️⃣  QR-код (для сканирования):
       {data.get('qr', 'N/A')}

   2️⃣  Веб-страница оплаты:
       {data.get('site_pay', 'N/A')}

   3️⃣  PayLink (универсальная ссылка):
       {data.get('paylink_url', 'N/A')}

   4️⃣  Ссылка для приложения O!Dengi:
       {data.get('link_app', 'N/A')}

📱 КАК ТЕСТИРОВАТЬ:
   1. Открой ссылку site_pay или paylink_url в браузере
   2. Или отсканируй QR-код приложением O!Dengi
   3. Попробуй оплатить (в тестовом режиме деньги не спишутся)

""")

    # Check current status
    print("=" * 70)
    print("📊 ТЕКУЩИЙ СТАТУС ПЛАТЕЖА")
    print("=" * 70)

    status_resp = check_status(order_id)
    status_data = status_resp.get("data", {})

    print(f"""
   Status Pay:  {status_data.get('status_pay', 'N/A')}
   Status Str:  {status_data.get('status_str', 'N/A')}
   Amount:      {status_data.get('amount', 'N/A')}

   Raw Response: {json.dumps(status_data, ensure_ascii=False, indent=2)[:500]}
""")

print("=" * 70)
