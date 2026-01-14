"""
Tulpar Express - Client Handlers
Registration flow with FSM and button-based UI
"""
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove

from src.services.sheets import sheets_service
from src.services.database import db_service
from src.models import Client
from src.keyboards import get_client_menu, get_registration_cancel, get_admin_menu
from src.config import config


# Helper to get the right service
async def get_client_by_chat_id(chat_id: int):
    """Get client - try PostgreSQL first, fallback to Sheets"""
    if config.database_url:
        return await db_service.get_client_by_chat_id(chat_id)
    return await sheets_service.get_client_by_chat_id(chat_id)


async def get_parcels_by_code(code: str):
    """Get parcels - try PostgreSQL first, fallback to Sheets"""
    if config.database_url:
        return await db_service.get_parcels_by_client_code(code)
    return await sheets_service.get_parcels_by_client_code(code)


async def create_new_client(client: Client):
    """Create client - write to both if PostgreSQL available"""
    if config.database_url:
        await db_service.create_client(client)
    await sheets_service.create_client(client)  # Always write to Sheets as backup


async def generate_code():
    """Generate code - use PostgreSQL if available"""
    if config.database_url:
        return await db_service.generate_client_code()
    return await sheets_service.generate_client_code()


async def get_client_by_phone(phone: str):
    """Get client by phone - try PostgreSQL first, fallback to Sheets"""
    if config.database_url:
        return await db_service.get_client_by_phone(phone)
    return await sheets_service.get_client_by_phone(phone)

client_router = Router(name="client")


class RegistrationStates(StatesGroup):
    """FSM states for client registration"""
    waiting_name = State()
    waiting_phone = State()


class RecoveryStates(StatesGroup):
    """FSM states for code recovery"""
    waiting_phone = State()


# ============== /start Command ==============

@client_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command - begin registration or show menu"""
    chat_id = message.from_user.id
    is_admin = chat_id in config.admin_chat_ids

    # Check if already registered
    existing_client = await get_client_by_chat_id(chat_id)

    if existing_client:
        # Already registered - show appropriate menu
        keyboard = get_admin_menu() if is_admin else get_client_menu()
        role_text = " (Администратор)" if is_admin else ""

        await message.answer(
            f"👋 С возвращением, {existing_client.full_name}!{role_text}\n\n"
            f"Ваш код: <b>{existing_client.code}</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # Admin not registered - show admin menu anyway
    if is_admin:
        await message.answer(
            "👨‍💼 <b>Панель администратора</b>\n\n"
            "Вы можете управлять ботом, но для тестирования "
            "функций клиента рекомендуется зарегистрироваться.",
            parse_mode="HTML",
            reply_markup=get_admin_menu()
        )
        return

    # New user - start registration
    await state.set_state(RegistrationStates.waiting_name)
    await message.answer(
        "👋 Добро пожаловать в <b>Tulpar Express</b>!\n\n"
        "Для регистрации введите ваше ФИО:",
        parse_mode="HTML",
        reply_markup=get_registration_cancel()
    )


# ============== Registration: Cancel ==============

@client_router.message(F.text == "❌ Отмена")
async def cancel_registration(message: Message, state: FSMContext):
    """Cancel registration process"""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer(
            "❌ Регистрация отменена.\n"
            "Отправьте /start чтобы начать заново.",
            reply_markup=ReplyKeyboardRemove()
        )


# ============== Registration: Name Input ==============

@client_router.message(RegistrationStates.waiting_name)
async def process_name(message: Message, state: FSMContext):
    """Process full name input"""
    name = message.text.strip() if message.text else ""

    # Validation
    if not name or len(name) < 2:
        await message.answer("❌ Пожалуйста, введите ваше ФИО (минимум 2 символа)")
        return

    # Save name and move to phone state
    await state.update_data(full_name=name)
    await state.set_state(RegistrationStates.waiting_phone)
    await message.answer(
        "📱 Отлично! Теперь введите номер телефона:",
        reply_markup=get_registration_cancel()
    )


# ============== Registration: Phone Input ==============

@client_router.message(RegistrationStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    """Process phone number input and complete registration"""
    phone_raw = message.text.strip() if message.text else ""

    # Extract only digits
    phone_digits = "".join(filter(str.isdigit, phone_raw))

    # Validation
    if len(phone_digits) < 9:
        await message.answer("❌ Введите корректный номер телефона (минимум 9 цифр)")
        return

    # Get saved data
    data = await state.get_data()
    full_name = data.get("full_name", "")

    # Generate unique code
    code = await generate_code()

    # Create client record
    client = Client(
        chat_id=message.from_user.id,
        code=code,
        full_name=full_name,
        phone=phone_digits,
        reg_date=datetime.now(),
    )

    # Save client (PostgreSQL + Sheets backup)
    await create_new_client(client)

    # Clear FSM state
    await state.clear()

    # Send success message with menu
    await message.answer(
        f"🎉 <b>Регистрация завершена!</b>\n\n"
        f"Ваш персональный код: <b>{code}</b>\n\n"
        f"Используйте этот код при отправке посылок.",
        parse_mode="HTML",
        reply_markup=get_client_menu()
    )


# ============== Button: Мой код ==============

@client_router.message(F.text == "📋 Мой код")
async def btn_my_code(message: Message):
    """Show user's code"""
    chat_id = message.from_user.id
    client = await get_client_by_chat_id(chat_id)

    if client:
        await message.answer(
            f"📋 Ваш код: <b>{client.code}</b>\n\n"
            f"Используйте его при отправке посылок из Китая.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ Вы не зарегистрированы.\n"
            "Нажмите /start для регистрации."
        )


# ============== Button: Мои посылки ==============

@client_router.message(F.text == "📦 Мои посылки")
async def btn_my_parcels(message: Message):
    """Show user's parcels status"""
    chat_id = message.from_user.id
    client = await get_client_by_chat_id(chat_id)

    if not client:
        await message.answer(
            "❌ Вы не зарегистрированы.\n"
            "Нажмите /start для регистрации."
        )
        return

    parcels = await get_parcels_by_code(client.code)

    if not parcels:
        await message.answer(
            f"📦 У вас пока нет посылок.\n\n"
            f"Ваш код для отправки: <b>{client.code}</b>",
            parse_mode="HTML"
        )
        return

    # Build status message
    lines = [f"📦 <b>Ваши посылки ({len(parcels)}):</b>\n"]

    for p in parcels:
        status_icon = "✅" if p.status.value == "DELIVERED" else "📦"
        amount_text = f" — <b>{p.amount_som:.0f} сом</b>" if p.amount_som > 0 else ""
        lines.append(f"{status_icon} {p.tracking}: {p.status.display_name}{amount_text}")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ============== Button: Забыл код (FR22-25) ==============

@client_router.message(F.text == "🔑 Забыл код")
async def btn_forgot_code(message: Message, state: FSMContext):
    """Start code recovery process"""
    await state.set_state(RecoveryStates.waiting_phone)
    await message.answer(
        "🔑 <b>Восстановление кода</b>\n\n"
        "Введите номер телефона, который вы указали при регистрации:",
        parse_mode="HTML",
        reply_markup=get_registration_cancel()
    )


@client_router.message(RecoveryStates.waiting_phone)
async def process_recovery_phone(message: Message, state: FSMContext):
    """Process phone for code recovery"""
    phone_raw = message.text.strip() if message.text else ""

    # Handle cancel
    if phone_raw == "❌ Отмена":
        await state.clear()
        await message.answer(
            "❌ Отменено",
            reply_markup=get_client_menu()
        )
        return

    # Extract digits
    phone_digits = "".join(filter(str.isdigit, phone_raw))

    if len(phone_digits) < 9:
        await message.answer("❌ Введите корректный номер телефона (минимум 9 цифр)")
        return

    # Search for client
    client = await get_client_by_phone(phone_digits)

    await state.clear()

    if client:
        await message.answer(
            f"✅ <b>Код найден!</b>\n\n"
            f"Ваш код: <b>{client.code}</b>\n"
            f"ФИО: {client.full_name}\n\n"
            f"Сохраните этот код!",
            parse_mode="HTML",
            reply_markup=get_client_menu()
        )
    else:
        await message.answer(
            "❌ Клиент с таким номером не найден.\n\n"
            "Возможно вы указали другой номер при регистрации, "
            "или ещё не зарегистрированы.\n\n"
            "Отправьте /start для регистрации.",
            reply_markup=get_client_menu()
        )


# ============== Legacy Commands (for backwards compatibility) ==============

@client_router.message(F.text == "/code")
async def cmd_code(message: Message):
    """Legacy /code command - redirect to button handler"""
    await btn_my_code(message)


@client_router.message(F.text == "/status")
async def cmd_status(message: Message):
    """Legacy /status command - redirect to button handler"""
    await btn_my_parcels(message)
