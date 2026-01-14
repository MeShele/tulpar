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


