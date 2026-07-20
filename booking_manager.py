from datetime import datetime, timedelta

from db_manager import supabase
from customer_manager import CustomerManager
from service_manager import ServiceManager
from availability_manager import AvailabilityManager


class BookingManager:
    """Tenant-scoped booking creation, lookup, and calendar enrichment."""

    @staticmethod
    def _enrich_bookings(business_id: str, bookings: list) -> list:
        services = {str(row.get("id")): row for row in ServiceManager.get_services(business_id)}
        customers = {str(row.get("phone_number")): row
                     for row in CustomerManager.get_all_customers(business_id, limit=500)}
        return [{
            "id": booking.get("id"), "phone_number": booking.get("phone_number"),
            "service_id": booking.get("service_id"),
            "appointment_timestamp": booking.get("appointment_timestamp"), "status": booking.get("status"),
            "customer_name": (customers.get(str(booking.get("phone_number")), {}).get("first_name")
                              or "Unknown customer"),
            "service_name": (services.get(str(booking.get("service_id")), {}).get("service_name")
                             or services.get(str(booking.get("service_id")), {}).get("name")
                             or booking.get("service_name") or "Unknown service"),
        } for booking in bookings]

    @staticmethod
    def get_upcoming_bookings(business_id: str, limit: int = 20) -> list:
        now = datetime.utcnow().isoformat()
        response = (supabase.table("bookings").select("*").eq("business_id", business_id)
                    .gte("appointment_timestamp", now).neq("status", "CANCELLED")
                    .order("appointment_timestamp").limit(max(1, min(limit, 100))).execute())
        return BookingManager._enrich_bookings(business_id, response.data or [])

    @staticmethod
    def get_today_bookings(business_id: str) -> list:
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        response = (supabase.table("bookings").select("*").eq("business_id", business_id)
                    .gte("appointment_timestamp", start.isoformat())
                    .lt("appointment_timestamp", (start + timedelta(days=1)).isoformat())
                    .neq("status", "CANCELLED").order("appointment_timestamp").execute())
        return BookingManager._enrich_bookings(business_id, response.data or [])

    @staticmethod
    def get_calendar_slots(business_id: str, start_datetime: str, end_datetime: str) -> list:
        slots = AvailabilityManager.get_calendar_slots(business_id, start_datetime, end_datetime)
        booking_ids = [row.get("booking_id") for row in slots if row.get("booking_id") is not None]
        bookings_by_id = {}
        if booking_ids:
            response = (supabase.table("bookings").select("*").eq("business_id", business_id)
                        .in_("id", booking_ids).execute())
            bookings_by_id = {row.get("id"): row for row in BookingManager._enrich_bookings(business_id, response.data or [])}
        return [{**slot,
                 "customer_name": (bookings_by_id.get(slot.get("booking_id")) or {}).get("customer_name"),
                 "service_name": (bookings_by_id.get(slot.get("booking_id")) or {}).get("service_name")}
                for slot in slots]

    @staticmethod
    def create_manual_booking(business_id: str, phone_number: str, customer_name: str,
                              service_id: int, appointment_timestamp: str,
                              customer_email=None, customer_notes=None) -> dict:
        empty = {"success": False, "booking": None, "customer": None}
        if not business_id:
            return {**empty, "error": "A business workspace is required."}
        service = ServiceManager.get_service_by_id(business_id, int(service_id))
        if not service:
            return {**empty, "error": "The selected service does not exist."}
        try:
            appointment = datetime.fromisoformat(str(appointment_timestamp).replace("Z", "+00:00"))
            if appointment.tzinfo is not None:
                appointment = appointment.replace(tzinfo=None)
            appointment = appointment.replace(second=0, microsecond=0)
        except (TypeError, ValueError):
            return {**empty, "error": "The appointment date and time are invalid."}
        if appointment <= datetime.utcnow() or appointment.minute not in (0, 30):
            return {**empty, "error": "A booking cannot be created in the past." if appointment <= datetime.utcnow() else "Appointments must begin on the hour or half-hour."}
        customer_result = CustomerManager.create_or_update_customer(
            business_id, phone_number, customer_name, customer_email, customer_notes)
        if not customer_result.get("success"):
            return {**empty, "error": customer_result.get("error")}
        session_response = supabase.table("client_sessions").upsert({
            "business_id": business_id,
            "phone_number": CustomerManager.normalise_phone_number(phone_number),
            "current_state": "INITIAL_CONTACT",
            "context_data": {"source": "MANUAL", "created_manually": True},
            "last_interaction": datetime.utcnow().isoformat(),
        }, on_conflict="business_id,phone_number").execute()
        if not session_response.data:
            return {**empty, "customer": customer_result.get("customer"),
                    "error": "The required client session could not be created."}
        timestamp = appointment.isoformat()
        existing = (supabase.table("availability_slots").select("status").eq("business_id", business_id)
                    .eq("slot_datetime", timestamp).limit(1).execute())
        if existing.data and existing.data[0].get("status") in {"BOOKED", "BLOCKED"}:
            return {**empty, "customer": customer_result.get("customer"),
                    "error": "The selected time is already booked." if existing.data[0].get("status") == "BOOKED" else "The selected time is blocked."}
        if not existing.data and not AvailabilityManager.create_slot(business_id, timestamp):
            return {**empty, "error": "The availability slot could not be created."}
        if not AvailabilityManager.is_slot_available(business_id, timestamp):
            return {**empty, "error": "The selected time is not available."}
        booking_response = supabase.table("bookings").insert({
            "business_id": business_id, "phone_number": CustomerManager.normalise_phone_number(phone_number),
            "service_id": int(service_id), "appointment_timestamp": timestamp, "status": "PENDING",
        }).execute()
        if not booking_response.data:
            return {**empty, "error": "The booking could not be saved."}
        booking = booking_response.data[0]
        if not AvailabilityManager.reserve_slot(business_id, timestamp, booking.get("id")):
            supabase.table("bookings").update({"status": "CANCELLED"}).eq("business_id", business_id).eq("id", booking.get("id")).execute()
            return {**empty, "error": "The booking was created, but the slot could not be reserved."}
        return {"success": True, "error": None,
                "booking": BookingManager._enrich_bookings(business_id, [booking])[0],
                "customer": customer_result.get("customer"), "service": service}
