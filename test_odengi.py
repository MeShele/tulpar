#!/usr/bin/env python3
"""
Test O-Dengi Payment API Integration
"""
import asyncio
import sys
sys.path.insert(0, '/Users/mac/Desktop/tulpar')

from src.services.payment import odengi_api, PaymentRequest, PaymentStatus


async def test_odengi():
    print("=" * 60)
    print("🧪 Тестирование O-Dengi API")
    print("=" * 60)

    # Check configuration
    print("\n📋 Конфигурация:")
    print(f"   API URL: {odengi_api.api_url}")
    print(f"   SID: {odengi_api.sid}")
    print(f"   Version: {odengi_api.api_version}")
    print(f"   Test Mode: {odengi_api.test_mode}")
    print(f"   Configured: {odengi_api.is_configured()}")

    if not odengi_api.is_configured():
        print("\n❌ API не настроен! Проверьте .env файл")
        return

    # Test 1: Create Invoice
    print("\n" + "=" * 60)
    print("📝 Тест 1: Создание счёта (createInvoice)")
    print("=" * 60)

    request = PaymentRequest(
        order_id="TEST-001-" + str(int(asyncio.get_event_loop().time())),
        amount_som=100.0,  # 100 сом
        description="Тестовый платёж Tulpar Express",
        client_code="TEST",
    )

    print(f"\n   Order ID: {request.order_id}")
    print(f"   Amount: {request.amount_som} сом")
    print(f"   Description: {request.description}")

    result = await odengi_api.create_invoice(request)

    print(f"\n   ✅ Success: {result.success}")

    if result.success:
        print(f"   📄 Invoice ID: {result.invoice_id}")
        print(f"   🔗 QR Data: {result.qr_data}")
        print(f"   🖼️  QR Image: {result.qr_image_url}")

        # Test 2: Check Status
        print("\n" + "=" * 60)
        print("🔍 Тест 2: Проверка статуса (statusPayment)")
        print("=" * 60)

        status_result = await odengi_api.check_status(order_id=request.order_id)

        print(f"\n   ✅ Success: {status_result.success}")
        if status_result.success:
            print(f"   📊 Status: {status_result.status} ({status_result.status_str})")
            print(f"   💰 Amount: {status_result.amount}")
        else:
            print(f"   ❌ Error: {status_result.error}")
    else:
        print(f"   ❌ Error: {result.error}")
        print(f"   📦 Raw Response: {result.raw_response}")

    print("\n" + "=" * 60)
    print("✅ Тестирование завершено!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_odengi())
