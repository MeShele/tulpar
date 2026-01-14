"""
Tulpar Express - Keyboards
Reply and Inline keyboards for bot UI
"""
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


# ============== Client Keyboards ==============

def get_client_menu() -> ReplyKeyboardMarkup:
    """Main menu for registered clients"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мой код"), KeyboardButton(text="📦 Мои посылки")],
            [KeyboardButton(text="🔑 Забыл код")],
        ],
        resize_keyboard=True,
    )


def get_registration_cancel() -> ReplyKeyboardMarkup:
    """Cancel button during registration"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ============== Admin Keyboards ==============

def get_admin_menu() -> ReplyKeyboardMarkup:
    """Main menu for admin"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🔍 Поиск клиента")],
            [KeyboardButton(text="📋 Таблица"), KeyboardButton(text="💱 Курс")],
            [KeyboardButton(text="📁 Загрузить Excel")],
        ],
        resize_keyboard=True,
    )


def get_table_filter_keyboard() -> InlineKeyboardMarkup:
    """Filter buttons for dynamic table"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇨🇳 Китай", callback_data="table:CHINA_WAREHOUSE"),
                InlineKeyboardButton(text="🏠 Бишкек", callback_data="table:BISHKEK_ARRIVED"),
            ],
            [
                InlineKeyboardButton(text="✅ Выданные", callback_data="table:DELIVERED"),
                InlineKeyboardButton(text="📦 Все активные", callback_data="table:ACTIVE"),
            ],
        ]
    )


def get_search_type_keyboard() -> InlineKeyboardMarkup:
    """Choose search type"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="По коду (TE-XXXX)", callback_data="search_type:code"),
                InlineKeyboardButton(text="По телефону", callback_data="search_type:phone"),
            ],
        ]
    )


def get_excel_type_keyboard() -> InlineKeyboardMarkup:
    """Choose Excel file type"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🇨🇳 Склад Китай", callback_data="excel_type:china")],
            [InlineKeyboardButton(text="🏠 Прибыло Бишкек", callback_data="excel_type:bishkek")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="excel_type:cancel")],
        ]
    )


def get_parcel_actions(tracking: str) -> InlineKeyboardMarkup:
    """Action buttons for a parcel"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Выдать {tracking}", callback_data=f"deliver:{tracking}")],
        ]
    )


def get_payment_keyboard(client_code: str, amount_som: float) -> InlineKeyboardMarkup:
    """Payment button for client parcels"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"💳 Оплатить {amount_som:.0f} сом",
                callback_data=f"pay:{client_code}:{amount_som:.0f}"
            )],
        ]
    )


def get_payment_status_keyboard(invoice_id: str) -> InlineKeyboardMarkup:
    """Check payment status button"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🔄 Проверить оплату",
                callback_data=f"check_pay:{invoice_id}"
            )],
            [InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=f"cancel_pay:{invoice_id}"
            )],
        ]
    )


def get_table_mode_keyboard() -> InlineKeyboardMarkup:
    """Choose between clients view and parcels view"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 По клиентам", callback_data="table_mode:clients"),
                InlineKeyboardButton(text="📦 По посылкам", callback_data="table_mode:parcels"),
            ],
        ]
    )


def get_clients_table_keyboard(
    page: int = 0,
    total_pages: int = 1,
    clients: list = None,
) -> InlineKeyboardMarkup:
    """
    Keyboard for clients table with pagination and client buttons

    Args:
        page: Current page (0-indexed)
        total_pages: Total number of pages
        clients: List of client dicts with 'code' field
    """
    buttons = []

    # Add client buttons (max 8 per page)
    if clients:
        for client in clients[:8]:
            code = client.get("code", "")
            active = client.get("active_count", 0)
            icon = "🔴" if active > 0 else "✅"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{icon} {code} — {client.get('full_name', '')[:20]}",
                    callback_data=f"client_view:{code}"
                )
            ])

    # Pagination row
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"clients_page:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"clients_page:{page + 1}"))
    buttons.append(nav_buttons)

    # Actions row
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"clients_page:{page}"),
        InlineKeyboardButton(text="📦 К посылкам", callback_data="table_mode:parcels"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_client_detail_keyboard(client_code: str, parcels: list = None) -> InlineKeyboardMarkup:
    """
    Keyboard for client detail view with parcel actions

    Args:
        client_code: Client code
        parcels: List of parcel dicts
    """
    buttons = []

    # Add parcel action buttons (deliver non-delivered)
    if parcels:
        for p in parcels[:5]:
            if p.get("status") != "DELIVERED":
                tracking = p.get("tracking", "")[:15]
                buttons.append([
                    InlineKeyboardButton(
                        text=f"✅ Выдать {tracking}",
                        callback_data=f"deliver:{p.get('tracking', '')}"
                    )
                ])

    # Navigation buttons
    buttons.append([
        InlineKeyboardButton(text="◀️ К списку", callback_data="clients_page:0"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"client_view:{client_code}"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


