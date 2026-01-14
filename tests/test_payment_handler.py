"""
Tests for Payment Handlers

Covers:
- Telegram callback handlers (pay:, check_pay:, cancel_pay:)
- Webhook handler for payment callbacks
- Admin payment commands
- process_payment_success flow
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from aiogram.types import CallbackQuery, Message, User, Chat
from aiogram import Bot

from src.handlers.payment import (
    handle_pay_button,
    handle_check_payment,
    handle_cancel_payment,
    handle_payment_webhook,
    process_payment_success,
)
from src.services.payment import (
    PaymentStatus,
    PaymentResult,
    PaymentStatusResult,
)


# ============== Fixtures ==============

@pytest.fixture
def mock_bot():
    """Create mock Bot instance"""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


@pytest.fixture
def mock_user():
    """Create mock User"""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.first_name = "Test"
    user.username = "testuser"
    return user


@pytest.fixture
def mock_message():
    """Create mock Message"""
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock()
    message.answer_photo = AsyncMock()
    message.delete = AsyncMock()
    return message


@pytest.fixture
def mock_callback(mock_user, mock_message):
    """Create mock CallbackQuery"""
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = mock_user
    callback.message = mock_message
    callback.answer = AsyncMock()
    callback.data = "pay:TE-5001:500"
    return callback


# ============== handle_pay_button Tests ==============

class TestHandlePayButton:
    """Test payment button click handler"""

    @pytest.mark.asyncio
    async def test_pay_button_success(self, mock_callback, mock_bot):
        """Test successful payment invoice creation"""
        mock_callback.data = "pay:TE-5001:500"

        mock_result = PaymentResult(
            success=True,
            invoice_id="INV-12345",
            order_id="TLP-TE-5001-123",
            qr_data="https://pay.dengi.kg/qr/12345",
            qr_image_url="https://pay.dengi.kg/qr/12345.png",
            raw_response={"data": {"site_pay": "https://pay.dengi.kg/pay/12345"}},
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.config') as mock_config:
            mock_api.create_invoice = AsyncMock(return_value=mock_result)
            mock_config.database_url = None

            await handle_pay_button(mock_callback, mock_bot)

        # Verify callback was answered
        mock_callback.answer.assert_called_once()
        assert "Создаю счёт" in mock_callback.answer.call_args[0][0]

        # Verify photo was sent with QR
        mock_callback.message.answer_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_pay_button_invalid_format(self, mock_callback, mock_bot):
        """Test payment with invalid callback data format"""
        mock_callback.data = "pay:invalid"  # Missing amount

        await handle_pay_button(mock_callback, mock_bot)

        mock_callback.message.answer.assert_called_once()
        assert "неверный формат" in mock_callback.message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_pay_button_api_error(self, mock_callback, mock_bot):
        """Test payment when API returns error"""
        mock_callback.data = "pay:TE-5001:500"

        mock_result = PaymentResult(
            success=False,
            error="Service temporarily unavailable",
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.config') as mock_config:
            mock_api.create_invoice = AsyncMock(return_value=mock_result)
            mock_config.database_url = None

            await handle_pay_button(mock_callback, mock_bot)

        mock_callback.message.answer.assert_called()
        call_text = mock_callback.message.answer.call_args[0][0]
        assert "Ошибка" in call_text
        assert "unavailable" in call_text

    @pytest.mark.asyncio
    async def test_pay_button_saves_to_db(self, mock_callback, mock_bot):
        """Test that payment is saved to database when configured"""
        mock_callback.data = "pay:TE-5001:500"

        mock_result = PaymentResult(
            success=True,
            invoice_id="INV-12345",
            order_id="TLP-TE-5001-123",
            qr_data="https://pay.dengi.kg/qr/12345",
            raw_response={"data": {"site_pay": "https://pay.dengi.kg/pay/12345"}},
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.config') as mock_config, \
             patch('src.handlers.payment.db_service') as mock_db:
            mock_api.create_invoice = AsyncMock(return_value=mock_result)
            mock_config.database_url = "postgresql://test"
            mock_db.create_payment = AsyncMock()

            await handle_pay_button(mock_callback, mock_bot)

        mock_db.create_payment.assert_called_once()
        call_kwargs = mock_db.create_payment.call_args[1]
        assert call_kwargs["client_code"] == "TE-5001"
        assert call_kwargs["amount_som"] == 500.0

    @pytest.mark.asyncio
    async def test_pay_button_qr_image_fallback(self, mock_callback, mock_bot):
        """Test fallback when QR image fails to load"""
        from aiogram.exceptions import TelegramBadRequest

        mock_callback.data = "pay:TE-5001:500"
        mock_callback.message.answer_photo.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request"
        )

        mock_result = PaymentResult(
            success=True,
            invoice_id="INV-12345",
            qr_data="https://pay.dengi.kg/qr/12345",
            raw_response={"data": {"site_pay": "https://pay.dengi.kg/pay/12345"}},
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.config') as mock_config:
            mock_api.create_invoice = AsyncMock(return_value=mock_result)
            mock_config.database_url = None

            await handle_pay_button(mock_callback, mock_bot)

        # Should fall back to text message with link
        mock_callback.message.answer.assert_called()


# ============== handle_check_payment Tests ==============

class TestHandleCheckPayment:
    """Test payment status check handler"""

    @pytest.mark.asyncio
    async def test_check_payment_paid(self, mock_callback, mock_bot):
        """Test checking status of paid invoice"""
        mock_callback.data = "check_pay:INV-12345"

        mock_result = PaymentStatusResult(
            success=True,
            status=PaymentStatus.PAID,
            order_id="TLP-TE-5001-123",
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.process_payment_success') as mock_process:
            mock_api.check_status = AsyncMock(return_value=mock_result)
            mock_process.return_value = True

            await handle_check_payment(mock_callback, mock_bot)

        mock_callback.answer.assert_called_once()
        assert "Проверяю статус" in mock_callback.answer.call_args[0][0]

        # Should process payment success
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_payment_pending(self, mock_callback, mock_bot):
        """Test checking status of pending invoice"""
        mock_callback.data = "check_pay:INV-12345"

        mock_result = PaymentStatusResult(
            success=True,
            status=PaymentStatus.PENDING,
            status_str="Ожидает оплаты",
        )

        with patch('src.handlers.payment.odengi_api') as mock_api:
            mock_api.check_status = AsyncMock(return_value=mock_result)

            await handle_check_payment(mock_callback, mock_bot)

        mock_callback.message.answer.assert_called()
        call_text = mock_callback.message.answer.call_args[0][0]
        assert "Статус платежа" in call_text

    @pytest.mark.asyncio
    async def test_check_payment_error(self, mock_callback, mock_bot):
        """Test handling API error when checking status"""
        mock_callback.data = "check_pay:INV-12345"

        mock_result = PaymentStatusResult(
            success=False,
            error="Invoice not found",
        )

        with patch('src.handlers.payment.odengi_api') as mock_api:
            mock_api.check_status = AsyncMock(return_value=mock_result)

            await handle_check_payment(mock_callback, mock_bot)

        mock_callback.message.answer.assert_called()
        call_text = mock_callback.message.answer.call_args[0][0]
        assert "Ошибка" in call_text


# ============== handle_cancel_payment Tests ==============

class TestHandleCancelPayment:
    """Test payment cancellation handler"""

    @pytest.mark.asyncio
    async def test_cancel_payment_success(self, mock_callback, mock_bot):
        """Test successful invoice cancellation"""
        mock_callback.data = "cancel_pay:INV-12345"

        with patch('src.handlers.payment.odengi_api') as mock_api:
            mock_api.cancel_invoice = AsyncMock(return_value=True)

            await handle_cancel_payment(mock_callback)

        mock_callback.answer.assert_called_once()
        mock_callback.message.answer.assert_called_once()
        assert "отменён" in mock_callback.message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_cancel_payment_failure(self, mock_callback, mock_bot):
        """Test cancellation failure (already paid)"""
        mock_callback.data = "cancel_pay:INV-12345"

        with patch('src.handlers.payment.odengi_api') as mock_api:
            mock_api.cancel_invoice = AsyncMock(return_value=False)

            await handle_cancel_payment(mock_callback)

        mock_callback.message.answer.assert_called()
        call_text = mock_callback.message.answer.call_args[0][0]
        assert "Не удалось отменить" in call_text


# ============== process_payment_success Tests ==============

class TestProcessPaymentSuccess:
    """Test payment success processing flow"""

    @pytest.mark.asyncio
    async def test_process_payment_full_flow(self, mock_bot):
        """Test complete payment success flow"""
        mock_payment = {
            "payment_id": "TLP-TE-5001-123",
            "client_code": "TE-5001",
            "chat_id": 123456789,
            "message_id": 100,
            "amount_som": "500.00",
            "status": "PENDING",
        }

        mock_client = MagicMock()
        mock_client.full_name = "Айбек Асанов"

        with patch('src.handlers.payment.db_service') as mock_db, \
             patch('src.handlers.payment.send_admin_payment_notification') as mock_notify, \
             patch('src.handlers.payment.config') as mock_config, \
             patch('src.services.sheets.sheets_service') as mock_sheets:
            mock_db.get_payment_by_id = AsyncMock(return_value=mock_payment)
            mock_db.update_payment_status = AsyncMock()
            mock_config.admin_chat_ids = [111, 222]
            mock_sheets.get_client_by_code = AsyncMock(return_value=mock_client)
            mock_notify.return_value = None

            result = await process_payment_success(mock_bot, "TLP-TE-5001-123")

        assert result is True

        # Verify payment status was updated
        mock_db.update_payment_status.assert_called_once()
        call_kwargs = mock_db.update_payment_status.call_args[1]
        assert call_kwargs["payment_id"] == "TLP-TE-5001-123"
        assert call_kwargs["status"] == "PAID"

        # Verify QR message was deleted
        mock_bot.delete_message.assert_called_once_with(
            chat_id=123456789, message_id=100
        )

        # Verify success message was sent to user
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == 123456789
        assert "Оплата прошла успешно" in call_kwargs["text"]

        # Verify admin notification was sent
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_payment_not_found(self, mock_bot):
        """Test processing when payment not found"""
        with patch('src.handlers.payment.db_service') as mock_db:
            mock_db.get_payment_by_id = AsyncMock(return_value=None)

            result = await process_payment_success(mock_bot, "TLP-INVALID")

        assert result is False
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_payment_already_paid(self, mock_bot):
        """Test processing already paid payment (idempotent)"""
        mock_payment = {
            "payment_id": "TLP-TE-5001-123",
            "status": "PAID",  # Already paid
        }

        with patch('src.handlers.payment.db_service') as mock_db:
            mock_db.get_payment_by_id = AsyncMock(return_value=mock_payment)
            mock_db.update_payment_status = AsyncMock()

            result = await process_payment_success(mock_bot, "TLP-TE-5001-123")

        assert result is True
        # Should not update status again
        mock_db.update_payment_status.assert_not_called()


# ============== handle_payment_webhook Tests ==============

class TestHandlePaymentWebhook:
    """Test webhook handler for payment callbacks"""

    @pytest.mark.asyncio
    async def test_webhook_paid_status(self, mock_bot):
        """Test webhook with paid status"""
        webhook_data = {
            "invoice_id": "INV-12345",
            "order_id": "TLP-TE-5001-123",
            "status_pay": 1,
            "amount": 50000,
            "trans": "TRANS-001",
        }

        with patch('src.handlers.payment.payment_service') as mock_service, \
             patch('src.handlers.payment.process_payment_success') as mock_process:
            mock_service.parse_callback.return_value = {
                "order_id": "TLP-TE-5001-123",
                "status": PaymentStatus.PAID,
            }
            mock_process.return_value = True

            response = await handle_payment_webhook(webhook_data, mock_bot)

        assert response["status"] == "ok"
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_pending_status(self, mock_bot):
        """Test webhook with pending status (ignored)"""
        webhook_data = {
            "invoice_id": "INV-12345",
            "status_pay": 0,
        }

        with patch('src.handlers.payment.payment_service') as mock_service:
            mock_service.parse_callback.return_value = {
                "order_id": "TLP-TE-5001-123",
                "status": PaymentStatus.PENDING,
            }

            response = await handle_payment_webhook(webhook_data, mock_bot)

        assert response["status"] == "ok"
        assert "ignored" in response.get("message", "")

    @pytest.mark.asyncio
    async def test_webhook_invalid_data(self, mock_bot):
        """Test webhook with invalid/tampered data"""
        webhook_data = {
            "invalid": "data",
        }

        with patch('src.handlers.payment.payment_service') as mock_service:
            mock_service.parse_callback.return_value = None

            response = await handle_payment_webhook(webhook_data, mock_bot)

        assert response["status"] == "error"
        assert "Invalid" in response["message"]

    @pytest.mark.asyncio
    async def test_webhook_missing_order_id(self, mock_bot):
        """Test webhook with missing order_id"""
        webhook_data = {
            "status_pay": 1,
        }

        with patch('src.handlers.payment.payment_service') as mock_service:
            mock_service.parse_callback.return_value = {
                "order_id": None,
                "status": PaymentStatus.PAID,
            }

            response = await handle_payment_webhook(webhook_data, mock_bot)

        assert response["status"] == "error"
        assert "payment_id" in response["message"]

    @pytest.mark.asyncio
    async def test_webhook_exception_handling(self, mock_bot):
        """Test webhook exception handling"""
        webhook_data = {"status_pay": 1}

        with patch('src.handlers.payment.payment_service') as mock_service:
            mock_service.parse_callback.side_effect = Exception("Unexpected error")

            response = await handle_payment_webhook(webhook_data, mock_bot)

        assert response["status"] == "error"


# ============== Integration-like Tests ==============

class TestPaymentIntegration:
    """Integration-like tests for payment flow"""

    @pytest.mark.asyncio
    async def test_full_payment_flow(self, mock_callback, mock_bot):
        """Test complete payment flow: create -> check -> success"""
        # Step 1: Create invoice
        mock_callback.data = "pay:TE-5001:500"

        create_result = PaymentResult(
            success=True,
            invoice_id="INV-12345",
            order_id="TLP-TE-5001-123",
            qr_data="https://pay.dengi.kg/qr/12345",
            raw_response={"data": {"site_pay": "https://pay.dengi.kg/pay/12345"}},
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.config') as mock_config:
            mock_api.create_invoice = AsyncMock(return_value=create_result)
            mock_config.database_url = None

            await handle_pay_button(mock_callback, mock_bot)

        # Step 2: Check status (simulating user clicking check button)
        mock_callback.data = "check_pay:INV-12345"
        mock_callback.answer.reset_mock()
        mock_callback.message.answer.reset_mock()

        check_result = PaymentStatusResult(
            success=True,
            status=PaymentStatus.PAID,
            order_id="TLP-TE-5001-123",
        )

        mock_payment = {
            "payment_id": "TLP-TE-5001-123",
            "client_code": "TE-5001",
            "chat_id": 123456789,
            "message_id": None,
            "amount_som": "500.00",
            "status": "PENDING",
        }

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.db_service') as mock_db, \
             patch('src.handlers.payment.config') as mock_config, \
             patch('src.handlers.payment.send_admin_payment_notification') as mock_notify, \
             patch('src.services.sheets.sheets_service') as mock_sheets:
            mock_api.check_status = AsyncMock(return_value=check_result)
            mock_db.get_payment_by_id = AsyncMock(return_value=mock_payment)
            mock_db.update_payment_status = AsyncMock()
            mock_config.admin_chat_ids = [111]
            mock_sheets.get_client_by_code = AsyncMock(return_value=None)
            mock_notify.return_value = None

            await handle_check_payment(mock_callback, mock_bot)

        # Verify payment was processed
        mock_db.update_payment_status.assert_called()

    @pytest.mark.asyncio
    async def test_m_code_client_payment(self, mock_callback, mock_bot):
        """Test payment for M-code client (Cyrillic format)"""
        mock_callback.data = "pay:M-325:1500"

        mock_result = PaymentResult(
            success=True,
            invoice_id="INV-M325",
            qr_data="https://pay.dengi.kg/qr/m325",
            raw_response={"data": {"site_pay": "https://pay.dengi.kg/pay/m325"}},
        )

        with patch('src.handlers.payment.odengi_api') as mock_api, \
             patch('src.handlers.payment.config') as mock_config:
            mock_api.create_invoice = AsyncMock(return_value=mock_result)
            mock_config.database_url = None

            await handle_pay_button(mock_callback, mock_bot)

        # Verify invoice was created
        mock_api.create_invoice.assert_called_once()
        call_args = mock_api.create_invoice.call_args[0][0]
        assert call_args.client_code == "M-325"
        assert call_args.amount_som == 1500.0
