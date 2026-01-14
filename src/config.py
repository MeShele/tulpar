"""
Tulpar Express Bot - Configuration
Loads settings from environment variables
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent.parent / "docker" / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()  # Try default .env in current directory


@dataclass
class Config:
    """Bot configuration from environment variables"""

    # Telegram
    telegram_bot_token: str
    admin_chat_ids: List[int]

    # Google Sheets
    google_sheets_id: str
    google_credentials_path: str

    # PostgreSQL (optional)
    database_url: Optional[str]

    # Pricing defaults
    default_usd_to_som: float
    usd_per_kg: float

    # Payment API (O-Dengi / dengi.kg)
    dengi_api_url: Optional[str]
    dengi_sid: Optional[str]
    dengi_password: Optional[str]
    dengi_merchant_name: str
    dengi_api_version: int
    dengi_test_mode: bool

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables"""
        admin_ids_str = os.getenv("ADMIN_CHAT_ID", "")
        admin_chat_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]

        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            admin_chat_ids=admin_chat_ids,
            google_sheets_id=os.getenv("GOOGLE_SHEETS_ID", ""),
            google_credentials_path=os.getenv(
                "GOOGLE_CREDENTIALS_PATH",
                str(Path(__file__).parent.parent / "docker" / "google-service-account.json")
            ),
            database_url=os.getenv("DATABASE_URL"),
            default_usd_to_som=float(os.getenv("DEFAULT_USD_TO_SOM", "89.5")),
            usd_per_kg=float(os.getenv("USD_PER_KG", "1.2")),
            # Payment API (O-Dengi)
            dengi_api_url=os.getenv("DENGI_API_URL", "https://mw-api-test.dengi.kg/api"),
            dengi_sid=os.getenv("DENGI_SID"),
            dengi_password=os.getenv("DENGI_PASSWORD"),
            dengi_merchant_name=os.getenv("DENGI_MERCHANT_NAME", "Tulpar Express"),
            dengi_api_version=int(os.getenv("DENGI_API_VERSION", "1005")),
            dengi_test_mode=os.getenv("DENGI_TEST_MODE", "true").lower() == "true",
        )

    def validate(self) -> None:
        """Validate required configuration"""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.google_sheets_id:
            raise ValueError("GOOGLE_SHEETS_ID is required")
        if not Path(self.google_credentials_path).exists():
            raise ValueError(f"Google credentials not found: {self.google_credentials_path}")


# Global config instance
config = Config.from_env()
