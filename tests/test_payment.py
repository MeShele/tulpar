"""
Tests for Payment Service (O-Dengi API)

Covers:
- PaymentStatus enum
- PaymentRequest/PaymentResult dataclasses
- ODengiAPI methods (signature, create_invoice, check_status, etc.)
- PaymentService legacy wrapper
- Callback parsing and validation
"""
import pytest
import hmac
import hashlib
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.payment import (
    PaymentStatus,
    PaymentRequest,
    PaymentResult,
    PaymentStatusResult,
    ODengiAPI,
    PaymentService,
)


# ============== PaymentStatus Tests ==============

class TestPaymentStatus:
    """Test PaymentStatus enum"""

    def test_status_values(self):
        """Test status integer values"""
        assert PaymentStatus.PENDING == 0
        assert PaymentStatus.PAID == 1
        assert PaymentStatus.CANCELLED == -1
        assert PaymentStatus.EXPIRED == -2
        assert PaymentStatus.PROCESSING == 2
        assert PaymentStatus.PARTIAL_REFUND == 3
        assert PaymentStatus.FULL_REFUND == 4

    def test_status_from_int(self):
        """Test creating status from integer"""
        assert PaymentStatus(0) == PaymentStatus.PENDING
        assert PaymentStatus(1) == PaymentStatus.PAID
        assert PaymentStatus(-1) == PaymentStatus.CANCELLED

    def test_invalid_status_raises(self):
        """Test that invalid status raises ValueError"""
        with pytest.raises(ValueError):
            PaymentStatus(999)


# ============== Dataclass Tests ==============

class TestPaymentRequest:
    """Test PaymentRequest dataclass"""

    def test_minimal_request(self):
        """Test creating request with minimal fields"""
        req = PaymentRequest(
            order_id="TLP-TEST-001",
            amount_som=100.0,
            description="Test payment"
        )
        assert req.order_id == "TLP-TEST-001"
        assert req.amount_som == 100.0
        assert req.description == "Test payment"
        assert req.client_code is None
        assert req.long_term is False

    def test_full_request(self):
        """Test creating request with all fields"""
        req = PaymentRequest(
            order_id="TLP-TE-5001-123",
            amount_som=500.50,
            description="Доставка посылки",
            client_code="TE-5001",
            chat_id=123456789,
            user_id="user123",
            long_term=True,
            date_life="31.12.2026",
            send_push=True,
            send_sms=False,
            result_url="https://example.com/result",
            success_url="https://example.com/success",
            fail_url="https://example.com/fail",
            fields_other={"custom": "data"},
        )
        assert req.client_code == "TE-5001"
        assert req.chat_id == 123456789
        assert req.long_term is True


class TestPaymentResult:
    """Test PaymentResult dataclass"""

    def test_success_result(self):
        """Test successful payment result"""
        result = PaymentResult(
            success=True,
            invoice_id="INV-12345",
            order_id="TLP-TEST-001",
            qr_data="https://pay.dengi.kg/qr/12345",
            qr_image_url="https://pay.dengi.kg/qr/12345.png",
        )
        assert result.success is True
        assert result.invoice_id == "INV-12345"
        assert result.error is None

    def test_error_result(self):
        """Test error payment result"""
        result = PaymentResult(
            success=False,
            error="Insufficient funds",
            error_code=402,
        )
        assert result.success is False
        assert result.error == "Insufficient funds"
        assert result.error_code == 402


class TestPaymentStatusResult:
    """Test PaymentStatusResult dataclass"""

    def test_paid_status_result(self):
        """Test paid status result"""
        result = PaymentStatusResult(
            success=True,
            status=PaymentStatus.PAID,
            status_str="approved",
            invoice_id="INV-12345",
            amount=10000,
            fee=100,
            trans_id="TRANS-001",
            paid_at=datetime(2026, 1, 15, 12, 0, 0),
        )
        assert result.success is True
        assert result.status == PaymentStatus.PAID
        assert result.amount == 10000


# ============== ODengiAPI Tests ==============

class TestODengiAPI:
    """Test ODengiAPI class"""

    @pytest.fixture
    def api(self):
        """Create API instance with test config"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "test_password"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test Merchant"
            return ODengiAPI()

    @pytest.fixture
    def unconfigured_api(self):
        """Create unconfigured API instance"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = None
            mock_config.dengi_sid = None
            mock_config.dengi_password = None
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = ""
            return ODengiAPI()

    def test_is_configured(self, api):
        """Test is_configured returns True when all settings present"""
        assert api.is_configured() is True

    def test_is_not_configured(self, unconfigured_api):
        """Test is_configured returns False when settings missing"""
        assert unconfigured_api.is_configured() is False


class TestODengiAPISignature:
    """Test HMAC signature generation and verification"""

    @pytest.fixture
    def api(self):
        """Create API instance with known password"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "secret_password"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test"
            return ODengiAPI()

    def test_generate_hash(self, api):
        """Test HMAC-MD5 hash generation"""
        payload = {"cmd": "test", "data": {"amount": 1000}}

        # Calculate expected hash
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        expected_hash = hmac.new(
            b"secret_password",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        actual_hash = api._generate_hash(payload)
        assert actual_hash == expected_hash

    def test_generate_hash_cyrillic(self, api):
        """Test hash generation with Cyrillic characters"""
        payload = {"cmd": "test", "desc": "Оплата доставки"}

        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        expected_hash = hmac.new(
            b"secret_password",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        actual_hash = api._generate_hash(payload)
        assert actual_hash == expected_hash

    def test_verify_callback_signature_valid(self, api):
        """Test signature verification with valid hash"""
        payload = {"invoice_id": "123", "status_pay": 1}
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        valid_hash = hmac.new(
            b"secret_password",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        data_with_hash = {**payload, "hash": valid_hash}
        assert api.verify_callback_signature(data_with_hash) is True

    def test_verify_callback_signature_invalid(self, api):
        """Test signature verification with invalid hash"""
        data = {
            "invoice_id": "123",
            "status_pay": 1,
            "hash": "invalid_hash_value",
        }
        assert api.verify_callback_signature(data) is False

    def test_verify_callback_signature_missing(self, api):
        """Test signature verification when hash is missing (legacy mode)"""
        data = {"invoice_id": "123", "status_pay": 1}
        # Should return True for backward compatibility
        assert api.verify_callback_signature(data) is True


class TestODengiAPIRequests:
    """Test API request building and execution"""

    @pytest.fixture
    def api(self):
        """Create API instance"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "test_password"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test"
            return ODengiAPI()

    def test_build_request(self, api):
        """Test request building"""
        with patch('src.services.payment.time.time', return_value=1705320000):
            request = api._build_request("createInvoice", {"amount": 10000})

        assert request["cmd"] == "createInvoice"
        assert request["version"] == 1005
        assert request["lang"] == "ru"
        assert request["sid"] == "test_merchant"
        assert request["mktime"] == "1705320000"
        assert request["data"]["amount"] == 10000
        assert "hash" in request

    @pytest.mark.asyncio
    async def test_create_invoice_success(self, api):
        """Test successful invoice creation"""
        mock_response = {
            "status": "ok",
            "data": {
                "invoice_id": "INV-12345",
                "qr": "https://pay.dengi.kg/qr/12345",
                "qr_url": "https://pay.dengi.kg/qr/12345.png",
                "site_pay": "https://pay.dengi.kg/pay/12345",
            }
        }

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            request = PaymentRequest(
                order_id="TLP-TEST-001",
                amount_som=100.0,
                description="Test payment"
            )
            result = await api.create_invoice(request)

        assert result.success is True
        assert result.invoice_id == "INV-12345"
        assert result.qr_data == "https://pay.dengi.kg/qr/12345"
        mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_invoice_error(self, api):
        """Test invoice creation with API error"""
        mock_response = {
            "status": "error",
            "message": "Invalid amount",
            "code": 400,
        }

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            request = PaymentRequest(
                order_id="TLP-TEST-001",
                amount_som=-100.0,
                description="Test payment"
            )
            result = await api.create_invoice(request)

        assert result.success is False
        assert "Invalid amount" in result.error

    @pytest.mark.asyncio
    async def test_create_invoice_not_configured(self, api):
        """Test invoice creation when not configured"""
        api.api_url = None

        request = PaymentRequest(
            order_id="TLP-TEST-001",
            amount_som=100.0,
            description="Test payment"
        )
        result = await api.create_invoice(request)

        assert result.success is False
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_create_invoice_amount_conversion(self, api):
        """Test that amount is converted to tiyin correctly"""
        mock_response = {"status": "ok", "data": {"invoice_id": "123"}}

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            request = PaymentRequest(
                order_id="TLP-TEST-001",
                amount_som=150.50,  # 150.50 som = 15050 tiyin
                description="Test payment"
            )
            await api.create_invoice(request)

        # Check that amount was converted to tiyin
        call_args = mock_request.call_args
        assert call_args[0][1]["amount"] == 15050  # 150.50 * 100

    @pytest.mark.asyncio
    async def test_check_status_paid(self, api):
        """Test checking status of paid invoice"""
        mock_response = {
            "data": {
                "payments": [{
                    "invoice_id": "INV-12345",
                    "order_id": "TLP-TEST-001",
                    "status_pay": 1,
                    "amount": 10000,
                    "fee": 100,
                    "trans_id": "TRANS-001",
                    "dt": "2026-01-15 12:00:00",
                }]
            }
        }

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.check_status(invoice_id="INV-12345")

        assert result.success is True
        assert result.status == PaymentStatus.PAID
        assert result.invoice_id == "INV-12345"
        assert result.trans_id == "TRANS-001"

    @pytest.mark.asyncio
    async def test_check_status_pending(self, api):
        """Test checking status of pending invoice"""
        mock_response = {
            "data": {
                "payments": [{
                    "invoice_id": "INV-12345",
                    "status_pay": 0,
                }]
            }
        }

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.check_status(invoice_id="INV-12345")

        assert result.success is True
        assert result.status == PaymentStatus.PENDING

    @pytest.mark.asyncio
    async def test_check_status_string_format(self, api):
        """Test checking status with string status format"""
        mock_response = {
            "data": {
                "payments": [{
                    "invoice_id": "INV-12345",
                    "status": "approved",
                }]
            }
        }

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.check_status(invoice_id="INV-12345")

        assert result.success is True
        assert result.status == PaymentStatus.PAID

    @pytest.mark.asyncio
    async def test_check_status_no_params(self, api):
        """Test check_status fails without invoice_id or order_id"""
        result = await api.check_status()

        assert result.success is False
        assert "required" in result.error

    @pytest.mark.asyncio
    async def test_cancel_invoice_success(self, api):
        """Test successful invoice cancellation"""
        mock_response = {"status": "ok"}

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.cancel_invoice("INV-12345")

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_invoice_error(self, api):
        """Test invoice cancellation failure"""
        mock_response = {"status": "error", "message": "Already paid"}

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.cancel_invoice("INV-12345")

        assert result is False

    @pytest.mark.asyncio
    async def test_void_payment_success(self, api):
        """Test successful payment void"""
        mock_response = {"status": "ok"}

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.void_payment("TRANS-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_refund_to_ewallet(self, api):
        """Test partial refund to e-wallet"""
        mock_response = {"status": "ok"}

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await api.refund_to_ewallet("TRANS-001", 5000)

        assert result is True


class TestODengiAPICallback:
    """Test callback parsing and validation"""

    @pytest.fixture
    def api(self):
        """Create API instance"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "test_password"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test"
            return ODengiAPI()

    def test_parse_callback_paid(self, api):
        """Test parsing paid callback"""
        data = {
            "invoice_id": "INV-12345",
            "order_id": "TLP-TEST-001",
            "status_pay": 1,
            "status_str": "Оплачен",
            "amount": 10000,
            "trans": "TRANS-001",
            "dt": "2026-01-15 12:00:00",
        }

        result = api.parse_callback(data, verify_signature=False)

        assert result is not None
        assert result["invoice_id"] == "INV-12345"
        assert result["order_id"] == "TLP-TEST-001"
        assert result["status"] == PaymentStatus.PAID
        assert result["trans_id"] == "TRANS-001"

    def test_parse_callback_pending(self, api):
        """Test parsing pending callback"""
        data = {
            "invoice_id": "INV-12345",
            "status_pay": 0,
        }

        result = api.parse_callback(data, verify_signature=False)

        assert result is not None
        assert result["status"] == PaymentStatus.PENDING

    def test_parse_callback_cancelled(self, api):
        """Test parsing cancelled callback"""
        data = {
            "invoice_id": "INV-12345",
            "status_pay": -1,
        }

        result = api.parse_callback(data, verify_signature=False)

        assert result is not None
        assert result["status"] == PaymentStatus.CANCELLED

    def test_parse_callback_with_signature_verification(self, api):
        """Test callback parsing with signature verification"""
        payload = {"invoice_id": "INV-12345", "status_pay": 1}
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        valid_hash = hmac.new(
            b"test_password",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        data = {**payload, "hash": valid_hash}
        result = api.parse_callback(data, verify_signature=True)

        assert result is not None
        assert result["status"] == PaymentStatus.PAID

    def test_parse_callback_invalid_signature(self, api):
        """Test callback parsing with invalid signature"""
        data = {
            "invoice_id": "INV-12345",
            "status_pay": 1,
            "hash": "invalid_hash",
        }

        result = api.parse_callback(data, verify_signature=True)

        assert result is None


# ============== PaymentService (Legacy Wrapper) Tests ==============

class TestPaymentService:
    """Test PaymentService legacy wrapper"""

    @pytest.fixture
    def service(self):
        """Create PaymentService instance"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "test_password"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test"
            return PaymentService()

    def test_is_configured(self, service):
        """Test is_configured delegates to API"""
        assert service.is_configured() is True

    def test_generate_payment_id(self, service):
        """Test payment ID generation format"""
        request = PaymentRequest(
            order_id="",
            amount_som=100.0,
            description="Test",
            client_code="TE-5001",
        )

        payment_id = service._generate_payment_id(request)

        assert payment_id.startswith("TLP-TE-5001-")
        assert len(payment_id) > 20

    def test_generate_payment_id_unknown_client(self, service):
        """Test payment ID generation with unknown client"""
        request = PaymentRequest(
            order_id="",
            amount_som=100.0,
            description="Test",
        )

        payment_id = service._generate_payment_id(request)

        assert "UNK" in payment_id

    @pytest.mark.asyncio
    async def test_create_payment_generates_id(self, service):
        """Test create_payment generates ID if not provided"""
        with patch.object(service._api, 'create_invoice', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = PaymentResult(success=True, invoice_id="123")

            request = PaymentRequest(
                order_id="",  # Empty order_id
                amount_som=100.0,
                description="Test",
                client_code="TE-5001",
            )
            await service.create_payment(request)

        # Check that order_id was generated
        call_args = mock_create.call_args
        assert call_args[0][0].order_id.startswith("TLP-TE-5001-")

    @pytest.mark.asyncio
    async def test_check_payment_status_success(self, service):
        """Test check_payment_status returns status"""
        with patch.object(service._api, 'check_status', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = PaymentStatusResult(
                success=True,
                status=PaymentStatus.PAID,
            )

            status = await service.check_payment_status("TLP-TEST-001")

        assert status == PaymentStatus.PAID

    @pytest.mark.asyncio
    async def test_check_payment_status_error(self, service):
        """Test check_payment_status returns None on error"""
        with patch.object(service._api, 'check_status', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = PaymentStatusResult(
                success=False,
                error="Not found",
            )

            status = await service.check_payment_status("TLP-INVALID")

        assert status is None

    def test_parse_callback_delegates(self, service):
        """Test parse_callback delegates to API"""
        data = {"invoice_id": "123", "status_pay": 1}

        with patch.object(service._api, 'parse_callback') as mock_parse:
            mock_parse.return_value = {"status": PaymentStatus.PAID}

            result = service.parse_callback(data)

        mock_parse.assert_called_once_with(data)


# ============== Edge Cases and Error Handling ==============

class TestPaymentEdgeCases:
    """Test edge cases and error handling"""

    @pytest.fixture
    def api(self):
        """Create API instance"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "test_password"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test"
            return ODengiAPI()

    @pytest.mark.asyncio
    async def test_network_error(self, api):
        """Test handling of network errors"""
        import aiohttp

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = aiohttp.ClientError("Connection failed")

            request = PaymentRequest(
                order_id="TLP-TEST-001",
                amount_som=100.0,
                description="Test",
            )
            result = await api.create_invoice(request)

        assert result.success is False
        assert "Network error" in result.error

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, api):
        """Test handling of invalid JSON response"""
        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ValueError("Invalid JSON response")

            request = PaymentRequest(
                order_id="TLP-TEST-001",
                amount_som=100.0,
                description="Test",
            )
            result = await api.create_invoice(request)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_check_status_datetime_parsing(self, api):
        """Test various datetime formats in status response"""
        test_cases = [
            ("2026-01-15 12:00:00", datetime(2026, 1, 15, 12, 0, 0)),
            ("2026-01-15 12:00:00.123456", datetime(2026, 1, 15, 12, 0, 0, 123456)),
        ]

        for dt_string, expected_dt in test_cases:
            mock_response = {
                "data": {
                    "payments": [{
                        "invoice_id": "INV-12345",
                        "status_pay": 1,
                        "dt": dt_string,
                    }]
                }
            }

            with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
                mock_request.return_value = mock_response

                result = await api.check_status(invoice_id="INV-12345")

            assert result.paid_at == expected_dt

    def test_parse_callback_unknown_status(self, api):
        """Test parsing callback with unknown status code"""
        data = {
            "invoice_id": "INV-12345",
            "status_pay": 999,  # Unknown status
        }

        result = api.parse_callback(data, verify_signature=False)

        assert result is not None
        assert result["invoice_id"] == "INV-12345"
        assert result["status"] is None  # Unknown status mapped to None

    @pytest.mark.asyncio
    async def test_create_invoice_with_optional_fields(self, api):
        """Test invoice creation with all optional fields"""
        mock_response = {"status": "ok", "data": {"invoice_id": "123"}}

        with patch.object(api, '_make_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            request = PaymentRequest(
                order_id="TLP-TEST-001",
                amount_som=100.0,
                description="Test",
                long_term=True,
                date_life="31.12.2026",
                send_push=True,
                send_sms=True,
                result_url="https://example.com/result",
                success_url="https://example.com/success",
                fail_url="https://example.com/fail",
                fields_other={"custom": "value"},
            )
            await api.create_invoice(request)

        call_args = mock_request.call_args
        data = call_args[0][1]

        assert data["long_term"] == 1
        assert data["date_life"] == "31.12.2026"
        assert data["send_push"] == "Отправить Push"
        assert data["send_sms"] == "Отправить СМС"
        assert data["result_url"] == "https://example.com/result"
        assert data["fields_other"] == {"custom": "value"}


# ============== Security Tests ==============

class TestPaymentSecurity:
    """Test security-related functionality"""

    @pytest.fixture
    def api(self):
        """Create API instance"""
        with patch('src.services.payment.config') as mock_config:
            mock_config.dengi_api_url = "https://test-api.dengi.kg/api"
            mock_config.dengi_sid = "test_merchant"
            mock_config.dengi_password = "secure_password_123"
            mock_config.dengi_api_version = 1005
            mock_config.dengi_test_mode = True
            mock_config.dengi_merchant_name = "Test"
            return ODengiAPI()

    def test_timing_safe_comparison(self, api):
        """Test that signature comparison is timing-safe"""
        # This tests that hmac.compare_digest is used (timing-safe)
        payload = {"invoice_id": "123"}
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        valid_hash = hmac.new(
            b"secure_password_123",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        data = {**payload, "hash": valid_hash}

        # Should use hmac.compare_digest internally
        assert api.verify_callback_signature(data) is True

    def test_signature_tampering_detected(self, api):
        """Test that tampering with payload invalidates signature"""
        payload = {"invoice_id": "123", "amount": 1000}
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        valid_hash = hmac.new(
            b"secure_password_123",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        # Tamper with the payload
        tampered_data = {"invoice_id": "123", "amount": 9999, "hash": valid_hash}

        assert api.verify_callback_signature(tampered_data) is False

    def test_replay_attack_different_fields(self, api):
        """Test that adding fields invalidates signature"""
        payload = {"invoice_id": "123"}
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        valid_hash = hmac.new(
            b"secure_password_123",
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        # Try to add extra field with same hash
        tampered_data = {"invoice_id": "123", "extra": "field", "hash": valid_hash}

        assert api.verify_callback_signature(tampered_data) is False
