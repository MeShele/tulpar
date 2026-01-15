"""
Tulpar Express - Excel Handlers
Admin handlers for Excel file processing (Epic 2, 3)
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from src.filters import IsAdmin
from src.services.sheets import sheets_service
from src.services.database import db_service
from src.services.excel_parser import parse_excel, ExcelParseResult
from src.services.notifications import broadcast, send_parcel_notification, send_payment_notification
from src.services.payment import payment_service, PaymentRequest
from src.models import Client, Parcel, ParcelStatus
from src.keyboards import get_admin_menu
from src.config import config

logger = logging.getLogger(__name__)

excel_router = Router(name="excel")

async def get_current_rate() -> float:
    """Get current USD to SOM rate from DB or use config default"""
    if config.database_url:
        try:
            return await db_service.get_usd_rate()
        except Exception:
            pass
    return config.default_usd_to_som


# ============== Excel File Handler (AC 2.2.1-2.2.5) ==============

@excel_router.message(F.document, IsAdmin())
async def handle_excel_file(message: Message, bot: Bot, state: FSMContext):
    """Handle Excel file upload from admin"""
    document = message.document

    # Validate file format (AC 2.2.3)
    if not document.file_name or not document.file_name.endswith(".xlsx"):
        await message.answer("❌ Пожалуйста, отправьте файл в формате Excel (.xlsx)")
        return

    # Get selected type from FSM state (if any)
    data = await state.get_data()
    selected_type = data.get("excel_type")
    await state.clear()  # Clear state after getting the type

    # Acknowledge receipt (AC 2.2.1)
    status_msg = await message.answer("📥 Файл получен. Обрабатываю...")

    try:
        # Download file (AC 2.2.5)
        file = await bot.get_file(document.file_id)
        file_data = io.BytesIO()
        await bot.download_file(file.file_path, file_data)
        file_data.seek(0)

        # Parse Excel (Story 2.3)
        result = parse_excel(file_data, document.file_name)

        if result.errors and not result.rows:
            await status_msg.edit_text(
                f"❌ Ошибка парсинга:\n" + "\n".join(result.errors[:5]),
                reply_markup=None
            )
            return

        # Use selected type if available, otherwise auto-detect
        file_type = selected_type if selected_type else result.file_type

        # Route to appropriate processor (AC 2.2.4)
        if file_type == "bishkek":
            await process_bishkek_excel(message, bot, result, status_msg)
        else:
            await process_china_excel(message, bot, result, status_msg)

    except Exception as e:
        logger.exception(f"Error processing Excel: {e}")
        await status_msg.edit_text(f"❌ Ошибка обработки: {e}")


# ============== China Warehouse Processing (Story 2.4, 2.5) ==============

async def process_china_excel(
    message: Message,
    bot: Bot,
    result: ExcelParseResult,
    status_msg: Message,
):
    """Process China warehouse Excel file"""
    await status_msg.edit_text(
        f"📦 Обработка 'Склад Китай'...\n"
        f"Найдено строк: {len(result.rows)}"
    )

    # Match codes to clients (Story 2.4)
    clients_to_notify = []
    not_found_codes = []

    for row in result.valid_rows:
        client = await sheets_service.get_client_by_code(row.client_code)
        if client:
            clients_to_notify.append(client)

            # Create parcel record
            parcel = Parcel(
                client_code=client.code,
                tracking=row.tracking or "",
                status=ParcelStatus.CHINA_WAREHOUSE,
                weight_kg=0,
                amount_usd=0,
                amount_som=0,
                date_china=datetime.now(),
                date_bishkek=None,
                date_delivered=None,
            )
            await sheets_service.create_parcel(parcel)
        else:
            not_found_codes.append(row.client_code)

    # Send notifications (Story 2.5)
    notification_result = await broadcast(
        bot=bot,
        clients=clients_to_notify,
        message_template=(
            "📦 <b>Посылка на складе в Китае</b>\n\n"
            "Ваш код: {code}\n"
            "Скоро отправим в Бишкек!"
        ),
    )

    # Build report (AC 2.5.3)
    report_lines = [
        f"✅ <b>Обработка 'Склад Китай' завершена</b>\n",
        f"📊 Всего строк: {len(result.rows)}",
        f"✅ Уведомлено: {notification_result.success_count}",
    ]

    if not_found_codes:
        report_lines.append(f"❌ Не найдено: {len(not_found_codes)}")
        # Show first few not found codes
        codes_preview = ", ".join(not_found_codes[:10])
        if len(not_found_codes) > 10:
            codes_preview += f" и ещё {len(not_found_codes) - 10}"
        report_lines.append(f"   Коды: {codes_preview}")

    if notification_result.failed_list:
        report_lines.append(f"⚠️ Ошибки отправки: {notification_result.failed_count}")

    if result.invalid_count > 0:
        report_lines.append(f"⚠️ Некорректных строк: {result.invalid_count}")

    await status_msg.edit_text("\n".join(report_lines), parse_mode="HTML")


# ============== Bishkek Arrival Processing (Epic 3) ==============

async def process_bishkek_excel(
    message: Message,
    bot: Bot,
    result: ExcelParseResult,
    status_msg: Message,
):
    """Process Bishkek arrival Excel file"""
    # Get current rate from DB
    usd_rate = await get_current_rate()

    await status_msg.edit_text(
        f"🏠 Обработка 'Прибыло Бишкек'...\n"
        f"Найдено строк: {len(result.rows)}\n"
        f"Курс: {usd_rate} сом/$"
    )

    # Match codes and calculate payments (Story 3.2)
    clients_to_notify = []
    not_found_codes = []
    notifications_data = []  # (client, amount_som, tracking)

    for row in result.valid_rows:
        client = await sheets_service.get_client_by_code(row.client_code)
        if client:
            # Calculate payment (Story 3.2)
            weight = row.weight_kg or 0
            amount_usd = weight * config.usd_per_kg
            amount_som = amount_usd * usd_rate

            # Update parcel status
            if row.tracking:
                await sheets_service.update_parcel_status(
                    client_code=client.code,
                    tracking=row.tracking,
                    new_status=ParcelStatus.BISHKEK_ARRIVED,
                    weight_kg=weight,
                    amount_usd=amount_usd,
                    amount_som=amount_som,
                    date_bishkek=datetime.now(),
                )
            else:
                # Create new parcel if no tracking
                parcel = Parcel(
                    client_code=client.code,
                    tracking=row.tracking or "",
                    status=ParcelStatus.BISHKEK_ARRIVED,
                    weight_kg=weight,
                    amount_usd=amount_usd,
                    amount_som=amount_som,
                    date_china=None,
                    date_bishkek=datetime.now(),
                    date_delivered=None,
                )
                await sheets_service.create_parcel(parcel)

            clients_to_notify.append(client)
            notifications_data.append((client, amount_som, row.tracking, weight))
        else:
            not_found_codes.append(row.client_code)

    # Send notifications with payment info and QR codes (Story 3.3)
    success_count = 0
    failed_count = 0
    qr_generated_count = 0

    for client, amount_som, tracking, weight in notifications_data:
        # Skip clients without chat_id (imported without Telegram)
        if not client.chat_id or client.chat_id == 0:
            logger.info(f"Skipping {client.code} - no chat_id")
            continue

        qr_data = None
        qr_image_url = None
        payment_result = None

        # Generate QR code payment if payment service is configured
        if payment_service.is_configured() and amount_som > 0:
            payment_request = PaymentRequest(
                order_id="",  # Will be auto-generated
                client_code=client.code,
                amount_som=amount_som,
                description=f"Доставка {client.code} ({weight:.2f}кг)" + (f" [{tracking}]" if tracking else ""),
                chat_id=client.chat_id,
            )

            payment_result = await payment_service.create_payment(payment_request)

            if payment_result.success:
                qr_data = payment_result.qr_data
                qr_image_url = payment_result.qr_image_url
                qr_generated_count += 1

                # Save payment to database
                if config.database_url:
                    await db_service.create_payment(
                        payment_id=payment_result.invoice_id or payment_result.order_id,
                        client_code=client.code,
                        chat_id=client.chat_id,
                        amount_som=amount_som,
                        description=f"Доставка ({weight:.2f}кг)",
                        tracking=tracking,
                        qr_data=qr_data,
                    )
                logger.info(f"QR payment created for {client.code}: {payment_result.invoice_id}")
            else:
                logger.warning(f"Failed to create QR for {client.code}: {payment_result.error}")

        # Send notification with or without QR
        invoice_id = payment_result.invoice_id if payment_result and payment_result.success else None
        success, message_id = await send_payment_notification(
            bot=bot,
            client=client,
            amount_som=amount_som,
            tracking=tracking,
            weight_kg=weight,
            qr_data=qr_data,
            qr_image_url=qr_image_url,
            invoice_id=invoice_id,
        )

        if success:
            success_count += 1
            # Update payment record with message_id for later deletion
            if payment_result and payment_result.success and message_id and config.database_url:
                await db_service.update_payment_message_id(payment_result.invoice_id or payment_result.order_id, message_id)
        else:
            failed_count += 1

    # Build report
    report_lines = [
        f"✅ <b>Обработка 'Прибыло Бишкек' завершена</b>\n",
        f"📊 Всего строк: {len(result.rows)}",
        f"✅ Уведомлено: {success_count}",
    ]

    if qr_generated_count > 0:
        report_lines.append(f"💳 QR для оплаты: {qr_generated_count}")

    if not_found_codes:
        report_lines.append(f"❌ Не найдено: {len(not_found_codes)}")
        codes_preview = ", ".join(not_found_codes[:10])
        if len(not_found_codes) > 10:
            codes_preview += f" и ещё {len(not_found_codes) - 10}"
        report_lines.append(f"   Коды: {codes_preview}")

    if failed_count > 0:
        report_lines.append(f"⚠️ Ошибки отправки: {failed_count}")

    await status_msg.edit_text("\n".join(report_lines), parse_mode="HTML")


# ============== Non-Admin File Handler (AC 2.2.2) ==============

@excel_router.message(F.document)
async def handle_non_admin_file(message: Message):
    """Ignore files from non-admins (silent - no response per AC 2.2.2)"""
    # File is ignored for non-admins
    pass
