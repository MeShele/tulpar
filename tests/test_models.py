"""
Tests for data models
"""
import pytest
from datetime import datetime

from src.models import Client, Parcel, ParcelStatus


class TestClient:
    """Test Client model"""

    def test_from_sheets_row(self):
        """Test creating Client from sheets row"""
        row = {
            "chat_id": "123456789",
            "code": "TE-5001",
            "full_name": "Айгуль Асанова",
            "phone": "0700123456",
            "reg_date": "2026-01-14T12:00:00",
        }
        client = Client.from_sheets_row(row)

        assert client.chat_id == 123456789
        assert client.code == "TE-5001"
        assert client.full_name == "Айгуль Асанова"
        assert client.phone == "0700123456"

    def test_to_sheets_row(self):
        """Test converting Client to sheets row"""
        client = Client(
            chat_id=123456789,
            code="TE-5001",
            full_name="Test User",
            phone="0700123456",
            reg_date=datetime(2026, 1, 14, 12, 0, 0),
        )
        row = client.to_sheets_row()

        assert row["chat_id"] == "123456789"
        assert row["code"] == "TE-5001"
        assert row["full_name"] == "Test User"


class TestParcelStatus:
    """Test ParcelStatus enum"""

    def test_display_names(self):
        """Test status display names"""
        assert "Китае" in ParcelStatus.CHINA_WAREHOUSE.display_name
        assert "пути" in ParcelStatus.IN_TRANSIT.display_name
        assert "Бишкек" in ParcelStatus.BISHKEK_ARRIVED.display_name
        assert "Выдано" in ParcelStatus.DELIVERED.display_name

    def test_enum_values(self):
        """Test enum string values"""
        assert ParcelStatus.CHINA_WAREHOUSE.value == "CHINA_WAREHOUSE"
        assert ParcelStatus.DELIVERED.value == "DELIVERED"
