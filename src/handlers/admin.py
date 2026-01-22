"""
Tulpar Express - Admin Handlers
Admin-only commands with button-based UI (Epic 5)
"""
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.filters import IsAdmin
from src.services.sheets import sheets_service
from src.services.database import db_service
from src.models import ParcelStatus
from src.keyboards import (
    get_admin_menu,
    get_search_type_keyboard,
    get_excel_type_keyboard,
    get_table_filter_keyboard,
    get_table_mode_keyboard,
    get_clients_table_keyboard,
    get_client_detail_keyboard,
    get_autopost_menu,
)
from src.config import config

# Check if autopost is available
try:
    from src.autopost.config import settings as autopost_settings
    AUTOPOST_AVAILABLE = True
except ImportError:
    AUTOPOST_AVAILABLE = False
    autopost_settings = None

admin_router = Router(name="admin")

# Pagination constant
CLIENTS_PER_PAGE = 8


class AdminStates(StatesGroup):
    """FSM states for admin operations"""
    waiting_search_query = State()
    waiting_excel_file = State()
    waiting_new_rate = State()


# ============== Admin Menu (on /start for admins) ==============

@admin_router.message(F.text == "/admin", IsAdmin())
async def cmd_admin(message: Message):
    """Show admin menu"""
    await message.answer(
        "👨‍💼 <b>Панель администратора</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_admin_menu()
    )


# ============== Button: Статистика ==============

@admin_router.message(F.text == "📊 Статистика", IsAdmin())
async def btn_stats(message: Message):
    """Show statistics"""
    stats = await sheets_service.get_statistics()

    status_lines = []
    for status, count in stats.get("status_counts", {}).items():
        # Переводим статус на русский через enum
        try:
            display_name = ParcelStatus(status).display_name
        except ValueError:
            display_name = status
        status_lines.append(f"  • {display_name}: {count}")

    status_text = "\n".join(status_lines) if status_lines else "  Нет данных"

    await message.answer(
        f"📊 <b>Статистика Tulpar Express</b>\n\n"
        f"👥 Клиентов: {stats['clients_count']}\n"
        f"📦 Посылок: {stats['parcels_count']}\n\n"
        f"<b>По статусам:</b>\n{status_text}",
        parse_mode="HTML"
    )


# ============== Button: Курс ==============

@admin_router.message(F.text == "💱 Курс", IsAdmin())
async def btn_rate(message: Message):
    """Show current USD rate"""
    if config.database_url:
        rate = await db_service.get_usd_rate()
    else:
        rate = 89.5  # Default fallback

    await message.answer(
        f"💱 <b>Курс валют</b>\n\n"
        f"Текущий курс: <b>1 USD = {rate} сом</b>\n"
        f"Цена за кг: <b>$3.50</b>\n\n"
        f"Для изменения курса:\n"
        f"/setrate НОВЫЙ_КУРС\n"
        f"Пример: /setrate 92.5",
        parse_mode="HTML"
    )


@admin_router.message(F.text.startswith("/setrate"), IsAdmin())
async def cmd_setrate(message: Message):
    """Set new USD to SOM rate"""
    parts = message.text.split()

    if len(parts) < 2:
        if config.database_url:
            rate = await db_service.get_usd_rate()
        else:
            rate = 89.5

        await message.answer(
            f"💱 Текущий курс: <b>{rate} сом</b>\n\n"
            f"Использование: /setrate КУРС\n"
            f"Пример: /setrate 92.5",
            parse_mode="HTML"
        )
        return

    try:
        new_rate = float(parts[1].replace(",", "."))
        if new_rate <= 0 or new_rate > 1000:
            raise ValueError("Invalid rate")
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число, например: 92.5")
        return

    if config.database_url:
        old_rate = await db_service.get_usd_rate()
        await db_service.set_usd_rate(new_rate)

        await message.answer(
            f"✅ <b>Курс обновлён</b>\n\n"
            f"Было: {old_rate} сом\n"
            f"Стало: <b>{new_rate} сом</b>\n\n"
            f"Расчёт: {3.5} × {new_rate} = <b>{3.5 * new_rate:.0f} сом/кг</b>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "⚠️ База данных не подключена.\n"
            "Курс можно изменить только в коде (excel.py)."
        )


# ============== Button: Таблица ==============

@admin_router.message(F.text == "📋 Таблица", IsAdmin())
async def btn_table(message: Message):
    """Show clients table directly"""
    if not config.database_url:
        await message.answer(
            "❌ База данных не настроена.\n"
            "Таблица клиентов доступна только с PostgreSQL.",
            parse_mode="HTML"
        )
        return

    # Show clients table directly
    total_count = await db_service.get_clients_count()
    total_pages = max(1, (total_count + CLIENTS_PER_PAGE - 1) // CLIENTS_PER_PAGE)

    clients = await db_service.get_clients_with_parcel_counts(
        offset=0,
        limit=CLIENTS_PER_PAGE,
    )

    if not clients:
        await message.answer(
            "👥 <b>Клиенты</b>\n\nКлиентов пока нет.",
            parse_mode="HTML",
            reply_markup=get_table_mode_keyboard()
        )
        return

    # Build table text
    lines = [
        "👥 <b>Таблица клиентов</b>",
        f"Всего: {total_count} | Стр. 1/{total_pages}\n",
        "🔴 = есть активные заказы",
        "",
    ]

    for c in clients:
        active = c.get("active_count", 0)
        total = c.get("parcel_count", 0)
        icon = "🔴" if active > 0 else "✅"
        name = c.get("full_name", "")[:18]
        lines.append(f"{icon} <b>{c['code']}</b> — {name} ({active}/{total})")

    lines.append("\n<i>Нажмите на клиента для деталей</i>")

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_clients_table_keyboard(
            page=0,
            total_pages=total_pages,
            clients=clients,
        )
    )


@admin_router.callback_query(F.data == "table_mode:clients", IsAdmin())
async def callback_table_clients(callback: CallbackQuery):
    """Switch to clients table view"""
    await show_clients_table(callback, page=0)


@admin_router.callback_query(F.data == "table_mode:parcels", IsAdmin())
async def callback_table_parcels(callback: CallbackQuery):
    """Switch to parcels table view"""
    await callback.message.edit_text(
        "📦 <b>Таблица посылок</b>\n\n"
        "Выберите фильтр:",
        parse_mode="HTML",
        reply_markup=get_table_filter_keyboard()
    )
    await callback.answer()


# ============== Clients Table View ==============

async def show_clients_table(callback: CallbackQuery, page: int = 0):
    """Display paginated clients table"""
    if not config.database_url:
        await callback.message.edit_text(
            "❌ База данных не настроена.\n"
            "Таблица клиентов доступна только с PostgreSQL.",
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Get clients with stats
    total_count = await db_service.get_clients_count()
    total_pages = max(1, (total_count + CLIENTS_PER_PAGE - 1) // CLIENTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    clients = await db_service.get_clients_with_parcel_counts(
        offset=page * CLIENTS_PER_PAGE,
        limit=CLIENTS_PER_PAGE,
    )

    if not clients:
        await callback.message.edit_text(
            "👥 <b>Клиенты</b>\n\n"
            "Клиентов пока нет.",
            parse_mode="HTML",
            reply_markup=get_table_mode_keyboard()
        )
        await callback.answer()
        return

    # Build table text
    lines = [
        "👥 <b>Таблица клиентов</b>",
        f"Всего: {total_count} | Стр. {page + 1}/{total_pages}\n",
        "🔴 = есть активные заказы",
        "",
    ]

    for c in clients:
        active = c.get("active_count", 0)
        total = c.get("parcel_count", 0)
        icon = "🔴" if active > 0 else "✅"
        name = c.get("full_name", "")[:18]
        lines.append(f"{icon} <b>{c['code']}</b> — {name} ({active}/{total})")

    lines.append("\n<i>Нажмите на клиента для деталей</i>")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_clients_table_keyboard(
            page=page,
            total_pages=total_pages,
            clients=clients,
        )
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("clients_page:"), IsAdmin())
async def callback_clients_page(callback: CallbackQuery):
    """Handle clients table pagination"""
    page = int(callback.data.split(":")[1])
    await show_clients_table(callback, page=page)


@admin_router.callback_query(F.data.startswith("client_view:"), IsAdmin())
async def callback_client_view(callback: CallbackQuery):
    """Show detailed client view with their parcels"""
    client_code = callback.data.split(":")[1]

    # Get client info
    client = await sheets_service.get_client_by_code(client_code)
    if not client:
        await callback.answer("Клиент не найден", show_alert=True)
        return

    # Get parcels with payment status
    if config.database_url:
        parcels = await db_service.get_client_parcels_detailed(client_code)
    else:
        parcels_raw = await sheets_service.get_parcels_by_client_code(client_code)
        parcels = [{"tracking": p.tracking, "status": p.status.value, "weight_kg": p.weight_kg,
                    "amount_som": p.amount_som, "date_bishkek": p.date_bishkek} for p in parcels_raw]

    # Build client info text
    lines = [
        f"👤 <b>{client.code}</b>",
        f"",
        f"📛 {client.full_name}",
        f"📱 {client.phone}",
        f"🆔 <code>{client.chat_id}</code>",
        f"📅 Рег: {client.reg_date.strftime('%d.%m.%Y')}",
        "",
        f"📦 <b>Заказы ({len(parcels)}):</b>",
    ]

    # Status icons mapping
    status_icons = {
        "CHINA_WAREHOUSE": "🇨🇳",
        "IN_TRANSIT": "✈️",
        "BISHKEK_ARRIVED": "🏠",
        "READY_PICKUP": "💰",
        "DELIVERED": "✅",
    }

    for p in parcels[:10]:
        status = p.get("status", "")
        icon = status_icons.get(status, "📦")
        tracking = p.get("tracking", "-")[:12]
        weight = p.get("weight_kg", 0)
        amount = p.get("amount_som", 0)
        payment_status = p.get("payment_status", "")

        # Payment indicator
        pay_icon = ""
        if payment_status == "PAID":
            pay_icon = " 💳✓"
        elif payment_status == "PENDING" and status == "BISHKEK_ARRIVED":
            pay_icon = " 💳⏳"

        amount_str = f"{amount:.0f}с" if amount > 0 else ""
        weight_str = f"{weight:.1f}кг" if weight > 0 else ""

        lines.append(f"  {icon} {tracking} {weight_str} {amount_str}{pay_icon}")

    if len(parcels) > 10:
        lines.append(f"  ... ещё {len(parcels) - 10}")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_client_detail_keyboard(client_code, parcels)
    )
    await callback.answer()


@admin_router.callback_query(F.data == "noop", IsAdmin())
async def callback_noop(callback: CallbackQuery):
    """No-op callback for pagination display"""
    await callback.answer()


@admin_router.callback_query(F.data.startswith("table:"), IsAdmin())
async def callback_table_filter(callback: CallbackQuery):
    """Handle table filter selection"""
    filter_type = callback.data.split(":")[1]

    # Get parcels based on filter
    if config.database_url:
        parcels = await db_service.get_parcels_by_status(filter_type, limit=30)
    else:
        parcels = await sheets_service.get_parcels_by_status(filter_type, limit=30)

    if not parcels:
        await callback.message.edit_text(
            f"📋 <b>Таблица посылок</b>\n\n"
            f"Фильтр: {filter_type}\n\n"
            f"Посылок не найдено.",
            parse_mode="HTML",
            reply_markup=get_table_filter_keyboard()
        )
        await callback.answer()
        return

    # Build table
    filter_names = {
        "CHINA_WAREHOUSE": "🇨🇳 На складе Китай",
        "BISHKEK_ARRIVED": "🏠 Прибыло Бишкек",
        "DELIVERED": "✅ Выданные",
        "ACTIVE": "📦 Все активные",
    }

    lines = [
        f"📋 <b>Таблица посылок</b>",
        f"Фильтр: {filter_names.get(filter_type, filter_type)}",
        f"Найдено: {len(parcels)}\n",
        "<code>",
        f"{'Код':<10} {'Трекинг':<15} {'Статус':<12} {'Сумма':>8}",
        "-" * 47,
    ]

    # Build inline buttons for active parcels
    buttons = []

    for p in parcels:
        status_short = {
            "CHINA_WAREHOUSE": "📦Китай",
            "IN_TRANSIT": "✈️В пути",
            "BISHKEK_ARRIVED": "🏠Бишкек",
            "READY_PICKUP": "💰Готов",
            "DELIVERED": "✅Выдан",
        }.get(p.status.value, p.status.value[:6])

        amount_str = f"{p.amount_som:.0f}" if p.amount_som > 0 else "-"
        tracking_short = p.tracking[:13] if len(p.tracking) > 13 else p.tracking

        lines.append(f"{p.client_code:<10} {tracking_short:<15} {status_short:<12} {amount_str:>8}")

        # Add deliver button for non-delivered
        if p.status.value != "DELIVERED" and len(buttons) < 10:
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ {p.tracking}",
                    callback_data=f"deliver:{p.tracking}"
                )
            ])

    lines.append("</code>")

    # Add filter buttons at the end
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"table:{filter_type}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🇨🇳 Китай", callback_data="table:CHINA_WAREHOUSE"),
        InlineKeyboardButton(text="🏠 Бишкек", callback_data="table:BISHKEK_ARRIVED"),
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


# ============== Button: Поиск клиента ==============

@admin_router.message(F.text == "🔍 Поиск клиента", IsAdmin())
async def btn_search(message: Message):
    """Start search - show search type options"""
    await message.answer(
        "🔍 <b>Поиск клиента</b>\n\n"
        "Как искать?",
        parse_mode="HTML",
        reply_markup=get_search_type_keyboard()
    )


@admin_router.callback_query(F.data.startswith("search_type:"), IsAdmin())
async def callback_search_type(callback: CallbackQuery, state: FSMContext):
    """Handle search type selection"""
    search_type = callback.data.split(":")[1]

    await state.update_data(search_type=search_type)
    await state.set_state(AdminStates.waiting_search_query)

    if search_type == "code":
        prompt = "Введите код клиента (TE-XXXX):"
    else:
        prompt = "Введите номер телефона:"

    await callback.message.edit_text(f"🔍 {prompt}")
    await callback.answer()


@admin_router.message(AdminStates.waiting_search_query, ~F.text.startswith("/"), IsAdmin())
async def process_search_query(message: Message, state: FSMContext):
    """Process search query (ignore commands)"""
    query = message.text.strip()
    data = await state.get_data()
    search_type = data.get("search_type", "code")

    await state.clear()

    # Perform search - try PostgreSQL first, fallback to Sheets
    client = None
    if search_type == "code" or query.upper().startswith("TE-") or query.upper().startswith("S-") or query.upper().startswith("KG-"):
        code = query.upper().strip()
        if config.database_url:
            client = await db_service.get_client_by_code(code)
        if not client:
            client = await sheets_service.get_client_by_code(code)
    else:
        if config.database_url:
            client = await db_service.get_client_by_phone(query)
        if not client:
            client = await sheets_service.get_client_by_phone(query)

    if not client:
        await message.answer(
            f"❌ Клиент не найден: {query}",
            reply_markup=get_admin_menu()
        )
        return

    # Get client's parcels - try PostgreSQL first, fallback to Sheets
    parcels = []
    if config.database_url:
        parcels = await db_service.get_parcels_by_client_code(client.code)
    if not parcels:
        parcels = await sheets_service.get_parcels_by_client_code(client.code)

    # Build parcel list and buttons
    parcel_lines = []
    buttons = []

    for p in parcels:
        status_icon = "✅" if p.status == ParcelStatus.DELIVERED else "📦"
        parcel_lines.append(f"  {status_icon} {p.tracking}: {p.status.display_name}")

        # Add deliver button for non-delivered parcels
        if p.status != ParcelStatus.DELIVERED:
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ Выдать {p.tracking}",
                    callback_data=f"deliver:{p.tracking}"
                )
            ])

    parcels_text = "\n".join(parcel_lines) if parcel_lines else "  Нет посылок"

    # Create keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    await message.answer(
        f"👤 <b>Клиент найден</b>\n\n"
        f"Код: <b>{client.code}</b>\n"
        f"ФИО: {client.full_name}\n"
        f"Телефон: {client.phone}\n"
        f"Chat ID: <code>{client.chat_id}</code>\n"
        f"Дата рег.: {client.reg_date.strftime('%d.%m.%Y')}\n\n"
        f"📦 <b>Посылки:</b>\n{parcels_text}",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============== Button: Загрузить Excel ==============

@admin_router.message(F.text == "📁 Загрузить Excel", IsAdmin())
async def btn_upload_excel(message: Message, state: FSMContext):
    """Start Excel upload - show file type options"""
    await state.set_state(AdminStates.waiting_excel_file)
    await message.answer(
        "📁 <b>Загрузка Excel</b>\n\n"
        "Выберите тип файла:",
        parse_mode="HTML",
        reply_markup=get_excel_type_keyboard()
    )


@admin_router.callback_query(F.data.startswith("excel_type:"), IsAdmin())
async def callback_excel_type(callback: CallbackQuery, state: FSMContext):
    """Handle Excel type selection"""
    excel_type = callback.data.split(":")[1]

    if excel_type == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Отменено")
        await callback.answer()
        return

    await state.update_data(excel_type=excel_type)

    type_name = "🇨🇳 Склад Китай" if excel_type == "china" else "🏠 Прибыло Бишкек"
    await callback.message.edit_text(
        f"📁 <b>{type_name}</b>\n\n"
        f"Отправьте Excel файл (.xlsx)",
        parse_mode="HTML"
    )
    await callback.answer()


# ============== Callback: Deliver Button ==============

@admin_router.callback_query(F.data.startswith("deliver:"), IsAdmin())
async def callback_deliver(callback: CallbackQuery):
    """Handle deliver button press"""
    parts = callback.data.split(":", 1)
    if len(parts) != 2 or not parts[1].strip():
        await callback.answer("❌ Некорректный запрос", show_alert=True)
        return
    tracking = parts[1].strip()[:100]  # Limit length for safety

    # Try database first, then Google Sheets
    parcel = None
    use_db = False

    if config.database_url:
        parcel = await db_service.get_parcel_by_tracking(tracking)
        if parcel:
            use_db = True

    if not parcel:
        parcel = await sheets_service.get_parcel_by_tracking(tracking)

    if not parcel:
        await callback.answer(f"Посылка не найдена: {tracking}", show_alert=True)
        return

    parcel_status = parcel.status if hasattr(parcel, 'status') else ParcelStatus(parcel.get('status', 'UNKNOWN'))
    parcel_client_code = parcel.client_code if hasattr(parcel, 'client_code') else parcel.get('client_code', '')

    if parcel_status == ParcelStatus.DELIVERED:
        await callback.answer("Уже выдана", show_alert=True)
        return

    # Update in appropriate service
    if use_db:
        success = await db_service.update_parcel_status(
            client_code=parcel_client_code,
            tracking=tracking,
            new_status=ParcelStatus.DELIVERED,
            date_delivered=datetime.now(),
        )
    else:
        success = await sheets_service.update_parcel_status(
            client_code=parcel_client_code,
            tracking=tracking,
            new_status=ParcelStatus.DELIVERED,
            date_delivered=datetime.now(),
        )

    if success:
        await callback.answer(f"✅ {tracking} выдана!")

        # Get client to notify
        client = await sheets_service.get_client_by_code(parcel_client_code)

        # Notify client about delivery (FR9)
        if client:
            try:
                await callback.bot.send_message(
                    client.chat_id,
                    f"✅ <b>Посылка выдана!</b>\n\n"
                    f"Трекинг: {tracking}\n"
                    f"Спасибо что пользуетесь Tulpar Express!",
                    parse_mode="HTML"
                )
            except Exception:
                pass  # Client may have blocked the bot

        # Update message to show delivered status
        await callback.message.reply(
            f"✅ Посылка <b>{tracking}</b> отмечена как выданная\n"
            f"Клиент: {parcel_client_code}" + (" (уведомлён)" if client else ""),
            parse_mode="HTML"
        )
        # Remove buttons from original message
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    else:
        await callback.answer("Ошибка при обновлении", show_alert=True)


# ============== Legacy Commands ==============

@admin_router.message(F.text == "/stats", IsAdmin())
async def cmd_stats(message: Message):
    """Legacy /stats command"""
    await btn_stats(message)


@admin_router.message(F.text.startswith("/search"), IsAdmin())
async def cmd_search(message: Message, state: FSMContext):
    """Legacy /search command with argument"""
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await btn_search(message)
        return

    # Direct search with argument
    query = parts[1].strip()

    if query.upper().startswith("TE-"):
        client = await sheets_service.get_client_by_code(query.upper())
    else:
        client = await sheets_service.get_client_by_phone(query)

    if not client:
        await message.answer(f"❌ Клиент не найден: {query}")
        return

    # Get parcels and show result (same as process_search_query)
    parcels = await sheets_service.get_parcels_by_client_code(client.code)

    parcel_lines = []
    buttons = []

    for p in parcels:
        status_icon = "✅" if p.status == ParcelStatus.DELIVERED else "📦"
        parcel_lines.append(f"  {status_icon} {p.tracking}: {p.status.display_name}")

        if p.status != ParcelStatus.DELIVERED:
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ Выдать {p.tracking}",
                    callback_data=f"deliver:{p.tracking}"
                )
            ])

    parcels_text = "\n".join(parcel_lines) if parcel_lines else "  Нет посылок"
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    await message.answer(
        f"👤 <b>Клиент найден</b>\n\n"
        f"Код: <b>{client.code}</b>\n"
        f"ФИО: {client.full_name}\n"
        f"Телефон: {client.phone}\n"
        f"Chat ID: <code>{client.chat_id}</code>\n"
        f"Дата рег.: {client.reg_date.strftime('%d.%m.%Y')}\n\n"
        f"📦 <b>Посылки:</b>\n{parcels_text}",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@admin_router.message(F.text.startswith("/delivered"), IsAdmin())
async def cmd_delivered(message: Message):
    """Legacy /delivered command"""
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer(
            "Использование:\n"
            "/delivered TRACKING — или используйте кнопки в поиске клиента"
        )
        return

    tracking = parts[1].strip()
    parcel = await sheets_service.get_parcel_by_tracking(tracking)

    if not parcel:
        await message.answer(f"❌ Посылка не найдена: {tracking}")
        return

    if parcel.status == ParcelStatus.DELIVERED:
        await message.answer(f"ℹ️ Посылка {tracking} уже выдана")
        return

    success = await sheets_service.update_parcel_status(
        client_code=parcel.client_code,
        tracking=tracking,
        new_status=ParcelStatus.DELIVERED,
        date_delivered=datetime.now(),
    )

    if success:
        await message.answer(
            f"✅ Посылка <b>{tracking}</b> отмечена как выданная\n"
            f"Клиент: {parcel.client_code}",
            parse_mode="HTML"
        )
    else:
        await message.answer(f"❌ Ошибка при обновлении: {tracking}")


# ============== Autopost Controls ==============

@admin_router.message(F.text == "📢 Канал", IsAdmin())
async def btn_autopost(message: Message):
    """Show autopost control menu"""
    if not AUTOPOST_AVAILABLE:
        await message.answer(
            "❌ Модуль автопостинга не установлен.",
            parse_mode="HTML"
        )
        return

    status = "✅ Включён" if autopost_settings.enabled else "⚪ Выключен"
    channel = autopost_settings.telegram_channel_id or "не указан"
    time = autopost_settings.posting_time

    await message.answer(
        f"📢 <b>Автопостинг в канал</b>\n\n"
        f"Статус: {status}\n"
        f"Канал: {channel}\n"
        f"Время: {time}\n\n"
        f"Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_autopost_menu()
    )


@admin_router.callback_query(F.data == "ap:run", IsAdmin())
async def callback_autopost_run(callback: CallbackQuery):
    """Manually run the autopost pipeline"""
    if not AUTOPOST_AVAILABLE or not autopost_settings.is_configured():
        await callback.answer(
            "Автопостинг не настроен. Проверьте переменные AUTOPOST_*",
            show_alert=True
        )
        return

    await callback.answer("⏳ Запускаю...")

    if callback.message:
        await callback.message.edit_text(
            "🚀 <b>Запускаю публикацию...</b>\n\n"
            "Это может занять несколько минут.\n"
            "Вы получите уведомление о результате.",
            parse_mode="HTML"
        )

    try:
        # Import and run pipeline
        from src.autopost.db.session import get_session_maker, get_engine, init_db
        from src.autopost.db.models import ProductDB, PostDB, CurrencyRateDB, SettingsDB  # noqa
        from src.autopost.pipeline.daily_pipeline import DailyPipeline
        from src.autopost.services.pinduoduo import PinduoduoService
        from src.autopost.services.currency import CurrencyService
        from src.autopost.services.openai_service import OpenAIService
        from src.autopost.services.image_service import ImageService
        from src.autopost.services.telegram_service import TelegramService
        from src.autopost.services.notification_service import NotificationService
        from src.autopost.core.product_filter import ProductFilter
        from src.autopost.db.repositories import CurrencyRepository
        import httpx

        # Ensure tables exist
        await init_db()

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            async with get_session_maker()() as session:
                currency_repo = CurrencyRepository(session)

                pinduoduo = PinduoduoService(client=http_client)
                currency = CurrencyService(client=http_client, repository=currency_repo)
                text_service = OpenAIService(client=http_client)
                image = ImageService(client=http_client)

                telegram = TelegramService(
                    bot_token=autopost_settings.telegram_bot_token,
                    channel_id=autopost_settings.telegram_channel_id,
                    owner_ids=autopost_settings.owner_ids_list,
                )

                notification = NotificationService(telegram_service=telegram)

                product_filter = ProductFilter(
                    min_discount=autopost_settings.min_discount,
                    min_rating=autopost_settings.min_rating,
                    top_limit=autopost_settings.top_products_limit,
                )

                pipeline = DailyPipeline(
                    pinduoduo_service=pinduoduo,
                    currency_service=currency,
                    taobao_service=None,
                    text_service=text_service,
                    image_service=image,
                    telegram_service=telegram,
                    instagram_service=None,
                    notification_service=notification,
                    session=session,
                    product_filter=product_filter,
                )

                result = await pipeline.run()

                if result.success:
                    if callback.message:
                        await callback.message.answer(
                            f"✅ <b>Публикация завершена!</b>\n\n"
                            f"Товаров: {result.products_count}\n"
                            f"Telegram ID: {result.telegram_message_id}\n"
                            f"Время: {result.total_duration_ms}ms",
                            parse_mode="HTML",
                            reply_markup=get_autopost_menu()
                        )
                else:
                    if callback.message:
                        await callback.message.answer(
                            f"❌ <b>Ошибка публикации</b>\n\n"
                            f"Этап: {result.failed_stage}\n"
                            f"Ошибка: <code>{str(result.error)[:200]}</code>",
                            parse_mode="HTML",
                            reply_markup=get_autopost_menu()
                        )

    except Exception as e:
        if callback.message:
            await callback.message.answer(
                f"❌ <b>Ошибка:</b>\n<code>{str(e)[:300]}</code>",
                parse_mode="HTML",
                reply_markup=get_autopost_menu()
            )


@admin_router.callback_query(F.data == "ap:posts", IsAdmin())
async def callback_autopost_posts(callback: CallbackQuery):
    """Show list of published posts"""
    if not AUTOPOST_AVAILABLE:
        await callback.answer("Модуль автопостинга недоступен", show_alert=True)
        return

    try:
        from src.autopost.db.session import get_session_maker
        from src.autopost.db.repositories.post_repository import PostRepository

        async with get_session_maker()() as session:
            repo = PostRepository(session)
            posts, total = await repo.get_posts(page=1, page_size=10)

            if not posts:
                await callback.message.edit_text(
                    "📋 <b>История публикаций</b>\n\n"
                    "Публикаций пока нет.",
                    parse_mode="HTML",
                    reply_markup=get_autopost_menu()
                )
                await callback.answer()
                return

            lines = [
                "📋 <b>История публикаций</b>",
                f"Всего: {total}\n",
            ]

            status_icons = {
                "published": "✅",
                "telegram_only": "📱",
                "instagram_failed": "⚠️",
                "pending": "⏳",
            }

            for post in posts[:10]:
                icon = status_icons.get(post.status, "📝")
                date = post.created_at.strftime("%d.%m %H:%M") if post.created_at else "-"
                products = len(post.products_json) if post.products_json else 0
                lines.append(f"{icon} {date} — {products} товаров")

            await callback.message.edit_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=get_autopost_menu()
            )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка: <code>{str(e)[:200]}</code>",
            parse_mode="HTML",
            reply_markup=get_autopost_menu()
        )

    await callback.answer()


@admin_router.callback_query(F.data == "ap:status", IsAdmin())
async def callback_autopost_status(callback: CallbackQuery):
    """Show autopost system status"""
    if not AUTOPOST_AVAILABLE:
        await callback.answer("Модуль автопостинга недоступен", show_alert=True)
        return

    await callback.answer("⏳ Проверяю...")

    try:
        from src.autopost.db.session import get_engine
        from sqlalchemy import text

        # Check database
        db_status = "❌"
        try:
            async with get_engine().begin() as conn:
                await conn.execute(text("SELECT 1"))
            db_status = "✅"
        except Exception:
            pass

        # Check config
        missing = autopost_settings.validate_required()
        config_status = "✅" if not missing else f"❌ ({', '.join(missing)})"

        lines = [
            "📊 <b>Статус автопостинга</b>\n",
            f"Модуль: {'✅ Включён' if autopost_settings.enabled else '⚪ Выключен'}",
            f"База данных: {db_status}",
            f"Конфигурация: {config_status}",
            f"\n<b>Настройки:</b>",
            f"Канал: {autopost_settings.telegram_channel_id or 'не указан'}",
            f"Время: {autopost_settings.posting_time}",
            f"Часовой пояс: {autopost_settings.timezone}",
            f"Макс. товаров: {autopost_settings.max_products}",
        ]

        await callback.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=get_autopost_menu()
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка: <code>{str(e)[:200]}</code>",
            parse_mode="HTML",
            reply_markup=get_autopost_menu()
        )


# ============== Access Denied for Non-Admins ==============

@admin_router.message(F.text.in_({"📊 Статистика", "🔍 Поиск клиента", "📁 Загрузить Excel", "💱 Курс", "📋 Таблица", "📢 Канал"}))
async def btn_admin_denied(message: Message):
    """Deny access to admin buttons for non-admins"""
    await message.answer("⛔ Эта функция доступна только администраторам.")
