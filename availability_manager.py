from datetime import datetime, timedelta

from db_manager import supabase


class AvailabilityManager:
    """Tenant-scoped appointment availability."""

    @staticmethod
    def create_slot(business_id: str, slot_datetime: str) -> bool:
        if not business_id:
            return False
        try:
            response = supabase.table("availability_slots").upsert({
                "business_id": business_id, "slot_datetime": slot_datetime,
                "status": "AVAILABLE", "updated_at": datetime.utcnow().isoformat(),
            }, on_conflict="business_id,slot_datetime").execute()
            return bool(response.data)
        except Exception as error:
            print(f"Tenant availability slot creation failed: {error}")
            return False

    @staticmethod
    def is_slot_available(business_id: str, slot_datetime: str) -> bool:
        if not business_id or datetime.fromisoformat(slot_datetime) <= datetime.utcnow():
            return False
        response = (
            supabase.table("availability_slots").select("slot_id")
            .eq("business_id", business_id).eq("slot_datetime", slot_datetime)
            .eq("status", "AVAILABLE").execute()
        )
        return bool(response.data)

    @staticmethod
    def reserve_slot(business_id: str, slot_datetime: str, booking_id: int) -> bool:
        if not business_id:
            return False
        response = (
            supabase.table("availability_slots").update({
                "status": "BOOKED", "booking_id": booking_id, "blocked_reason": None,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("business_id", business_id).eq("slot_datetime", slot_datetime)
            .eq("status", "AVAILABLE").execute()
        )
        return bool(response.data)

    @staticmethod
    def get_calendar_slots(business_id: str, start_datetime: str, end_datetime: str) -> list:
        if not business_id:
            return []
        response = (
            supabase.table("availability_slots").select("*").eq("business_id", business_id)
            .gte("slot_datetime", start_datetime).lt("slot_datetime", end_datetime)
            .order("slot_datetime").execute()
        )
        return response.data or []

    @staticmethod
    def block_time_range(business_id: str, start_datetime: str, end_datetime: str,
                         reason: str = "Blocked time", created_by: str = "DASHBOARD") -> bool:
        if not business_id:
            return False
        start_dt, end_dt = datetime.fromisoformat(start_datetime), datetime.fromisoformat(end_datetime)
        if end_dt <= start_dt:
            return False
        try:
            supabase.table("blocked_availability").insert({
                "business_id": business_id, "block_start": start_dt.isoformat(),
                "block_end": end_dt.isoformat(), "reason": reason, "created_by": created_by,
            }).execute()
            current = start_dt
            while current < end_dt:
                slot = current.isoformat()
                existing = (supabase.table("availability_slots").select("status")
                            .eq("business_id", business_id).eq("slot_datetime", slot)
                            .limit(1).execute())
                if not existing.data or existing.data[0].get("status") != "BOOKED":
                    supabase.table("availability_slots").upsert({
                        "business_id": business_id, "slot_datetime": slot, "status": "BLOCKED",
                        "booking_id": None, "blocked_reason": reason,
                        "updated_at": datetime.utcnow().isoformat(),
                    }, on_conflict="business_id,slot_datetime").execute()
                current += timedelta(minutes=30)
            return True
        except Exception as error:
            print(f"Tenant time range blocking failed: {error}")
            return False

    @staticmethod
    def unblock_slot(business_id: str, slot_id: int) -> bool:
        if not business_id:
            return False
        try:
            response = supabase.table("availability_slots").update({
                "status": "AVAILABLE", "booking_id": None, "blocked_reason": None,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("business_id", business_id).eq("slot_id", slot_id).eq("status", "BLOCKED").execute()
            return bool(response.data)
        except Exception as error:
            print(f"Tenant slot unblock failed: {error}")
            return False
