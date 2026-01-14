"""
Tulpar Express - Data Models
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ParcelStatus(str, Enum):
    """Parcel status constants"""
    CHINA_WAREHOUSE = "CHINA_WAREHOUSE"  # На складе в Китае
    IN_TRANSIT = "IN_TRANSIT"            # В пути
    BISHKEK_ARRIVED = "BISHKEK_ARRIVED"  # Прибыло в Бишкек
    READY_PICKUP = "READY_PICKUP"        # Готово к выдаче
    DELIVERED = "DELIVERED"              # Выдано

    @property
    def display_name(self) -> str:
        """Human-readable status name in Russian"""
        names = {
            self.CHINA_WAREHOUSE: "📦 На складе в Китае",
            self.IN_TRANSIT: "✈️ В пути",
            self.BISHKEK_ARRIVED: "🏠 Прибыло в Бишкек",
            self.READY_PICKUP: "💰 Готово к выдаче",
            self.DELIVERED: "✅ Выдано",
        }
        return names.get(self, self.value)


@dataclass
class Client:
    """Client data model matching Google Sheets 'clients' sheet"""
    chat_id: int
    code: str  # TE-XXXX format
    full_name: str
    phone: str
    reg_date: datetime

    @classmethod
    def from_sheets_row(cls, row: dict) -> "Client":
        """Create Client from Google Sheets row"""
        return cls(
            chat_id=int(row.get("chat_id", 0)),
            code=row.get("code", ""),
            full_name=row.get("full_name", ""),
            phone=row.get("phone", ""),
            reg_date=datetime.fromisoformat(row.get("reg_date", datetime.now().isoformat())),
        )

    def to_sheets_row(self) -> dict:
        """Convert to Google Sheets row format"""
        return {
            "chat_id": str(self.chat_id),
            "code": self.code,
            "full_name": self.full_name,
            "phone": self.phone,
            "reg_date": self.reg_date.isoformat(),
        }


@dataclass
class Parcel:
    """Parcel data model matching Google Sheets 'parcels' sheet"""
    client_code: str
    tracking: str
    status: ParcelStatus
    weight_kg: float
    amount_usd: float
    amount_som: float
    date_china: Optional[datetime]
    date_bishkek: Optional[datetime]
    date_delivered: Optional[datetime]

    @classmethod
    def from_sheets_row(cls, row: dict) -> "Parcel":
        """Create Parcel from Google Sheets row"""
        def parse_date(val: str) -> Optional[datetime]:
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                return None

        # Safe status parsing - fallback to CHINA_WAREHOUSE if invalid
        try:
            status = ParcelStatus(row.get("status", ParcelStatus.CHINA_WAREHOUSE.value))
        except ValueError:
            status = ParcelStatus.CHINA_WAREHOUSE

        return cls(
            client_code=row.get("client_code", ""),
            tracking=row.get("tracking", ""),
            status=status,
            weight_kg=float(row.get("weight_kg", 0)),
            amount_usd=float(row.get("amount_usd", 0)),
            amount_som=float(row.get("amount_som", 0)),
            date_china=parse_date(row.get("date_china", "")),
            date_bishkek=parse_date(row.get("date_bishkek", "")),
            date_delivered=parse_date(row.get("date_delivered", "")),
        )
