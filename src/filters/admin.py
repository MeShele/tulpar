"""
Tulpar Express - Admin Filter
"""
from aiogram.filters import Filter
from aiogram.types import Message

from src.config import config


class IsAdmin(Filter):
    """Filter to check if user is admin"""

    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in config.admin_chat_ids
