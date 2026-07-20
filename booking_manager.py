from datetime import datetime, timedelta
from typing import Optional

from db_manager import supabase
from customer_manager import CustomerManager
from service_manager import ServiceManager
from availability_manager import AvailabilityManager


class BookingManager:
    """Tenant-scoped booking creation, lookup, rescheduling, cancellation, and enrichment."""

    ACTIVE_BOOKING_STATUSES = [
        "PENDING",
        "CONFIRMED",
        "BOOKED",
    ]

    @staticmethod
    def _normalise_timestamp(timestamp: str) -> Optional[str]:
        """
        Convert an incoming ISO timestamp into the naive ISO format currently
        used by the booking and availability tables.
        """
        if not timestamp:
            return None

        try:
            appointment = datetime.fromisoformat(
                str(timestamp).replace("Z", "+00:00")
            )

            if appointment.tzinfo is not None:
                appointment = appointment.replace(tzinfo=None)

            appointment = appointment.replace(
                second=0,
                microsecond=0,
            )

            return appointment.isoformat()

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _release_slot(
        business_id: str,
        slot_datetime: str,
        booking_id: int,
    ) -> bool:
        """
        Return a booked slot to AVAILABLE after a booking is cancelled
        or rescheduled.
        """
        if not business_id or not slot_datetime or booking_id is None:
            return False

        try:
            response = (
                supabase.table("availability_slots")
                .update(
                    {
                        "status": "AVAILABLE",
                        "booking_id": None,
                        "blocked_reason": None,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                )
                .eq("business_id", business_id)
                .eq("slot_datetime", slot_datetime)
                .eq("booking_id", booking_id)
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(f"Tenant slot release failed: {error}")
            return False

    @staticmethod
    def _enrich_bookings(
        business_id: str,
        bookings: list,
    ) -> list:
        if not business_id or not bookings:
            return []

        services = {
            str(row.get("id")): row
            for row in ServiceManager.get_services(business_id)
        }

        customers = {
            str(row.get("phone_number")): row
            for row in CustomerManager.get_all_customers(
                business_id,
                limit=500,
            )
        }

        enriched_bookings = []

        for booking in bookings:
            service = services.get(
                str(booking.get("service_id")),
                {},
            )

            customer = customers.get(
                str(booking.get("phone_number")),
                {},
            )

            enriched_bookings.append(
                {
                    "id": booking.get("id"),
                    "business_id": booking.get("business_id"),
                    "phone_number": booking.get("phone_number"),
                    "service_id": booking.get("service_id"),
                    "appointment_timestamp": booking.get(
                        "appointment_timestamp"
                    ),
                    "status": booking.get("status"),
                    "customer_name": (
                        customer.get("first_name")
                        or customer.get("full_name")
                        or customer.get("name")
                        or "Unknown customer"
                    ),
                    "service_name": (
                        service.get("service_name")
                        or service.get("name")
                        or booking.get("service_name")
                        or "Unknown service"
                    ),
                }
            )

        return enriched_bookings

    @staticmethod
    def get_upcoming_bookings(
        business_id: str,
        limit: int = 20,
    ) -> list:
        if not business_id:
            return []

        try:
            now = datetime.utcnow().isoformat()
            safe_limit = max(
                1,
                min(int(limit or 20), 100),
            )

            response = (
                supabase.table("bookings")
                .select("*")
                .eq("business_id", business_id)
                .gte("appointment_timestamp", now)
                .neq("status", "CANCELLED")
                .order("appointment_timestamp")
                .limit(safe_limit)
                .execute()
            )

            return BookingManager._enrich_bookings(
                business_id,
                response.data or [],
            )

        except Exception as error:
            print(f"Tenant upcoming-bookings lookup failed: {error}")
            return []

    @staticmethod
    def get_today_bookings(
        business_id: str,
    ) -> list:
        if not business_id:
            return []

        try:
            start = datetime.utcnow().replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            end = start + timedelta(days=1)

            response = (
                supabase.table("bookings")
                .select("*")
                .eq("business_id", business_id)
                .gte("appointment_timestamp", start.isoformat())
                .lt("appointment_timestamp", end.isoformat())
                .neq("status", "CANCELLED")
                .order("appointment_timestamp")
                .execute()
            )

            return BookingManager._enrich_bookings(
                business_id,
                response.data or [],
            )

        except Exception as error:
            print(f"Tenant today-bookings lookup failed: {error}")
            return []

    @staticmethod
    def get_calendar_slots(
        business_id: str,
        start_datetime: str,
        end_datetime: str,
    ) -> list:
        if not business_id:
            return []

        try:
            slots = AvailabilityManager.get_calendar_slots(
                business_id,
                start_datetime,
                end_datetime,
            )

            booking_ids = [
                row.get("booking_id")
                for row in slots
                if row.get("booking_id") is not None
            ]

            bookings_by_id = {}

            if booking_ids:
                response = (
                    supabase.table("bookings")
                    .select("*")
                    .eq("business_id", business_id)
                    .in_("id", booking_ids)
                    .execute()
                )

                enriched_bookings = BookingManager._enrich_bookings(
                    business_id,
                    response.data or [],
                )

                bookings_by_id = {
                    booking.get("id"): booking
                    for booking in enriched_bookings
                }

            return [
                {
                    **slot,
                    "customer_name": (
                        bookings_by_id.get(
                            slot.get("booking_id")
                        )
                        or {}
                    ).get("customer_name"),
                    "service_name": (
                        bookings_by_id.get(
                            slot.get("booking_id")
                        )
                        or {}
                    ).get("service_name"),
                }
                for slot in slots
            ]

        except Exception as error:
            print(f"Tenant booking calendar lookup failed: {error}")
            return []

    @staticmethod
    def create_manual_booking(
        business_id: str,
        phone_number: str,
        customer_name: str,
        service_id: int,
        appointment_timestamp: str,
        customer_email=None,
        customer_notes=None,
    ) -> dict:
        empty = {
            "success": False,
            "booking": None,
            "customer": None,
        }

        if not business_id:
            return {
                **empty,
                "error": "A business workspace is required.",
            }

        try:
            clean_service_id = int(service_id)
        except (TypeError, ValueError):
            return {
                **empty,
                "error": "A valid service must be selected.",
            }

        service = ServiceManager.get_service_by_id(
            business_id,
            clean_service_id,
        )

        if not service:
            return {
                **empty,
                "error": "The selected service does not exist.",
            }

        timestamp = BookingManager._normalise_timestamp(
            appointment_timestamp
        )

        if not timestamp:
            return {
                **empty,
                "error": "The appointment date and time are invalid.",
            }

        appointment = datetime.fromisoformat(timestamp)

        if appointment <= datetime.utcnow():
            return {
                **empty,
                "error": "A booking cannot be created in the past.",
            }

        if appointment.minute not in (0, 30):
            return {
                **empty,
                "error": (
                    "Appointments must begin on the hour "
                    "or half-hour."
                ),
            }

        customer_result = (
            CustomerManager.create_or_update_customer(
                business_id,
                phone_number,
                customer_name,
                customer_email,
                customer_notes,
            )
        )

        if not customer_result.get("success"):
            return {
                **empty,
                "error": customer_result.get("error"),
            }

        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        try:
            session_response = (
                supabase.table("client_sessions")
                .upsert(
                    {
                        "business_id": business_id,
                        "phone_number": clean_phone,
                        "current_state": "INITIAL_CONTACT",
                        "context_data": {
                            "source": "MANUAL",
                            "created_manually": True,
                        },
                        "last_interaction": (
                            datetime.utcnow().isoformat()
                        ),
                    },
                    on_conflict="business_id,phone_number",
                )
                .execute()
            )

            if not session_response.data:
                return {
                    **empty,
                    "customer": customer_result.get("customer"),
                    "error": (
                        "The required client session "
                        "could not be created."
                    ),
                }

            existing = (
                supabase.table("availability_slots")
                .select("status")
                .eq("business_id", business_id)
                .eq("slot_datetime", timestamp)
                .limit(1)
                .execute()
            )

            if existing.data:
                slot_status = str(
                    existing.data[0].get("status") or ""
                ).upper()

                if slot_status == "BOOKED":
                    return {
                        **empty,
                        "customer": customer_result.get("customer"),
                        "error": (
                            "The selected time is already booked."
                        ),
                    }

                if slot_status == "BLOCKED":
                    return {
                        **empty,
                        "customer": customer_result.get("customer"),
                        "error": "The selected time is blocked.",
                    }

            if (
                not existing.data
                and not AvailabilityManager.create_slot(
                    business_id,
                    timestamp,
                )
            ):
                return {
                    **empty,
                    "customer": customer_result.get("customer"),
                    "error": (
                        "The availability slot could not "
                        "be created."
                    ),
                }

            if not AvailabilityManager.is_slot_available(
                business_id,
                timestamp,
            ):
                return {
                    **empty,
                    "customer": customer_result.get("customer"),
                    "error": (
                        "The selected time is not available."
                    ),
                }

            booking_response = (
                supabase.table("bookings")
                .insert(
                    {
                        "business_id": business_id,
                        "phone_number": clean_phone,
                        "service_id": clean_service_id,
                        "appointment_timestamp": timestamp,
                        "status": "PENDING",
                    }
                )
                .execute()
            )

            if not booking_response.data:
                return {
                    **empty,
                    "customer": customer_result.get("customer"),
                    "error": "The booking could not be saved.",
                }

            booking = booking_response.data[0]
            booking_id = booking.get("id")

            if not AvailabilityManager.reserve_slot(
                business_id,
                timestamp,
                booking_id,
            ):
                (
                    supabase.table("bookings")
                    .update({"status": "CANCELLED"})
                    .eq("business_id", business_id)
                    .eq("id", booking_id)
                    .execute()
                )

                return {
                    **empty,
                    "customer": customer_result.get("customer"),
                    "error": (
                        "The booking was created, but the "
                        "slot could not be reserved."
                    ),
                }

            enriched = BookingManager._enrich_bookings(
                business_id,
                [booking],
            )

            return {
                "success": True,
                "error": None,
                "booking": enriched[0] if enriched else booking,
                "customer": customer_result.get("customer"),
                "service": service,
            }

        except Exception as error:
            print(f"Tenant manual booking creation failed: {error}")

            return {
                **empty,
                "error": str(error),
            }

    @staticmethod
    def insert_booking(
        business_id: str,
        phone_number: str,
        service_id: int,
        timestamp_str: str,
    ) -> dict:
        """
        Create a booking from the WhatsApp conversational flow.
        """
        if not business_id:
            return {}

        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        timestamp = BookingManager._normalise_timestamp(
            timestamp_str
        )

        if not clean_phone or not timestamp:
            return {}

        try:
            clean_service_id = int(service_id)
        except (TypeError, ValueError):
            return {}

        try:
            appointment = datetime.fromisoformat(timestamp)

            if appointment <= datetime.utcnow():
                print("Cannot create booking in the past.")
                return {}

            service = ServiceManager.get_service_by_id(
                business_id,
                clean_service_id,
            )

            if not service:
                print("Selected service does not exist.")
                return {}

            existing_slot = (
                supabase.table("availability_slots")
                .select("status")
                .eq("business_id", business_id)
                .eq("slot_datetime", timestamp)
                .limit(1)
                .execute()
            )

            if not existing_slot.data:
                slot_created = AvailabilityManager.create_slot(
                    business_id,
                    timestamp,
                )

                if not slot_created:
                    print("Availability slot could not be created.")
                    return {}

            if not AvailabilityManager.is_slot_available(
                business_id,
                timestamp,
            ):
                print("Selected slot is not available.")
                return {}

            booking_response = (
                supabase.table("bookings")
                .insert(
                    {
                        "business_id": business_id,
                        "phone_number": clean_phone,
                        "service_id": clean_service_id,
                        "appointment_timestamp": timestamp,
                        "status": "PENDING",
                    }
                )
                .execute()
            )

            if not booking_response.data:
                return {}

            booking = booking_response.data[0]
            booking_id = booking.get("id")

            slot_reserved = AvailabilityManager.reserve_slot(
                business_id,
                timestamp,
                booking_id,
            )

            if not slot_reserved:
                (
                    supabase.table("bookings")
                    .update({"status": "CANCELLED"})
                    .eq("business_id", business_id)
                    .eq("id", booking_id)
                    .execute()
                )

                return {}

            return booking

        except Exception as error:
            print(
                "Tenant calendar allocation processing "
                f"failure: {error}"
            )
            return {}

    @staticmethod
    def get_latest_active_booking(
        business_id: str,
        phone_number: str,
    ) -> Optional[dict]:
        """
        Find the customer's nearest future non-cancelled booking
        inside the current tenant.
        """
        if not business_id:
            return None

        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        if not clean_phone:
            return None

        try:
            now = datetime.utcnow().isoformat()

            response = (
                supabase.table("bookings")
                .select("*")
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .gte("appointment_timestamp", now)
                .neq("status", "CANCELLED")
                .order("appointment_timestamp", desc=False)
                .limit(1)
                .execute()
            )

            if response.data:
                return response.data[0]

            return None

        except Exception as error:
            print(f"Tenant booking lookup failed: {error}")
            return None

    @staticmethod
    def reschedule_latest_booking(
        business_id: str,
        phone_number: str,
        new_timestamp_str: str,
    ) -> dict:
        """
        Move the customer's nearest active booking to a new
        tenant-scoped availability slot.
        """
        if not business_id:
            return {}

        timestamp = BookingManager._normalise_timestamp(
            new_timestamp_str
        )

        if not timestamp:
            return {}

        try:
            appointment = datetime.fromisoformat(timestamp)

            if appointment <= datetime.utcnow():
                print("Cannot reschedule booking to the past.")
                return {}

            booking = BookingManager.get_latest_active_booking(
                business_id,
                phone_number,
            )

            if not booking:
                return {}

            old_timestamp = booking.get(
                "appointment_timestamp"
            )
            booking_id = booking.get("id")

            existing_slot = (
                supabase.table("availability_slots")
                .select("status")
                .eq("business_id", business_id)
                .eq("slot_datetime", timestamp)
                .limit(1)
                .execute()
            )

            if not existing_slot.data:
                slot_created = AvailabilityManager.create_slot(
                    business_id,
                    timestamp,
                )

                if not slot_created:
                    return {}

            if not AvailabilityManager.is_slot_available(
                business_id,
                timestamp,
            ):
                print("New slot is not available.")
                return {}

            reserve_success = (
                AvailabilityManager.reserve_slot(
                    business_id,
                    timestamp,
                    booking_id,
                )
            )

            if not reserve_success:
                print("New slot could not be reserved.")
                return {}

            response = (
                supabase.table("bookings")
                .update(
                    {
                        "appointment_timestamp": timestamp,
                        "status": "PENDING",
                    }
                )
                .eq("business_id", business_id)
                .eq("id", booking_id)
                .execute()
            )

            if not response.data:
                BookingManager._release_slot(
                    business_id,
                    timestamp,
                    booking_id,
                )
                return {}

            if old_timestamp and old_timestamp != timestamp:
                BookingManager._release_slot(
                    business_id,
                    old_timestamp,
                    booking_id,
                )

            return response.data[0]

        except Exception as error:
            print(f"Tenant booking reschedule failed: {error}")
            return {}

    @staticmethod
    def cancel_latest_booking(
        business_id: str,
        phone_number: str,
    ) -> dict:
        """
        Cancel the customer's nearest active booking and release
        the associated tenant availability slot.
        """
        if not business_id:
            return {}

        try:
            booking = BookingManager.get_latest_active_booking(
                business_id,
                phone_number,
            )

            if not booking:
                return {}

            booking_id = booking.get("id")
            appointment_timestamp = booking.get(
                "appointment_timestamp"
            )

            response = (
                supabase.table("bookings")
                .update({"status": "CANCELLED"})
                .eq("business_id", business_id)
                .eq("id", booking_id)
                .execute()
            )

            if not response.data:
                return {}

            if appointment_timestamp:
                BookingManager._release_slot(
                    business_id,
                    appointment_timestamp,
                    booking_id,
                )

            return response.data[0]

        except Exception as error:
            print(f"Tenant booking cancellation failed: {error}")
            return {}