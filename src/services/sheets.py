"""
Tulpar Express - Google Sheets Service
CRUD operations for clients, parcels, codes
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from functools import partial
from typing import Optional, List, Dict, Any

import gspread
from google.oauth2.service_account import Credentials

from src.config import config
from src.models import Client, Parcel, ParcelStatus


class SheetsService:
    """Google Sheets data access layer"""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self) -> None:
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None

    def _get_client(self) -> gspread.Client:
        """Get or create gspread client (lazy initialization)"""
        if self._client is None:
            # Support both JSON string (for cloud) and file path (for local)
            if config.google_credentials_json:
                creds_info = json.loads(config.google_credentials_json)
                credentials = Credentials.from_service_account_info(
                    creds_info,
                    scopes=self.SCOPES,
                )
            else:
                credentials = Credentials.from_service_account_file(
                    config.google_credentials_path,
                    scopes=self.SCOPES,
                )
            self._client = gspread.authorize(credentials)
        return self._client

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        """Get or open spreadsheet (lazy initialization)"""
        if self._spreadsheet is None:
            client = self._get_client()
            self._spreadsheet = client.open_by_key(config.google_sheets_id)
        return self._spreadsheet

    async def _run_sync(self, func, *args, **kwargs):
        """Run synchronous gspread function in executor"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    # ============== Client Operations ==============

    async def get_client_by_chat_id(self, chat_id: int) -> Optional[Client]:
        """Find client by Telegram chat_id"""
        def _find():
            sheet = self._get_spreadsheet().worksheet("clients")
            records = sheet.get_all_records()
            for row in records:
                if str(row.get("chat_id")) == str(chat_id):
                    return Client.from_sheets_row(row)
            return None

        return await self._run_sync(_find)

    async def get_client_by_code(self, code: str) -> Optional[Client]:
        """Find client by code (TE-XXXX)"""
        def _find():
            sheet = self._get_spreadsheet().worksheet("clients")
            records = sheet.get_all_records()
            for row in records:
                if row.get("code") == code:
                    return Client.from_sheets_row(row)
            return None

        return await self._run_sync(_find)

    async def get_client_by_phone(self, phone: str) -> Optional[Client]:
        """Find client by phone number"""
        # Normalize phone - only digits
        phone_digits = "".join(filter(str.isdigit, phone))

        def _find():
            sheet = self._get_spreadsheet().worksheet("clients")
            records = sheet.get_all_records()
            for row in records:
                row_phone = "".join(filter(str.isdigit, row.get("phone", "")))
                if row_phone == phone_digits or row_phone.endswith(phone_digits[-9:]):
                    return Client.from_sheets_row(row)
            return None

        return await self._run_sync(_find)

    async def create_client(self, client: Client) -> Client:
        """Create new client record"""
        def _create():
            sheet = self._get_spreadsheet().worksheet("clients")
            row = client.to_sheets_row()
            sheet.append_row([
                row["chat_id"],
                row["code"],
                row["full_name"],
                row["phone"],
                row["reg_date"],
            ])
            return client

        return await self._run_sync(_create)

    async def get_all_clients(self) -> List[Client]:
        """Get all registered clients"""
        def _get_all():
            sheet = self._get_spreadsheet().worksheet("clients")
            records = sheet.get_all_records()
            return [Client.from_sheets_row(row) for row in records]

        return await self._run_sync(_get_all)

    # ============== Code Generation ==============

    async def generate_client_code(self) -> str:
        """Generate unique client code TE-XXXX using auto-increment"""
        def _generate():
            sheet = self._get_spreadsheet().worksheet("codes")
            # Get current last_number from A2
            current = sheet.acell("A2").value
            if current is None:
                current = 5000
            else:
                current = int(current)

            # Increment and save
            new_number = current + 1
            sheet.update_acell("A2", new_number)

            # Format with 4 digits, leading zeros (AC 1.4.2)
            return f"TE-{new_number:04d}"

        return await self._run_sync(_generate)

    # ============== Parcel Operations ==============

    async def get_parcels_by_client_code(self, client_code: str) -> List[Parcel]:
        """Get all parcels for a client"""
        def _get():
            sheet = self._get_spreadsheet().worksheet("parcels")
            records = sheet.get_all_records()
            return [
                Parcel.from_sheets_row(row)
                for row in records
                if row.get("client_code") == client_code
            ]

        return await self._run_sync(_get)

    async def get_parcel_by_tracking(self, tracking: str) -> Optional[Parcel]:
        """Find parcel by tracking number"""
        def _find():
            sheet = self._get_spreadsheet().worksheet("parcels")
            records = sheet.get_all_records()
            for row in records:
                if row.get("tracking") == tracking:
                    return Parcel.from_sheets_row(row)
            return None

        return await self._run_sync(_find)

    async def create_parcel(self, parcel: Parcel) -> Parcel:
        """Create new parcel record"""
        def _create():
            sheet = self._get_spreadsheet().worksheet("parcels")
            sheet.append_row([
                parcel.client_code,
                parcel.tracking,
                parcel.status.value,
                parcel.weight_kg,
                parcel.amount_usd,
                parcel.amount_som,
                parcel.date_china.isoformat() if parcel.date_china else "",
                parcel.date_bishkek.isoformat() if parcel.date_bishkek else "",
                parcel.date_delivered.isoformat() if parcel.date_delivered else "",
            ])
            return parcel

        return await self._run_sync(_create)

    async def update_parcel_status(
        self,
        client_code: str,
        tracking: str,
        new_status: ParcelStatus,
        **updates
    ) -> bool:
        """Update parcel status and optional fields"""
        def _update():
            sheet = self._get_spreadsheet().worksheet("parcels")
            records = sheet.get_all_records()

            for idx, row in enumerate(records, start=2):  # Start from row 2 (after header)
                if row.get("client_code") == client_code and row.get("tracking") == tracking:
                    # Update status
                    sheet.update_cell(idx, 3, new_status.value)

                    # Update optional fields
                    if "weight_kg" in updates:
                        sheet.update_cell(idx, 4, updates["weight_kg"])
                    if "amount_usd" in updates:
                        sheet.update_cell(idx, 5, updates["amount_usd"])
                    if "amount_som" in updates:
                        sheet.update_cell(idx, 6, updates["amount_som"])
                    if "date_bishkek" in updates:
                        sheet.update_cell(idx, 8, updates["date_bishkek"].isoformat())
                    if "date_delivered" in updates:
                        sheet.update_cell(idx, 9, updates["date_delivered"].isoformat())

                    return True
            return False

        return await self._run_sync(_update)

    async def get_parcels_by_status(self, status: Optional[str] = None, limit: int = 50) -> List[Parcel]:
        """Get parcels filtered by status"""
        def _get():
            sheet = self._get_spreadsheet().worksheet("parcels")
            records = sheet.get_all_records()

            if status == "ACTIVE":
                filtered = [r for r in records if r.get("status") != "DELIVERED"]
            elif status:
                filtered = [r for r in records if r.get("status") == status]
            else:
                filtered = records

            # Sort by newest first and limit
            return [Parcel.from_sheets_row(row) for row in filtered[:limit]]

        return await self._run_sync(_get)

    # ============== Statistics ==============

    async def get_statistics(self) -> Dict[str, Any]:
        """Get basic statistics"""
        def _stats():
            spreadsheet = self._get_spreadsheet()

            clients_sheet = spreadsheet.worksheet("clients")
            clients_count = len(clients_sheet.get_all_records())

            parcels_sheet = spreadsheet.worksheet("parcels")
            parcels = parcels_sheet.get_all_records()
            parcels_count = len(parcels)

            # Count by status
            status_counts = {}
            for parcel in parcels:
                status = parcel.get("status", "UNKNOWN")
                status_counts[status] = status_counts.get(status, 0) + 1

            return {
                "clients_count": clients_count,
                "parcels_count": parcels_count,
                "status_counts": status_counts,
            }

        return await self._run_sync(_stats)


# Global service instance
sheets_service = SheetsService()
