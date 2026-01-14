"""
Tulpar Express - Payment Handlers
Handles payment callbacks and confirmation
"""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, URLInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from src.filters import IsAdmin
from src.services.database import db_service
from src.services.notifications import send_admin_payment_notification
from src.services.payment import payment_service, odengi_api, PaymentStatus, PaymentRequest
from src.keyboards import get_payment_status_keyboard
from src.config import config

logger = logging.getLogger(__name__)

payment_router = Router(name="payment")


# ============== Client Payment Callbacks ==============

@payment_router.callback_query(F.data.startswith("pay:"))
async def handle_pay_button(callback: CallbackQuery, bot: Bot):
    """
    Handle payment button click from client.
    Creates invoice and shows QR code.

    Callback data format: pay:{client_code}:{amount}
    """
    await callback.answer("⏳ Создаю счёт на оплату...")

    try:
        # Parse callback data
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.message.answer("❌ Ошибка: неверный формат данных")
            return

        _, client_code, amount_str = parts
        amount_som = float(amount_str)

        # Generate unique order ID
        order_id = f"TLP-{client_code}-{int(datetime.now().timestamp())}"

        # Create payment request
        request = PaymentRequest(
            order_id=order_id,
            amount_som=amount_som,
            description=f"Оплата доставки Tulpar Express - {client_code}",
            client_code=client_code,
            chat_id=callback.from_user.id,
        )

        # Create invoice via O-Dengi API
        result = await odengi_api.create_invoice(request)

        if not result.success:
            await callback.message.answer(
                f"❌ Ошибка создания счёта:\n{result.error}"
            )
            return

        # Save payment to database (if available)
        if config.database_url:
            try:
                await db_service.create_payment(
                    payment_id=order_id,
                    client_code=client_code,
                    chat_id=callback.from_user.id,
                    amount_som=amount_som,
                    description=f"Invoice: {result.invoice_id}",
                    qr_data=result.qr_data,
                )
            except Exception as e:
                logger.warning(f"Failed to save payment to DB: {e}")

        # Build payment message
        payment_url = result.raw_response.get("data", {}).get("site_pay", "")
        qr_url = result.qr_data

        text = (
            f"💳 <b>Счёт на оплату</b>\n\n"
            f"Сумма: <b>{amount_som:.0f} сом</b>\n"
            f"Код клиента: {client_code}\n"
            f"Номер счёта: <code>{result.invoice_id}</code>\n\n"
            f"🔗 <b>Оплатить:</b>\n"
            f"<a href=\"{payment_url}\">Открыть страницу оплаты</a>\n\n"
            f"📱 Или отсканируйте QR-код приложением O!Денги"
        )

        # Send QR code image
        if qr_url:
            try:
                qr_photo = URLInputFile(qr_url, filename="qr_payment.png")
                await callback.message.answer_photo(
                    photo=qr_photo,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=get_payment_status_keyboard(result.invoice_id)
                )
            except TelegramBadRequest:
                # If QR image fails, send text with link
                await callback.message.answer(
                    text + f"\n\n🔗 QR-код: {qr_url}",
                    parse_mode="HTML",
                    reply_markup=get_payment_status_keyboard(result.invoice_id),
                    disable_web_page_preview=True
                )
        else:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=get_payment_status_keyboard(result.invoice_id)
            )

        logger.info(f"Payment invoice created: {result.invoice_id} for {client_code}, {amount_som} som")

    except Exception as e:
        logger.exception(f"Payment creation error: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


@payment_router.callback_query(F.data.startswith("check_pay:"))
async def handle_check_payment(callback: CallbackQuery, bot: Bot):
    """Check payment status"""
    await callback.answer("🔄 Проверяю статус...")

    try:
        invoice_id = callback.data.split(":")[1]

        # Check status via API
        result = await odengi_api.check_status(invoice_id=invoice_id)

        if not result.success:
            await callback.message.answer(f"❌ Ошибка проверки: {result.error}")
            return

        status_text = result.status_str or str(result.status) if result.status else "Ожидает оплаты"

        if result.status == PaymentStatus.PAID:
            # Payment successful! Process it (update DB + notify admin)
            if result.order_id:
                await process_payment_success(bot, result.order_id)
            else:
                # Fallback: just show success message
                await callback.message.answer(
                    "✅ <b>Оплата прошла успешно!</b>\n\n"
                    "Спасибо! Можете забрать посылку в пункте выдачи.",
                    parse_mode="HTML"
                )
            # Try to delete the QR message
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass  # Message already deleted or not found
        else:
            await callback.message.answer(
                f"📊 <b>Статус платежа:</b> {status_text}\n\n"
                f"Счёт: <code>{invoice_id}</code>",
                parse_mode="HTML",
                reply_markup=get_payment_status_keyboard(invoice_id)
            )

    except Exception as e:
        logger.exception(f"Check payment error: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


@payment_router.callback_query(F.data.startswith("cancel_pay:"))
async def handle_cancel_payment(callback: CallbackQuery):
    """Cancel unpaid invoice"""
    await callback.answer("🗑 Отменяю счёт...")

    try:
        invoice_id = callback.data.split(":")[1]

        # Cancel via API
        success = await odengi_api.cancel_invoice(invoice_id)

        if success:
            await callback.message.answer("✅ Счёт отменён")
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass  # Message already deleted or not found
        else:
            await callback.message.answer(
                "⚠️ Не удалось отменить счёт.\n"
                "Возможно он уже оплачен или истёк."
            )

    except Exception as e:
        logger.exception(f"Cancel payment error: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


async def process_payment_success(
    bot: Bot,
    payment_id: str,
) -> bool:
    """
    Process a successful payment:
    1. Update payment status in DB
    2. Delete QR message from user's chat
    3. Send success message to user
    4. Notify admins

    Returns True if processed successfully
    """
    # Get payment from database
    payment = await db_service.get_payment_by_id(payment_id)
    if not payment:
        logger.error(f"Payment not found: {payment_id}")
        return False

    if payment["status"] == "PAID":
        logger.info(f"Payment already processed: {payment_id}")
        return True

    chat_id = payment["chat_id"]
    message_id = payment["message_id"]
    amount_som = float(payment["amount_som"])
    client_code = payment["client_code"]

    # Update payment status
    await db_service.update_payment_status(
        payment_id=payment_id,
        status="PAID",
        paid_at=datetime.now(),
    )

    # Delete QR message if we have message_id
    if message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Deleted QR message {message_id} for {client_code}")
        except Exception as e:
            logger.warning(f"Could not delete QR message: {e}")

    # Send success message to user
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ <b>Оплата прошла успешно!</b>\n\n"
                f"Сумма: {amount_som:.0f} сом\n"
                f"Код: {client_code}\n\n"
                "Спасибо! Можете забрать посылку в пункте выдачи."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to send success message to {chat_id}: {e}")

    # Get client name for admin notification
    from src.services.sheets import sheets_service
    client = await sheets_service.get_client_by_code(client_code)
    client_name = client.full_name if client else client_code

    # Notify admins
    await send_admin_payment_notification(
        bot=bot,
        admin_chat_ids=config.admin_chat_ids,
        client_code=client_code,
        client_name=client_name,
        amount_som=amount_som,
        payment_id=payment_id,
    )

    logger.info(f"Payment processed successfully: {payment_id}")
    return True


# ============== Admin Commands for Payment Management ==============

@payment_router.message(Command("confirm_payment"), IsAdmin())
async def confirm_payment_cmd(message: Message, bot: Bot):
    """
    Admin command to manually confirm a payment
    Usage: /confirm_payment TLP-TE-5036-...
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ Укажите ID платежа:\n"
            "<code>/confirm_payment TLP-TE-XXXX-...</code>"
        )
        return

    payment_id = args[1].strip()

    # Process the payment
    success = await process_payment_success(bot, payment_id)

    if success:
        await message.answer(f"✅ Платёж подтверждён: {payment_id}")
    else:
        await message.answer(f"❌ Ошибка подтверждения платежа: {payment_id}")


@payment_router.message(Command("pending_payments"), IsAdmin())
async def list_pending_payments(message: Message):
    """List all pending payments for admin review"""
    if not config.database_url:
        await message.answer("❌ База данных не настроена")
        return

    async with db_service._pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT payment_id, client_code, amount_som, created_at
            FROM payments
            WHERE status = 'PENDING'
            ORDER BY created_at DESC
            LIMIT 20
        """)

    if not rows:
        await message.answer("✅ Нет ожидающих платежей")
        return

    lines = ["<b>💳 Ожидающие платежи:</b>\n"]
    for row in rows:
        lines.append(
            f"• {row['client_code']}: {row['amount_som']:.0f} сом\n"
            f"  <code>{row['payment_id']}</code>"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@payment_router.message(Command("check_payment"), IsAdmin())
async def check_payment_status_cmd(message: Message, bot: Bot):
    """
    Check payment status with payment gateway
    Usage: /check_payment TLP-TE-5036-...
    """
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❌ Укажите ID платежа:\n"
            "<code>/check_payment TLP-TE-XXXX-...</code>"
        )
        return

    payment_id = args[1].strip()

    # Check with payment gateway
    status = await payment_service.check_payment_status(payment_id)

    if status is None:
        await message.answer(f"❌ Не удалось проверить статус: {payment_id}")
        return

    await message.answer(f"💳 Статус платежа {payment_id}: <b>{status.name}</b> ({status.value})")

    # If paid, process it
    if status == PaymentStatus.PAID:
        success = await process_payment_success(bot, payment_id)
        if success:
            await message.answer("✅ Платёж обработан!")


# ============== Webhook Handler for Payment Callbacks ==============

async def handle_payment_webhook(data: dict, bot: Bot) -> dict:
    """
    Handle incoming webhook from payment gateway

    Args:
        data: Webhook payload
        bot: Bot instance for sending messages

    Returns:
        Response dict with status
    """
    try:
        logger.info(f"Payment webhook received: {data}")

        # Parse callback data
        parsed = payment_service.parse_callback(data)
        if not parsed:
            return {"status": "error", "message": "Invalid callback data"}

        payment_id = parsed.get("order_id")

        if not payment_id:
            return {"status": "error", "message": "Missing payment_id"}

        # Check if payment is successful
        payment_status = parsed.get("status")
        if payment_status == PaymentStatus.PAID:
            success = await process_payment_success(bot, payment_id)
            return {
                "status": "ok" if success else "error",
                "payment_id": payment_id,
            }

        return {"status": "ok", "message": f"Status {payment_status} ignored"}

    except Exception as e:
        logger.exception(f"Webhook processing error: {e}")
        return {"status": "error", "message": str(e)}
