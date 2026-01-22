"""Inline keyboards for the owner bot."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.autopost.config import settings
from src.autopost.db.models import PostDB, PostStatus


def to_local_time(dt: datetime) -> datetime:
    """Convert datetime to local timezone (from settings).

    Args:
        dt: Datetime to convert (assumed UTC if no tzinfo).

    Returns:
        Datetime in local timezone.
    """
    local_tz = ZoneInfo(settings.timezone)

    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    return dt.astimezone(local_tz)

# Callback data prefixes
CALLBACK_POSTS_PAGE = "posts:page"
CALLBACK_POST_VIEW = "post:view"
CALLBACK_PRODUCT_LINK = "product:link"
CALLBACK_ADMIN_RUN = "admin:run"
CALLBACK_ADMIN_POSTS = "admin:posts"
CALLBACK_ADMIN_STATUS = "admin:status"
CALLBACK_ADMIN_BACK = "admin:back"

# Reply keyboard button texts
BTN_RUN = "🚀 Запустить"
BTN_POSTS = "📋 Посты"
BTN_STATUS = "📊 Статус"


def build_main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    """Build main menu reply keyboard (bottom buttons).

    Returns:
        ReplyKeyboardMarkup with main action buttons.
    """
    buttons = [
        [KeyboardButton(text=BTN_RUN)],
        [KeyboardButton(text=BTN_POSTS), KeyboardButton(text=BTN_STATUS)],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        is_persistent=True,
    )


def build_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Build admin menu keyboard with main actions.

    Returns:
        InlineKeyboardMarkup with admin buttons.
    """
    buttons = [
        [InlineKeyboardButton(text="🚀 Запустить публикацию", callback_data=CALLBACK_ADMIN_RUN)],
        [InlineKeyboardButton(text="📋 Посты", callback_data=CALLBACK_ADMIN_POSTS)],
        [InlineKeyboardButton(text="📊 Статус", callback_data=CALLBACK_ADMIN_STATUS)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard with back to menu button.

    Returns:
        InlineKeyboardMarkup with back button.
    """
    buttons = [
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data=CALLBACK_ADMIN_BACK)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Page size for posts list
POSTS_PAGE_SIZE = 10

# Product buttons per row
PRODUCT_BUTTONS_PER_ROW = 2

# Product URL templates by source
PINDUODUO_URL_TEMPLATE = "https://mobile.yangkeduo.com/goods.html?goods_id={product_id}"
TAOBAO_URL_TEMPLATE = "https://item.taobao.com/item.htm?id={product_id}"


def get_product_url(product_id: str, source: str = "pinduoduo") -> str:
    """Get product URL based on source platform.

    Args:
        product_id: Product ID.
        source: Platform source (pinduoduo or taobao).

    Returns:
        Product URL for the appropriate platform.
    """
    if source == "taobao":
        return TAOBAO_URL_TEMPLATE.format(product_id=product_id)
    return PINDUODUO_URL_TEMPLATE.format(product_id=product_id)


def get_source_name(source: str) -> str:
    """Get human-readable source name.

    Args:
        source: Platform source (pinduoduo or taobao).

    Returns:
        Human-readable platform name.
    """
    names = {
        "pinduoduo": "Pinduoduo",
        "taobao": "Taobao",
    }
    return names.get(source, source.title())


def get_status_emoji(status: str) -> str:
    """Get emoji for post status.

    Args:
        status: Post status string.

    Returns:
        Emoji representing the status.
    """
    status_emojis = {
        PostStatus.PENDING.value: "⏳",
        PostStatus.TELEGRAM_ONLY.value: "📱",
        PostStatus.PUBLISHED.value: "✅",
        PostStatus.INSTAGRAM_FAILED.value: "⚠️",
    }
    return status_emojis.get(status, "❓")


def get_status_text(status: str) -> str:
    """Get human-readable text for post status.

    Args:
        status: Post status string.

    Returns:
        Human-readable status text.
    """
    status_texts = {
        PostStatus.PENDING.value: "Ожидает",
        PostStatus.TELEGRAM_ONLY.value: "Только TG",
        PostStatus.PUBLISHED.value: "Опубликован",
        PostStatus.INSTAGRAM_FAILED.value: "IG ошибка",
    }
    return status_texts.get(status, "Неизвестно")


def format_post_button_text(post: PostDB) -> str:
    """Format text for post button in list.

    Args:
        post: PostDB instance.

    Returns:
        Formatted button text.
    """
    local_time = to_local_time(post.created_at)
    date_str = local_time.strftime("%d.%m.%Y")
    products_count = len(post.products_json) if post.products_json else 0
    status_emoji = get_status_emoji(post.status)

    return f"{date_str} | {products_count} тов. | {status_emoji}"


def build_posts_keyboard(
    posts: list[PostDB],
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for posts list.

    Args:
        posts: List of posts for current page.
        current_page: Current page number (1-indexed).
        total_pages: Total number of pages.

    Returns:
        InlineKeyboardMarkup with post buttons and pagination.
    """
    buttons: list[list[InlineKeyboardButton]] = []

    # Add post buttons
    for post in posts:
        button_text = format_post_button_text(post)
        callback_data = f"{CALLBACK_POST_VIEW}:{post.id}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])

    # Add pagination row
    pagination_row: list[InlineKeyboardButton] = []

    if current_page > 1:
        pagination_row.append(
            InlineKeyboardButton(
                text="← Назад",
                callback_data=f"{CALLBACK_POSTS_PAGE}:{current_page - 1}",
            )
        )

    # Page indicator
    pagination_row.append(
        InlineKeyboardButton(
            text=f"{current_page}/{total_pages}",
            callback_data="noop",
        )
    )

    if current_page < total_pages:
        pagination_row.append(
            InlineKeyboardButton(
                text="Вперёд →",
                callback_data=f"{CALLBACK_POSTS_PAGE}:{current_page + 1}",
            )
        )

    if pagination_row:
        buttons.append(pagination_row)

    # Add back to menu button
    buttons.append(
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data=CALLBACK_ADMIN_BACK)]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_post_detail_keyboard(
    post: PostDB,
    current_page: int = 1,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for post detail view with product buttons.

    Args:
        post: PostDB instance with products.
        current_page: Current page to return to.

    Returns:
        InlineKeyboardMarkup with product buttons and back button.
    """
    buttons: list[list[InlineKeyboardButton]] = []

    # Add product buttons (2 per row)
    products = post.products_json if post.products_json else []
    row: list[InlineKeyboardButton] = []

    for i, _product in enumerate(products):
        callback_data = f"{CALLBACK_PRODUCT_LINK}:{post.id}:{i}"
        button = InlineKeyboardButton(
            text=f"🔗 Товар {i + 1}",
            callback_data=callback_data,
        )
        row.append(button)

        # Add row when we have 2 buttons or it's the last product
        if len(row) == PRODUCT_BUTTONS_PER_ROW or i == len(products) - 1:
            buttons.append(row)
            row = []

    # Add back button
    buttons.append(
        [
            InlineKeyboardButton(
                text="← Назад к списку",
                callback_data=f"{CALLBACK_POSTS_PAGE}:{current_page}",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_posts_list_message(
    posts: list[PostDB],
    current_page: int,
    total_pages: int,
    total_count: int,
) -> str:
    """Format the posts list message text.

    Args:
        posts: List of posts for current page.
        current_page: Current page number.
        total_pages: Total number of pages.
        total_count: Total number of posts.

    Returns:
        Formatted message text.
    """
    if not posts:
        return "📋 У вас пока нет публикаций."

    lines = ["📋 <b>Ваши публикации:</b>", ""]

    for i, post in enumerate(posts, start=1):
        idx = (current_page - 1) * POSTS_PAGE_SIZE + i
        local_time = to_local_time(post.created_at)
        date_str = local_time.strftime("%d.%m.%Y %H:%M")
        products_count = len(post.products_json) if post.products_json else 0
        status_emoji = get_status_emoji(post.status)
        status_text = get_status_text(post.status)

        lines.append(
            f"{idx}. 📅 {date_str} | 🛒 {products_count} тов. | {status_emoji} {status_text}"
        )

    lines.append("")
    lines.append(f"Всего: {total_count} | Страница {current_page} из {total_pages}")

    return "\n".join(lines)


def format_post_detail_message(post: PostDB) -> str:
    """Format the post detail message text.

    Args:
        post: PostDB instance.

    Returns:
        Formatted message text with product details.
    """
    local_time = to_local_time(post.created_at)
    date_str = local_time.strftime("%d.%m.%Y %H:%M")
    status_emoji = get_status_emoji(post.status)
    status_text = get_status_text(post.status)

    lines = [
        f"📝 <b>Пост #{post.id}</b>",
        "",
        f"📅 Дата: {date_str}",
        f"📊 Статус: {status_emoji} {status_text}",
    ]

    if post.telegram_message_id:
        lines.append(f"📱 Telegram ID: {post.telegram_message_id}")

    if post.instagram_post_id:
        lines.append(f"📸 Instagram ID: {post.instagram_post_id}")

    lines.append("")
    lines.append("<b>🛒 Товары:</b>")
    lines.append("")

    products = post.products_json if post.products_json else []
    for i, product in enumerate(products, start=1):
        title = product.get("title", product.get("name", "Товар"))
        price = product.get("price_kgs", product.get("price", 0))
        discount = product.get("discount", 0)

        # Truncate long titles
        if len(title) > 40:
            title = title[:37] + "..."

        line = f"{i}. {title}"
        if price:
            line += f"\n   💰 {price:,} сом".replace(",", " ")
        if discount:
            line += f" (-{discount}%)"

        lines.append(line)

    return "\n".join(lines)


def format_product_link_message(product: dict, product_index: int) -> str:
    """Format message with product link for Pinduoduo/Taobao.

    Args:
        product: Product dictionary with id, title, price_kgs, discount, source.
        product_index: Product index (0-based) for display.

    Returns:
        Formatted message text with product info and link.
    """
    # Get product details
    product_id = product.get("id", product.get("pdd_id", ""))
    title = product.get("title", product.get("name", "Товар"))
    price = product.get("price_kgs", product.get("price", 0))
    discount = product.get("discount", 0)
    source = product.get("source", "pinduoduo")

    # Build the URL based on source
    url = get_product_url(product_id, source) if product_id else ""
    source_name = get_source_name(source)

    lines = [
        f"🔗 <b>Товар #{product_index + 1}:</b>",
        "",
        f"📦 {title}",
    ]

    if price:
        price_line = f"💰 {price:,} сом".replace(",", " ")
        if discount:
            price_line += f" (-{discount}%)"
        lines.append(price_line)

    lines.append("")

    if product_id:
        lines.append(f"🏪 Источник: {source_name}")
        lines.append(f"🔎 ID: <code>{product_id}</code>")
        lines.append("")
        lines.append(f"👉 <a href=\"{url}\">Открыть на {source_name}</a>")
        lines.append("")
        lines.append("💡 <i>Для лучших цен ищите по ID в приложении</i>")
    else:
        lines.append("⚠️ Ссылка недоступна (нет ID товара)")

    return "\n".join(lines)
