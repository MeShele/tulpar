"""
Tulpar Express - Payment Service (O-Dengi / dengi.kg)
QR code payment generation via O-Dengi API
API Documentation: sandbox.dengi.kg
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import IntEnum

import aiohttp

from src.config import config

logger = logging.getLogger(__name__)


class PaymentStatus(IntEnum):
    """O-Dengi payment status codes (status_pay field)"""
    PENDING = 0          # Ожидает оплаты
    PAID = 1             # Оплачен
    CANCELLED = -1       # Отменён
    EXPIRED = -2         # Просрочен
    PROCESSING = 2       # В обработке
    PARTIAL_REFUND = 3   # Частичный возврат
    FULL_REFUND = 4      # Полный возврат


@dataclass
class PaymentRequest:
    """Payment request data for createInvoice"""
    order_id: str
    amount_som: float
    description: str
    client_code: Optional[str] = None
    chat_id: Optional[int] = None
    user_id: Optional[str] = None
    # Optional settings
    long_term: bool = False
    date_life: Optional[str] = None  # Format: DD.MM.YYYY
    send_push: bool = True
    send_sms: bool = False
    result_url: Optional[str] = None
    success_url: Optional[str] = None
    fail_url: Optional[str] = None
    fields_other: Optional[Dict[str, Any]] = None


@dataclass
class PaymentResult:
    """Result of payment creation"""
    success: bool
    invoice_id: Optional[str] = None
    order_id: Optional[str] = None
    qr_data: Optional[str] = None
    qr_image_url: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[int] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class PaymentStatusResult:
    """Result of payment status check"""
    success: bool
    status: Optional[PaymentStatus] = None
    status_str: Optional[str] = None
    invoice_id: Optional[str] = None
    order_id: Optional[str] = None
    amount: Optional[int] = None
    fee: Optional[int] = None
    trans_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class ODengiAPI:
    """O-Dengi Payment API Client"""

    # API Commands
    CMD_CREATE_INVOICE = "createInvoice"
    CMD_STATUS_PAYMENT = "statusPayment"
    CMD_UPDATE_MARK = "updateMark"
    CMD_INVOICE_CANCEL = "invoiceCancel"
    CMD_VOID_PAYMENT = "voidPayment"
    CMD_REFUND_TO_EWALLET = "refundPaymentToEwallet"
    CMD_CHANGE_DESCRIPTION = "changeInvoiceDescription"
    CMD_GET_HISTORY = "getHistoryCsv"

    def __init__(self) -> None:
        self.api_url = config.dengi_api_url
        self.sid = config.dengi_sid
        self.password = config.dengi_password
        self.api_version = config.dengi_api_version
        self.test_mode = config.dengi_test_mode
        self.merchant_name = config.dengi_merchant_name

    def is_configured(self) -> bool:
        """Check if payment service is properly configured"""
        return bool(self.api_url and self.sid and self.password)

    def _generate_hash(self, payload: Dict[str, Any]) -> str:
        """
        Generate HMAC-MD5 signature for API request.

        Hash is calculated from JSON string without spaces/newlines.
        """
        # Create JSON string without spaces (compact)
        json_string = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)

        # Calculate HMAC-MD5
        signature = hmac.new(
            self.password.encode('utf-8'),
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        return signature

    def _build_request(self, cmd: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Build API request with proper structure and signature"""
        mktime = str(int(time.time()))

        # Base payload without hash
        payload = {
            "cmd": cmd,
            "version": self.api_version,
            "lang": "ru",
            "sid": self.sid,
            "mktime": mktime,
            "data": data,
        }

        # Generate hash from payload
        payload["hash"] = self._generate_hash(payload)

        return payload

    async def _make_request(self, cmd: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make API request to O-Dengi.

        Returns parsed response or raises exception.
        """
        if not self.is_configured():
            raise ValueError("Payment service not configured")

        payload = self._build_request(cmd, data)

        # Log request without sensitive data (hash, sid excluded from log)
        safe_log_data = {k: v for k, v in data.items() if k not in ("password", "hash")}
        logger.debug(f"O-Dengi request [{cmd}]: {json.dumps(safe_log_data, ensure_ascii=False)}")

        connector = aiohttp.TCPConnector()  # SSL enabled by default
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                self.api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True,
            ) as response:
                response_text = await response.text()
                # Log response without sensitive data (truncate and exclude hash)
                safe_response = response_text[:500].replace(payload.get("hash", ""), "[HASH]")
                logger.debug(f"O-Dengi response [{cmd}]: {safe_response}")

                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON response: {response_text[:200]}") from e

                return result

    # ==================== Public API Methods ====================

    async def create_invoice(self, request: PaymentRequest) -> PaymentResult:
        """
        Create payment invoice and get QR code.

        API: createInvoice
        """
        if not self.is_configured():
            return PaymentResult(success=False, error="Payment service not configured")

        try:
            # Amount in tiyin (1 som = 100 tiyin)
            amount_tiyin = int(request.amount_som * 100)

            data = {
                "order_id": request.order_id,
                "desc": request.description,
                "amount": amount_tiyin,
                "currency": "KGS",
                "test": 1 if self.test_mode else 0,
            }

            # Optional fields
            if request.long_term:
                data["long_term"] = 1
            if request.user_id:
                data["user_id"] = request.user_id
            if request.date_life:
                data["date_life"] = request.date_life
            if request.send_push:
                data["send_push"] = "Отправить Push"
            if request.send_sms:
                data["send_sms"] = "Отправить СМС"
            if request.result_url:
                data["result_url"] = request.result_url
            if request.success_url:
                data["success_url"] = request.success_url
            if request.fail_url:
                data["fail_url"] = request.fail_url
            if request.fields_other:
                data["fields_other"] = request.fields_other

            result = await self._make_request(self.CMD_CREATE_INVOICE, data)

            # Check for API error
            if result.get("status") == "error" or result.get("error"):
                error_msg = result.get("message") or result.get("error") or "Unknown error"
                return PaymentResult(
                    success=False,
                    error=error_msg,
                    error_code=result.get("code"),
                    raw_response=result,
                )

            # Response structure: {"data": {"invoice_id": ..., "qr": ..., ...}}
            response_data = result.get("data", result)

            # Check for error in response data
            if "error" in response_data:
                error_msg = response_data.get("desc") or f"Error code: {response_data.get('error')}"
                return PaymentResult(
                    success=False,
                    error=error_msg,
                    error_code=response_data.get("error"),
                    raw_response=result,
                )

            # Extract QR data from response
            # Response contains: qr, emv_qr, qr_url, paylink_url, link_app, site_pay
            qr_data = (
                response_data.get("qr") or
                response_data.get("emv_qr") or
                response_data.get("paylink_url")
            )
            qr_image_url = (
                response_data.get("qr_url") or
                response_data.get("site_pay") or
                response_data.get("link_app")
            )

            return PaymentResult(
                success=True,
                invoice_id=response_data.get("invoice_id"),
                order_id=request.order_id,
                qr_data=qr_data,
                qr_image_url=qr_image_url,
                raw_response=result,
            )

        except aiohttp.ClientError as e:
            logger.exception(f"O-Dengi network error: {e}")
            return PaymentResult(success=False, error=f"Network error: {str(e)}")
        except Exception as e:
            logger.exception(f"O-Dengi create_invoice error: {e}")
            return PaymentResult(success=False, error=str(e))

    async def check_status(
        self,
        invoice_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> PaymentStatusResult:
        """
        Check payment status.

        API: statusPayment
        Provide either invoice_id or order_id.
        """
        if not self.is_configured():
            return PaymentStatusResult(success=False, error="Payment service not configured")

        if not invoice_id and not order_id:
            return PaymentStatusResult(success=False, error="invoice_id or order_id required")

        try:
            data = {}
            if invoice_id:
                data["invoice_id"] = invoice_id
            if order_id:
                data["order_id"] = order_id

            result = await self._make_request(self.CMD_STATUS_PAYMENT, data)

            # Response structure: {"data": {"payments": [...]}} or {"data": {...}}
            response_data = result.get("data", result)

            # Check for API error
            if "error" in response_data:
                error_msg = response_data.get("desc") or f"Error code: {response_data.get('error')}"
                return PaymentStatusResult(
                    success=False,
                    error=error_msg,
                    raw_response=result,
                )

            # Handle payments array format (statusPayment returns array)
            payment_data = response_data
            if "payments" in response_data and response_data["payments"]:
                payment_data = response_data["payments"][0]

            # Parse status - handle both integer (status_pay) and string (status) formats
            status = None
            status_str = None

            # Try status_pay (integer) first
            status_pay = payment_data.get("status_pay")
            if status_pay is not None:
                try:
                    status = PaymentStatus(int(status_pay))
                except ValueError:
                    logger.warning(f"Unknown status_pay value: {status_pay}")

            # Try status (string) - O-Dengi returns "approved", "pending", etc.
            status_string = payment_data.get("status")
            if status_string and not status:
                status_str = status_string
                status_map = {
                    "approved": PaymentStatus.PAID,
                    "paid": PaymentStatus.PAID,
                    "pending": PaymentStatus.PENDING,
                    "cancelled": PaymentStatus.CANCELLED,
                    "canceled": PaymentStatus.CANCELLED,
                    "expired": PaymentStatus.EXPIRED,
                    "processing": PaymentStatus.PROCESSING,
                }
                status = status_map.get(status_string.lower())

            # Parse datetime - handle both "dt" and "date_pay" fields
            paid_at = None
            dt_value = payment_data.get("dt") or payment_data.get("date_pay")
            if dt_value:
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
                    try:
                        paid_at = datetime.strptime(dt_value, fmt)
                        break
                    except ValueError:
                        continue

            return PaymentStatusResult(
                success=True,
                status=status,
                status_str=status_str or payment_data.get("status_str"),
                invoice_id=payment_data.get("invoice_id"),
                order_id=payment_data.get("order_id"),
                amount=payment_data.get("amount"),
                fee=payment_data.get("fee"),
                trans_id=payment_data.get("trans_id") or payment_data.get("trans"),
                paid_at=paid_at,
                raw_response=result,
            )

        except Exception as e:
            logger.exception(f"O-Dengi check_status error: {e}")
            return PaymentStatusResult(success=False, error=str(e))

    async def cancel_invoice(self, invoice_id: str) -> bool:
        """
        Cancel unpaid invoice.

        API: invoiceCancel
        """
        if not self.is_configured():
            return False

        try:
            result = await self._make_request(
                self.CMD_INVOICE_CANCEL,
                {"invoice_id": invoice_id}
            )

            if result.get("status") == "error":
                logger.warning(f"Cancel invoice error: {result.get('message')}")
                return False

            return True

        except Exception as e:
            logger.exception(f"O-Dengi cancel_invoice error: {e}")
            return False

    async def void_payment(self, trans_id: str) -> bool:
        """
        Void (fully cancel) a completed payment.

        API: voidPayment
        """
        if not self.is_configured():
            return False

        try:
            result = await self._make_request(
                self.CMD_VOID_PAYMENT,
                {"trans_id": trans_id}
            )

            if result.get("status") == "error":
                logger.warning(f"Void payment error: {result.get('message')}")
                return False

            return True

        except Exception as e:
            logger.exception(f"O-Dengi void_payment error: {e}")
            return False

    async def refund_to_ewallet(self, trans_id: str, amount: int) -> bool:
        """
        Partial refund to user's e-wallet.

        API: refundPaymentToEwallet

        Args:
            trans_id: Transaction ID
            amount: Amount in tiyin to refund
        """
        if not self.is_configured():
            return False

        try:
            result = await self._make_request(
                self.CMD_REFUND_TO_EWALLET,
                {"trans_id": trans_id, "amount": amount}
            )

            if result.get("status") == "error":
                logger.warning(f"Refund error: {result.get('message')}")
                return False

            return True

        except Exception as e:
            logger.exception(f"O-Dengi refund_to_ewallet error: {e}")
            return False

    def verify_callback_signature(self, data: Dict[str, Any]) -> bool:
        """
        Verify webhook callback signature from O-Dengi.

        The callback should contain a 'hash' field that we verify
        using HMAC-MD5 with our password.

        Args:
            data: Callback payload from O-Dengi

        Returns:
            True if signature is valid or no signature provided (legacy)
        """
        received_hash = data.get("hash")
        if not received_hash:
            # No hash provided - log warning but allow (for backward compatibility)
            logger.warning("Webhook callback received without hash signature")
            return True

        # Create payload without hash for verification
        payload_to_verify = {k: v for k, v in data.items() if k != "hash"}

        # Calculate expected hash
        json_string = json.dumps(payload_to_verify, separators=(',', ':'), ensure_ascii=False)
        expected_hash = hmac.new(
            self.password.encode('utf-8'),
            json_string.encode('utf-8'),
            hashlib.md5
        ).hexdigest()

        is_valid = hmac.compare_digest(received_hash, expected_hash)
        if not is_valid:
            logger.warning(f"Invalid webhook signature. Expected: {expected_hash[:8]}..., Got: {received_hash[:8]}...")

        return is_valid

    def parse_callback(self, data: Dict[str, Any], verify_signature: bool = True) -> Optional[Dict[str, Any]]:
        """
        Parse and verify payment callback/webhook data.

        Args:
            data: Callback payload from O-Dengi
            verify_signature: Whether to verify HMAC signature (default: True)

        Returns:
            Parsed callback with standardized fields, or None if invalid
        """
        try:
            # Verify signature if enabled
            if verify_signature and not self.verify_callback_signature(data):
                logger.error("Webhook signature verification failed - rejecting callback")
                return None

            # Parse status
            status_pay = data.get("status_pay")
            status = None
            if status_pay is not None:
                try:
                    status = PaymentStatus(int(status_pay))
                except ValueError:
                    pass

            return {
                "invoice_id": data.get("invoice_id"),
                "order_id": data.get("order_id"),
                "status": status,
                "status_str": data.get("status_str"),
                "amount": data.get("amount"),
                "trans_id": data.get("trans"),
                "paid_at": data.get("dt"),
            }
        except Exception as e:
            logger.exception(f"Callback parse error: {e}")
            return None


# ==================== Legacy Compatibility Layer ====================
# For backward compatibility with existing code

class PaymentService:
    """Legacy wrapper for ODengiAPI - for backward compatibility"""

    def __init__(self) -> None:
        self._api = ODengiAPI()

    def is_configured(self) -> bool:
        return self._api.is_configured()

    async def create_payment(self, request: PaymentRequest) -> PaymentResult:
        """Legacy method - wraps create_invoice"""
        # Generate order_id if not provided
        if not request.order_id:
            request.order_id = self._generate_payment_id(request)
        return await self._api.create_invoice(request)

    async def check_payment_status(self, payment_id: str) -> Optional[PaymentStatus]:
        """Legacy method - wraps check_status"""
        result = await self._api.check_status(order_id=payment_id)
        return result.status if result.success else None

    def _generate_payment_id(self, request: PaymentRequest) -> str:
        """Generate unique payment ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        client = request.client_code or "UNK"
        data = f"{client}:{request.amount_som}:{timestamp}"
        hash_suffix = hashlib.md5(data.encode()).hexdigest()[:8]
        return f"TLP-{client}-{timestamp}-{hash_suffix}"

    def parse_callback(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._api.parse_callback(data)


# Global instances
odengi_api = ODengiAPI()
payment_service = PaymentService()  # Legacy compatibility
