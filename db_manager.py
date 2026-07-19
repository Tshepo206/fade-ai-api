import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Database credentials missing inside .env configurations.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


class BarberDatabaseManager:
    """Manages bookings, clients, sessions, services, availability, bookkeeping, and analytics."""

    @staticmethod
    def get_or_create_session(phone_number: str) -> dict:
        try:
            response = (
                supabase.table("client_sessions")
                .select("*")
                .eq("phone_number", phone_number)
                .execute()
            )

            if response.data:
                return response.data[0]

            new_session = {
                "phone_number": phone_number,
                "current_state": "INITIAL_CONTACT",
                "context_data": {},
            }

            insert_resp = supabase.table("client_sessions").insert(new_session).execute()
            return insert_resp.data[0]

        except Exception as error:
            print(f"Session verification failure: {error}")
            return {
                "phone_number": phone_number,
                "current_state": "INITIAL_CONTACT",
                "context_data": {},
            }

    @staticmethod
    def ensure_client_session(
        phone_number: str,
        source: str = "MANUAL",
    ) -> bool:
        """Ensure a client_sessions row exists before creating a booking."""
        try:
            clean_phone = BarberDatabaseManager.normalise_phone_number(
                phone_number
            )

            if not clean_phone:
                print("Client session creation failed: missing phone number.")
                return False

            existing_response = (
                supabase.table("client_sessions")
                .select("phone_number")
                .eq("phone_number", clean_phone)
                .limit(1)
                .execute()
            )

            if existing_response.data:
                return True

            session_data = {
                "phone_number": clean_phone,
                "current_state": "INITIAL_CONTACT",
                "context_data": {
                    "source": source,
                    "created_manually": source.upper() == "MANUAL",
                },
                "last_interaction": datetime.utcnow().isoformat(),
            }

            insert_response = (
                supabase.table("client_sessions")
                .insert(session_data)
                .execute()
            )

            return bool(insert_response.data)

        except Exception as error:
            print(f"Client session creation failed: {error}")
            return False

    @staticmethod
    def update_session_state(phone_number: str, new_state: str, context_updates: dict = None) -> None:
        try:
            update_data = {
                "current_state": new_state,
                "last_interaction": datetime.utcnow().isoformat(),
            }

            if context_updates is not None:
                update_data["context_data"] = context_updates

            supabase.table("client_sessions").update(update_data).eq(
                "phone_number", phone_number
            ).execute()

        except Exception as error:
            print(f"State engine syncing malfunction: {error}")

    @staticmethod
    def save_pending_transaction(phone_number: str, transaction: dict, missing_field: str) -> bool:
        try:
            data = {
                "phone_number": phone_number,
                "transaction_json": transaction,
                "missing_field": missing_field,
                "created_at": datetime.utcnow().isoformat(),
            }

            supabase.table("pending_transactions").upsert(
                data,
                on_conflict="phone_number",
            ).execute()

            return True

        except Exception as error:
            print(f"Pending transaction save failed: {error}")
            return False

    @staticmethod
    def get_pending_transaction(phone_number: str):
        try:
            response = (
                supabase.table("pending_transactions")
                .select("*")
                .eq("phone_number", phone_number)
                .execute()
            )

            if response.data:
                return response.data[0]

            return None

        except Exception as error:
            print(f"Pending transaction lookup failed: {error}")
            return None

    @staticmethod
    def delete_pending_transaction(phone_number: str) -> bool:
        try:
            supabase.table("pending_transactions").delete().eq(
                "phone_number", phone_number
            ).execute()

            return True

        except Exception as error:
            print(f"Pending transaction delete failed: {error}")
            return False

    @staticmethod
    def has_pending_transaction(phone_number: str) -> bool:
        return BarberDatabaseManager.get_pending_transaction(phone_number) is not None

    # ------------------------------------------------------------------
    # CLIENTS / CUSTOMER MANAGEMENT
    # ------------------------------------------------------------------

    @staticmethod
    def normalise_phone_number(phone_number: str) -> str:
        """Return a consistent digits-only phone number."""
        if not phone_number:
            return ""

        clean_phone = "".join(
            character
            for character in str(phone_number)
            if character.isdigit()
        )

        if clean_phone.startswith("0") and len(clean_phone) == 10:
            clean_phone = f"27{clean_phone[1:]}"

        return clean_phone

    @staticmethod
    def get_client(phone_number: str):
        try:
            clean_phone = BarberDatabaseManager.normalise_phone_number(
                phone_number
            )

            if not clean_phone:
                return None

            response = (
                supabase.table("clients")
                .select("*")
                .eq("phone_number", clean_phone)
                .limit(1)
                .execute()
            )

            if response.data:
                return response.data[0]

            return None

        except Exception as error:
            print(f"Client lookup failed: {error}")
            return None

    @staticmethod
    def get_all_clients(
        search_term: str = None,
        limit: int = 100,
    ) -> list:
        """Return clients, including manually added clients with no revenue yet."""
        try:
            safe_limit = max(1, min(int(limit or 100), 500))

            query = (
                supabase.table("clients")
                .select("*")
                .order("first_name")
                .limit(safe_limit)
            )

            if search_term and search_term.strip():
                query = query.ilike(
                    "first_name",
                    f"%{search_term.strip()}%",
                )

            response = query.execute()
            return response.data or []

        except Exception as error:
            print(f"Customer-list lookup failed: {error}")
            return []

    @staticmethod
    def create_or_update_client(
        phone_number: str,
        first_name: str,
        email: str = None,
        notes: str = None,
    ) -> dict:
        """Create or update a client directly in Supabase."""
        try:
            clean_phone = BarberDatabaseManager.normalise_phone_number(
                phone_number
            )
            clean_name = (first_name or "").strip().title()
            clean_email = (email or "").strip().lower()
            clean_notes = (notes or "").strip()

            if not clean_phone:
                return {
                    "success": False,
                    "error": "A valid phone number is required.",
                    "customer": None,
                }

            if len(clean_phone) < 10:
                return {
                    "success": False,
                    "error": "The phone number is too short.",
                    "customer": None,
                }

            if not clean_name:
                return {
                    "success": False,
                    "error": "The customer's name is required.",
                    "customer": None,
                }

            customer_data = {
                "phone_number": clean_phone,
                "first_name": clean_name,
            }

            if clean_email:
                customer_data["email"] = clean_email

            if clean_notes:
                customer_data["notes"] = clean_notes

            response = (
                supabase.table("clients")
                .upsert(
                    customer_data,
                    on_conflict="phone_number",
                )
                .execute()
            )

            if not response.data:
                return {
                    "success": False,
                    "error": "Supabase did not return the saved customer.",
                    "customer": None,
                }

            return {
                "success": True,
                "error": None,
                "customer": response.data[0],
            }

        except Exception as error:
            print(f"Customer save failed: {error}")
            return {
                "success": False,
                "error": str(error),
                "customer": None,
            }

    @staticmethod
    def upsert_client(phone_number: str, first_name: str) -> bool:
        """Backwards-compatible wrapper used by the WhatsApp flow."""
        result = BarberDatabaseManager.create_or_update_client(
            phone_number=phone_number,
            first_name=first_name,
        )
        return bool(result.get("success"))

    @staticmethod
    def fetch_services() -> list:
        try:
            response = supabase.table("services").select("*").execute()
            return response.data or []

        except Exception as error:
            print(f"Service lookup failed: {error}")
            return []

    @staticmethod
    def get_service_by_id(service_id: int):
        try:
            response = (
                supabase.table("services")
                .select("*")
                .eq("id", service_id)
                .execute()
            )

            if response.data:
                return response.data[0]

            return None

        except Exception as error:
            print(f"Service lookup by ID failed: {error}")
            return None

    # ------------------------------------------------------------------
    # AVAILABILITY ENGINE
    # ------------------------------------------------------------------

    @staticmethod
    def create_availability_slot(slot_datetime: str) -> bool:
        try:
            data = {
                "slot_datetime": slot_datetime,
                "status": "AVAILABLE",
                "updated_at": datetime.utcnow().isoformat(),
            }

            supabase.table("availability_slots").upsert(
                data,
                on_conflict="slot_datetime",
            ).execute()

            return True

        except Exception as error:
            print(f"Availability slot creation failed: {error}")
            return False

    @staticmethod
    def create_availability_slots_for_day(
        target_date: str,
        start_hour: int = 9,
        end_hour: int = 18,
        interval_minutes: int = 30,
    ) -> bool:
        try:
            start_dt = datetime.fromisoformat(f"{target_date}T{start_hour:02d}:00:00")
            end_dt = datetime.fromisoformat(f"{target_date}T{end_hour:02d}:00:00")

            rows = []
            current = start_dt

            while current < end_dt:
                rows.append(
                    {
                        "slot_datetime": current.isoformat(),
                        "status": "AVAILABLE",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                )
                current += timedelta(minutes=interval_minutes)

            if rows:
                supabase.table("availability_slots").upsert(
                    rows,
                    on_conflict="slot_datetime",
                ).execute()

            return True

        except Exception as error:
            print(f"Daily availability generation failed: {error}")
            return False

    @staticmethod
    def get_available_slots(start_datetime: str = None, end_datetime: str = None) -> list:
        try:
            query = supabase.table("availability_slots").select("*").eq(
                "status", "AVAILABLE"
            )

            if start_datetime:
                query = query.gte("slot_datetime", start_datetime)

            if end_datetime:
                query = query.lt("slot_datetime", end_datetime)

            response = query.order("slot_datetime").execute()
            return response.data or []

        except Exception as error:
            print(f"Availability lookup failed: {error}")
            return []

    @staticmethod
    def is_slot_available(slot_datetime: str) -> bool:
        try:
            if datetime.fromisoformat(slot_datetime) <= datetime.utcnow():
                return False

            response = (
                supabase.table("availability_slots")
                .select("*")
                .eq("slot_datetime", slot_datetime)
                .eq("status", "AVAILABLE")
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(f"Availability validation failed: {error}")
            return False

    @staticmethod
    def book_slot(slot_datetime: str, booking_id: int) -> bool:
        try:
            if not BarberDatabaseManager.is_slot_available(slot_datetime):
                return False

            response = (
                supabase.table("availability_slots")
                .update(
                    {
                        "status": "BOOKED",
                        "booking_id": booking_id,
                        "blocked_reason": None,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                )
                .eq("slot_datetime", slot_datetime)
                .eq("status", "AVAILABLE")
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(f"Slot booking failed: {error}")
            return False

    @staticmethod
    def block_slot(slot_datetime: str, reason: str = "Blocked by owner") -> bool:
        try:
            existing_booking = (
                supabase.table("availability_slots")
                .select("*")
                .eq("slot_datetime", slot_datetime)
                .eq("status", "BOOKED")
                .execute()
            )

            if existing_booking.data:
                print("Cannot block a slot that is already booked.")
                return False

            supabase.table("availability_slots").upsert(
                {
                    "slot_datetime": slot_datetime,
                    "status": "BLOCKED",
                    "booking_id": None,
                    "blocked_reason": reason,
                    "updated_at": datetime.utcnow().isoformat(),
                },
                on_conflict="slot_datetime",
            ).execute()

            return True

        except Exception as error:
            print(f"Slot blocking failed: {error}")
            return False

    @staticmethod
    def unblock_slot(slot_id: str) -> bool:
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
                .eq("slot_id", slot_id)
                .execute()
            )

            return True

        except Exception as error:
            print(f"Slot unblock failed: {error}")
            return False

    @staticmethod
    def block_time_range(
        start_datetime: str,
        end_datetime: str,
        reason: str = "Blocked by owner",
        created_by: str = "OWNER",
        interval_minutes: int = 30,
    ) -> bool:
        try:
            start_dt = datetime.fromisoformat(start_datetime)
            end_dt = datetime.fromisoformat(end_datetime)

            if end_dt <= start_dt:
                print("Block end time must be after start time.")
                return False

            supabase.table("blocked_availability").insert(
                {
                    "block_start": start_dt.isoformat(),
                    "block_end": end_dt.isoformat(),
                    "reason": reason,
                    "created_by": created_by,
                }
            ).execute()

            current = start_dt

            while current < end_dt:
                slot_datetime = current.isoformat()

                existing_booking = (
                    supabase.table("availability_slots")
                    .select("*")
                    .eq("slot_datetime", slot_datetime)
                    .eq("status", "BOOKED")
                    .execute()
                )

                if not existing_booking.data:
                    supabase.table("availability_slots").upsert(
                        {
                            "slot_datetime": slot_datetime,
                            "status": "BLOCKED",
                            "booking_id": None,
                            "blocked_reason": reason,
                            "updated_at": datetime.utcnow().isoformat(),
                        },
                        on_conflict="slot_datetime",
                    ).execute()

                current += timedelta(minutes=interval_minutes)

            return True

        except Exception as error:
            print(f"Time range blocking failed: {error}")
            return False

    @staticmethod
    def unblock_time_range(
        start_datetime: str,
        end_datetime: str,
        interval_minutes: int = 30,
    ) -> bool:
        try:
            start_dt = datetime.fromisoformat(start_datetime)
            end_dt = datetime.fromisoformat(end_datetime)

            if end_dt <= start_dt:
                print("Unblock end time must be after start time.")
                return False

            current = start_dt

            while current < end_dt:
                supabase.table("availability_slots").update(
                    {
                        "status": "AVAILABLE",
                        "booking_id": None,
                        "blocked_reason": None,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                ).eq("slot_datetime", current.isoformat()).eq("status", "BLOCKED").execute()

                current += timedelta(minutes=interval_minutes)

            return True

        except Exception as error:
            print(f"Time range unblock failed: {error}")
            return False

    @staticmethod
    def block_full_day(
        target_date: str,
        reason: str = "Full day blocked",
        created_by: str = "OWNER",
    ) -> bool:
        try:
            return BarberDatabaseManager.block_time_range(
                start_datetime=f"{target_date}T00:00:00",
                end_datetime=f"{target_date}T23:59:00",
                reason=reason,
                created_by=created_by,
            )

        except Exception as error:
            print(f"Full day blocking failed: {error}")
            return False

    @staticmethod
    def get_blocked_periods(start_datetime: str = None, end_datetime: str = None) -> list:
        try:
            query = supabase.table("blocked_availability").select("*")

            if start_datetime:
                query = query.gte("block_start", start_datetime)

            if end_datetime:
                query = query.lt("block_end", end_datetime)

            response = query.order("block_start").execute()
            return response.data or []

        except Exception as error:
            print(f"Blocked periods lookup failed: {error}")
            return []

    @staticmethod
    def is_slot_blocked(slot_datetime: str) -> bool:
        try:
            response = (
                supabase.table("availability_slots")
                .select("*")
                .eq("slot_datetime", slot_datetime)
                .eq("status", "BLOCKED")
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(f"Blocked slot check failed: {error}")
            return False

    @staticmethod
    def get_day_schedule(target_date: str) -> list:
        try:
            start_dt = datetime.fromisoformat(f"{target_date}T00:00:00")
            end_dt = start_dt + timedelta(days=1)

            response = (
                supabase.table("availability_slots")
                .select("*")
                .gte("slot_datetime", start_dt.isoformat())
                .lt("slot_datetime", end_dt.isoformat())
                .order("slot_datetime")
                .execute()
            )

            return response.data or []

        except Exception as error:
            print(f"Day schedule lookup failed: {error}")
            return []

    @staticmethod
    def get_calendar_slots(
            start_datetime: str,
            end_datetime: str,
        ) -> list:
        try:
            slots_response = (
                supabase.table("availability_slots")
                .select("*")
                .gte("slot_datetime", start_datetime)
                .lt("slot_datetime", end_datetime)
                .order("slot_datetime")
                .execute()
            )

            slots = slots_response.data or []

            booking_ids = [
                slot.get("booking_id")
                for slot in slots
                if slot.get("booking_id") is not None
            ]

            bookings_by_id = {}

            if booking_ids:
                bookings_response = (
                    supabase.table("bookings")
                    .select("*")
                    .in_("id", booking_ids)
                    .execute()
                )

                bookings = bookings_response.data or []
                enriched_bookings = BarberDatabaseManager._enrich_bookings(bookings)

                bookings_by_id = {
                    booking.get("id"): booking
                    for booking in enriched_bookings
                }

            daily_schedule = []

            for slot in slots:
                booking = bookings_by_id.get(slot.get("booking_id"))

                daily_schedule.append(
                    {
                        "slot_id": slot.get("slot_id"),
                        "slot_datetime": slot.get("slot_datetime"),
                        "status": slot.get("status"),
                        "booking_id": slot.get("booking_id"),
                        "blocked_reason": slot.get("blocked_reason"),
                        "customer_name": booking.get("customer_name") if booking else None,
                        "service_name": booking.get("service_name") if booking else None,
                    }
                )

            return daily_schedule

        except Exception as error:
            print(f"Calendar slots lookup failed: {error}")
            return []

    @staticmethod
    def unblock_slot(slot_id: int) -> bool:
            try:
                supabase.table("availability_slots").update({
                    "status": "AVAILABLE",
                    "booking_id": None,
                    "blocked_reason": None,
                    "updated_at": datetime.utcnow().isoformat(),
                }).eq("slot_id", slot_id).eq("status", "BLOCKED").execute()

                return True

            except Exception as error:
                print(f"Unblock slot failed: {error}")
                return False

    # ------------------------------------------------------------------
    # BOOKINGS
    # ------------------------------------------------------------------

    @staticmethod
    def create_manual_booking(
        phone_number: str,
        customer_name: str,
        service_id: int,
        appointment_timestamp: str,
        customer_email: str = None,
        customer_notes: str = None,
    ) -> dict:
        """Create/update the customer, booking, and availability slot in Supabase."""
        try:
            clean_phone = BarberDatabaseManager.normalise_phone_number(
                phone_number
            )
            clean_name = (customer_name or "").strip().title()

            if not clean_phone:
                return {
                    "success": False,
                    "error": "A valid customer phone number is required.",
                    "booking": None,
                    "customer": None,
                }

            if not clean_name:
                return {
                    "success": False,
                    "error": "The customer's name is required.",
                    "booking": None,
                    "customer": None,
                }

            try:
                clean_service_id = int(service_id)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error": "A valid service must be selected.",
                    "booking": None,
                    "customer": None,
                }

            service = BarberDatabaseManager.get_service_by_id(clean_service_id)
            if not service:
                return {
                    "success": False,
                    "error": "The selected service does not exist.",
                    "booking": None,
                    "customer": None,
                }

            try:
                appointment_dt = datetime.fromisoformat(
                    str(appointment_timestamp).replace("Z", "+00:00")
                )
                if appointment_dt.tzinfo is not None:
                    appointment_dt = appointment_dt.replace(tzinfo=None)
                appointment_dt = appointment_dt.replace(second=0, microsecond=0)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "error": "The appointment date and time are invalid.",
                    "booking": None,
                    "customer": None,
                }

            if appointment_dt <= datetime.utcnow():
                return {
                    "success": False,
                    "error": "A booking cannot be created in the past.",
                    "booking": None,
                    "customer": None,
                }

            if appointment_dt.minute not in (0, 30):
                return {
                    "success": False,
                    "error": "Appointments must begin on the hour or half-hour.",
                    "booking": None,
                    "customer": None,
                }

            clean_timestamp = appointment_dt.isoformat()

            customer_result = BarberDatabaseManager.create_or_update_client(
                phone_number=clean_phone,
                first_name=clean_name,
                email=customer_email,
                notes=customer_notes,
            )

            if not customer_result.get("success"):
                return {
                    "success": False,
                    "error": customer_result.get("error")
                    or "The customer could not be saved.",
                    "booking": None,
                    "customer": None,
                }

            session_ready = BarberDatabaseManager.ensure_client_session(
                phone_number=clean_phone,
                source="MANUAL",
            )

            if not session_ready:
                return {
                    "success": False,
                    "error": (
                        "The customer was saved, but the required "
                        "client session could not be created."
                    ),
                    "booking": None,
                    "customer": customer_result.get("customer"),
                }

            existing_slot_response = (
                supabase.table("availability_slots")
                .select("*")
                .eq("slot_datetime", clean_timestamp)
                .limit(1)
                .execute()
            )
            existing_slot = (
                existing_slot_response.data[0]
                if existing_slot_response.data
                else None
            )

            if existing_slot:
                slot_status = str(existing_slot.get("status") or "").upper()
                if slot_status == "BLOCKED":
                    return {
                        "success": False,
                        "error": "The selected time is blocked.",
                        "booking": None,
                        "customer": customer_result.get("customer"),
                    }
                if slot_status == "BOOKED":
                    return {
                        "success": False,
                        "error": "The selected time is already booked.",
                        "booking": None,
                        "customer": customer_result.get("customer"),
                    }
            else:
                if not BarberDatabaseManager.create_availability_slot(
                    clean_timestamp
                ):
                    return {
                        "success": False,
                        "error": "The availability slot could not be created.",
                        "booking": None,
                        "customer": customer_result.get("customer"),
                    }

            if not BarberDatabaseManager.is_slot_available(clean_timestamp):
                return {
                    "success": False,
                    "error": "The selected time is not available.",
                    "booking": None,
                    "customer": customer_result.get("customer"),
                }

            booking_data = {
                "phone_number": clean_phone,
                "service_id": clean_service_id,
                "appointment_timestamp": clean_timestamp,
                "status": "PENDING",
            }

            booking_response = (
                supabase.table("bookings")
                .insert(booking_data)
                .execute()
            )
            if not booking_response.data:
                return {
                    "success": False,
                    "error": "The booking could not be saved.",
                    "booking": None,
                    "customer": customer_result.get("customer"),
                }

            booking = booking_response.data[0]
            booking_id = booking.get("id")

            if not BarberDatabaseManager.book_slot(clean_timestamp, booking_id):
                supabase.table("bookings").update(
                    {"status": "CANCELLED"}
                ).eq("id", booking_id).execute()
                return {
                    "success": False,
                    "error": "The booking was created, but the slot could not be reserved.",
                    "booking": None,
                    "customer": customer_result.get("customer"),
                }

            enriched_bookings = BarberDatabaseManager._enrich_bookings([booking])
            enriched_booking = enriched_bookings[0] if enriched_bookings else booking

            return {
                "success": True,
                "error": None,
                "booking": enriched_booking,
                "customer": customer_result.get("customer"),
                "service": service,
            }

        except Exception as error:
            print(f"Manual booking creation failed: {error}")
            return {
                "success": False,
                "error": str(error),
                "booking": None,
                "customer": None,
            }

    @staticmethod
    def insert_booking(phone_number: str, service_id: int, timestamp_str: str) -> dict:
        try:
            if datetime.fromisoformat(timestamp_str) <= datetime.utcnow():
                print("Cannot create booking in the past.")
                return {}

            availability_exists = (
                supabase.table("availability_slots")
                .select("*")
                .eq("slot_datetime", timestamp_str)
                .execute()
            )

            if not availability_exists.data:
                BarberDatabaseManager.create_availability_slot(timestamp_str)

            if not BarberDatabaseManager.is_slot_available(timestamp_str):
                print("Selected slot is not available.")
                return {}

            booking_data = {
                "phone_number": phone_number,
                "service_id": service_id,
                "appointment_timestamp": timestamp_str,
                "status": "PENDING",
            }

            booking_response = supabase.table("bookings").insert(booking_data).execute()

            if not booking_response.data:
                return {}

            booking = booking_response.data[0]
            booking_id = booking.get("id")

            slot_booked = BarberDatabaseManager.book_slot(timestamp_str, booking_id)

            if not slot_booked:
                supabase.table("bookings").update({"status": "CANCELLED"}).eq(
                    "id", booking_id
                ).execute()
                return {}

            return booking

        except Exception as error:
            print(f"Calendar allocation processing failure: {error}")
            return {}

    @staticmethod
    def get_latest_active_booking(phone_number: str):
        try:
            now = datetime.utcnow().isoformat()

            response = (
                supabase.table("bookings")
                .select("*")
                .eq("phone_number", phone_number)
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
            print(f"Booking lookup failed: {error}")
            return None

    @staticmethod
    def reschedule_latest_booking(phone_number: str, new_timestamp_str: str) -> dict:
        try:
            if datetime.fromisoformat(new_timestamp_str) <= datetime.utcnow():
                print("Cannot reschedule booking to the past.")
                return {}

            booking = BarberDatabaseManager.get_latest_active_booking(phone_number)

            if not booking:
                return {}

            old_timestamp = booking.get("appointment_timestamp")
            booking_id = booking.get("id")

            availability_exists = (
                supabase.table("availability_slots")
                .select("*")
                .eq("slot_datetime", new_timestamp_str)
                .execute()
            )

            if not availability_exists.data:
                BarberDatabaseManager.create_availability_slot(new_timestamp_str)

            if not BarberDatabaseManager.is_slot_available(new_timestamp_str):
                print("New slot is not available.")
                return {}

            response = (
                supabase.table("bookings")
                .update(
                    {
                        "appointment_timestamp": new_timestamp_str,
                        "status": "PENDING",
                    }
                )
                .eq("id", booking_id)
                .execute()
            )

            if not response.data:
                return {}

            if old_timestamp:
                supabase.table("availability_slots").update(
                    {
                        "status": "AVAILABLE",
                        "booking_id": None,
                        "blocked_reason": None,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                ).eq("slot_datetime", old_timestamp).eq("booking_id", booking_id).execute()

            BarberDatabaseManager.book_slot(new_timestamp_str, booking_id)

            return response.data[0]

        except Exception as error:
            print(f"Booking reschedule failed: {error}")
            return {}

    @staticmethod
    def cancel_latest_booking(phone_number: str) -> dict:
        try:
            booking = BarberDatabaseManager.get_latest_active_booking(phone_number)

            if not booking:
                return {}

            booking_id = booking.get("id")
            appointment_timestamp = booking.get("appointment_timestamp")

            response = (
                supabase.table("bookings")
                .update({"status": "CANCELLED"})
                .eq("id", booking_id)
                .execute()
            )

            if appointment_timestamp:
                supabase.table("availability_slots").update(
                    {
                        "status": "AVAILABLE",
                        "booking_id": None,
                        "blocked_reason": None,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                ).eq("slot_datetime", appointment_timestamp).eq("booking_id", booking_id).execute()

            if response.data:
                return response.data[0]

            return {}

        except Exception as error:
            print(f"Booking cancellation failed: {error}")
            return {}

    # ------------------------------------------------------------------
    # LEDGER / BOOKKEEPING
    # ------------------------------------------------------------------

    @staticmethod
    def record_ledger_entry(booking_id: int, account_type: str, debit: float, credit: float, narrative: str) -> bool:
        try:
            ledger_data = {
                "booking_id": booking_id,
                "account_type": account_type,
                "debit_amount": debit,
                "credit_amount": credit,
                "narrative": narrative,
            }

            supabase.table("financial_ledger").insert(ledger_data).execute()
            return True

        except Exception as error:
            print(f"Accounting ledger validation broken: {error}")
            return False

    @staticmethod
    def record_transaction(
        customer_name: str = None,
        service_name: str = None,
        amount: float = None,
        payment_method: str = None,
        transaction_type: str = "Service",
        booking_id: int = None,
    ) -> bool:
        try:
            if amount is None:
                print("Transaction amount missing. Ledger entry not saved.")
                return False

            clean_transaction_type = (transaction_type or "Service").strip().title()
            clean_payment_method = (payment_method or "").strip().title()
            clean_customer_name = (customer_name or "").strip().title()
            clean_service_name = (service_name or "").strip().title()

            is_expense = clean_transaction_type == "Expense"

            debit_amount = float(amount) if is_expense else 0
            credit_amount = 0 if is_expense else float(amount)

            if is_expense:
                account_type = "Expense"
            elif clean_transaction_type == "Retail":
                account_type = "Retail Revenue"
            else:
                account_type = "Service Revenue"

            narrative_parts = []

            if clean_service_name:
                narrative_parts.append(clean_service_name)

            if clean_customer_name:
                narrative_parts.append(clean_customer_name)

            if clean_payment_method:
                narrative_parts.append(clean_payment_method)

            narrative = " - ".join(narrative_parts) or f"{account_type} transaction"

            ledger_data = {
                "transaction_timestamp": datetime.utcnow().isoformat(),
                "account_type": account_type,
                "debit_amount": debit_amount,
                "credit_amount": credit_amount,
                "narrative": narrative,
                "customer_name": clean_customer_name or None,
                "service_name": clean_service_name or None,
                "payment_method": clean_payment_method or None,
                "booking_id": booking_id,
            }

            response = supabase.table("financial_ledger").insert(ledger_data).execute()

            print("[Ledger Save] Transaction saved:")
            print(response.data)

            return True

        except Exception as error:
            print(f"Transaction ledger save failed: {error}")
            return False

    @staticmethod
    def get_recent_transactions(limit: int = 20):
        try:
            response = (
                supabase.table("financial_ledger")
                .select("*")
                .order("transaction_timestamp", desc=True)
                .limit(limit)
                .execute()
            )

            return response.data or []

        except Exception as error:
            print(f"Transaction lookup failed: {error}")
            return []

    # ------------------------------------------------------------------
    # DASHBOARD / ANALYTICS
    # ------------------------------------------------------------------

    @staticmethod
    def _enrich_bookings(bookings: list) -> list:
        try:
            services = BarberDatabaseManager.fetch_services()
            clients_response = supabase.table("clients").select("*").execute()
            clients = clients_response.data or []

            services_by_id = {
                str(service.get("id")): service
                for service in services
                if service.get("id") is not None
            }

            clients_by_phone = {
                str(client.get("phone_number")): client
                for client in clients
                if client.get("phone_number") is not None
            }

            enriched_bookings = []

            for booking in bookings:
                service_id = booking.get("service_id")
                phone_number = booking.get("phone_number")

                service = services_by_id.get(str(service_id), {})
                client = clients_by_phone.get(str(phone_number), {})

                customer_name = (
                    client.get("first_name")
                    or client.get("full_name")
                    or client.get("name")
                    or "Unknown customer"
                )

                service_name = (
                    service.get("service_name")
                    or service.get("name")
                    or booking.get("service_name")
                    or "Unknown service"
                )

                enriched_bookings.append(
                    {
                        "id": booking.get("id"),
                        "phone_number": phone_number,
                        "service_id": service_id,
                        "appointment_timestamp": booking.get("appointment_timestamp"),
                        "status": booking.get("status"),
                        "customer_name": customer_name,
                        "service_name": service_name,
                    }
                )

            return enriched_bookings

        except Exception as error:
            print(f"Booking enrichment failed: {error}")
            return bookings

    @staticmethod
    def get_today_bookings():
        try:
            now = datetime.utcnow()
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)

            bookings_response = (
                supabase.table("bookings")
                .select("*")
                .gte("appointment_timestamp", start_date.isoformat())
                .lt("appointment_timestamp", end_date.isoformat())
                .neq("status", "CANCELLED")
                .order("appointment_timestamp")
                .execute()
            )

            bookings = bookings_response.data or []
            return BarberDatabaseManager._enrich_bookings(bookings)

        except Exception as error:
            print(f"Today bookings lookup failed: {error}")
            return []

    @staticmethod
    def get_upcoming_bookings(limit: int = 20):
        try:
            now = datetime.utcnow().isoformat()

            bookings_response = (
                supabase.table("bookings")
                .select("*")
                .gte("appointment_timestamp", now)
                .neq("status", "CANCELLED")
                .order("appointment_timestamp")
                .limit(limit)
                .execute()
            )

            bookings = bookings_response.data or []
            return BarberDatabaseManager._enrich_bookings(bookings)

        except Exception as error:
            print(f"Booking lookup failed: {error}")
            return []

    @staticmethod
    def _get_period_start(period: str):
        now = datetime.utcnow()

        if period == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

        if period == "week":
            return now - timedelta(days=7)

        if period == "month":
            return now - timedelta(days=30)

        return None

    @staticmethod
    def get_dashboard_summary(period: str = "today"):
        try:
            start_date = BarberDatabaseManager._get_period_start(period)

            if start_date is None:
                start_date = datetime.utcnow().replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                period = "today"

            response = (
                supabase.table("financial_ledger")
                .select("*")
                .gte("transaction_timestamp", start_date.isoformat())
                .execute()
            )

            transactions = response.data or []

            revenue = 0
            expenses = 0
            cash = 0
            card = 0

            for row in transactions:
                credit = float(row.get("credit_amount") or 0)
                debit = float(row.get("debit_amount") or 0)
                payment = (row.get("payment_method") or "").strip().title()

                revenue += credit
                expenses += debit

                if payment == "Cash":
                    cash += credit
                elif payment == "Card":
                    card += credit

            profit = revenue - expenses

            return {
                "success": True,
                "period": period,
                "revenue": revenue,
                "expenses": expenses,
                "profit": profit,
                "cash": cash,
                "card": card,
                "transactions": len(transactions),
            }

        except Exception as error:
            print(f"Dashboard summary failed: {error}")

            return {
                "success": False,
                "period": period,
                "revenue": 0,
                "expenses": 0,
                "profit": 0,
                "cash": 0,
                "card": 0,
                "transactions": 0,
            }

    @staticmethod
    def get_revenue_trends(period: str = "week"):
        try:
            now = datetime.utcnow()
            days = 30 if period == "month" else 7
            start_date = now - timedelta(days=days)

            response = (
                supabase.table("financial_ledger")
                .select("*")
                .gte("transaction_timestamp", start_date.isoformat())
                .execute()
            )

            transactions = response.data or []
            trends = {}

            for i in range(days):
                day = start_date + timedelta(days=i + 1)
                day_key = day.strftime("%Y-%m-%d")

                trends[day_key] = {
                    "date": day_key,
                    "revenue": 0,
                    "expenses": 0,
                    "profit": 0,
                }

            for row in transactions:
                timestamp = row.get("transaction_timestamp")

                if not timestamp:
                    continue

                tx_date = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                ).strftime("%Y-%m-%d")

                if tx_date not in trends:
                    continue

                credit = float(row.get("credit_amount") or 0)
                debit = float(row.get("debit_amount") or 0)

                trends[tx_date]["revenue"] += credit
                trends[tx_date]["expenses"] += debit
                trends[tx_date]["profit"] += credit - debit

            return list(trends.values())

        except Exception as error:
            print(f"Revenue trends lookup failed: {error}")
            return []

    @staticmethod
    def get_revenue_by_service(period: str = "month"):
        try:
            start_date = BarberDatabaseManager._get_period_start(period)
            query = supabase.table("financial_ledger").select("*")

            if start_date:
                query = query.gte("transaction_timestamp", start_date.isoformat())

            response = query.execute()
            transactions = response.data or []
            service_totals = {}

            for row in transactions:
                credit = float(row.get("credit_amount") or 0)

                if credit <= 0:
                    continue

                service_name = row.get("service_name") or "Uncategorised service"

                if service_name not in service_totals:
                    service_totals[service_name] = {
                        "service_name": service_name,
                        "revenue": 0,
                        "transactions": 0,
                    }

                service_totals[service_name]["revenue"] += credit
                service_totals[service_name]["transactions"] += 1

            services = list(service_totals.values())
            services.sort(key=lambda item: item["revenue"], reverse=True)

            return services

        except Exception as error:
            print(f"Revenue by service lookup failed: {error}")
            return []

    @staticmethod
    def get_top_customers(period: str = "month", limit: int = 10):
        try:
            start_date = BarberDatabaseManager._get_period_start(period)
            query = supabase.table("financial_ledger").select("*")

            if start_date:
                query = query.gte("transaction_timestamp", start_date.isoformat())

            response = query.execute()
            transactions = response.data or []
            customer_totals = {}

            for row in transactions:
                credit = float(row.get("credit_amount") or 0)

                if credit <= 0:
                    continue

                customer_name = row.get("customer_name") or "Unknown customer"

                if customer_name not in customer_totals:
                    customer_totals[customer_name] = {
                        "customer_name": customer_name,
                        "revenue": 0,
                        "visits": 0,
                    }

                customer_totals[customer_name]["revenue"] += credit
                customer_totals[customer_name]["visits"] += 1

            customers = list(customer_totals.values())
            customers.sort(key=lambda item: item["revenue"], reverse=True)

            return customers[:limit]

        except Exception as error:
            print(f"Top customers lookup failed: {error}")
            return []

    @staticmethod
    def get_ai_recommendations(period: str = "today"):
        try:
            summary = BarberDatabaseManager.get_dashboard_summary(period)
            bookings = BarberDatabaseManager.get_upcoming_bookings(limit=20)
            revenue_by_service = BarberDatabaseManager.get_revenue_by_service(period)
            top_customers = BarberDatabaseManager.get_top_customers(period, limit=3)

            recommendations = []

            revenue = float(summary.get("revenue") or 0)
            cash = float(summary.get("cash") or 0)
            card = float(summary.get("card") or 0)
            transactions = int(summary.get("transactions") or 0)

            if revenue == 0:
                recommendations.append(
                    {
                        "type": "revenue",
                        "title": "No revenue recorded yet",
                        "message": "No sales have been recorded for this period. Voice bookkeeping entries will update this automatically.",
                    }
                )
            else:
                recommendations.append(
                    {
                        "type": "revenue",
                        "title": "Revenue is active",
                        "message": f"Revenue for this period is R{revenue:.0f} across {transactions} recorded transactions.",
                    }
                )

            if card > cash:
                recommendations.append(
                    {
                        "type": "payments",
                        "title": "Card payments are leading",
                        "message": f"Card payments are R{card:.0f}, higher than cash payments of R{cash:.0f}.",
                    }
                )
            elif cash > card:
                recommendations.append(
                    {
                        "type": "payments",
                        "title": "Cash payments are leading",
                        "message": f"Cash payments are R{cash:.0f}, higher than card payments of R{card:.0f}.",
                    }
                )

            if bookings:
                recommendations.append(
                    {
                        "type": "bookings",
                        "title": "Upcoming appointments",
                        "message": f"There are {len(bookings)} upcoming appointments on the dashboard.",
                    }
                )
            else:
                recommendations.append(
                    {
                        "type": "bookings",
                        "title": "No upcoming appointments",
                        "message": "There are no upcoming appointments. This may be a good time to send WhatsApp reminders or promotions.",
                    }
                )

            if revenue_by_service:
                top_service = revenue_by_service[0]
                recommendations.append(
                    {
                        "type": "service",
                        "title": "Top service",
                        "message": f"{top_service['service_name']} is currently the highest earning service at R{top_service['revenue']:.0f}.",
                    }
                )

            if top_customers:
                top_customer = top_customers[0]
                recommendations.append(
                    {
                        "type": "customer",
                        "title": "Top customer",
                        "message": f"{top_customer['customer_name']} is currently the top customer with R{top_customer['revenue']:.0f} revenue.",
                    }
                )

            return recommendations

        except Exception as error:
            print(f"AI recommendations failed: {error}")
            return []

    @staticmethod
    def get_bank_reconciliation(period: str = "today"):
        try:
            summary = BarberDatabaseManager.get_dashboard_summary(period)

            expected_cash = float(summary.get("cash") or 0)
            expected_card = float(summary.get("card") or 0)
            total_revenue = float(summary.get("revenue") or 0)

            return {
                "expected_cash": expected_cash,
                "expected_card": expected_card,
                "expected_total": total_revenue,
                "bank_confirmed_card": 0,
                "cash_counted": 0,
                "unreconciled_amount": total_revenue,
                "status": "Pending reconciliation",
                "note": "Bank import and cash count matching will be added in the next version.",
            }

        except Exception as error:
            print(f"Bank reconciliation failed: {error}")
            return {}

    @staticmethod
    def get_monthly_report():
        try:
            summary = BarberDatabaseManager.get_dashboard_summary("month")
            revenue_by_service = BarberDatabaseManager.get_revenue_by_service("month")
            top_customers = BarberDatabaseManager.get_top_customers("month", limit=5)
            trends = BarberDatabaseManager.get_revenue_trends("month")

            return {
                "month": datetime.utcnow().strftime("%B %Y"),
                "summary": summary,
                "revenue_by_service": revenue_by_service,
                "top_customers": top_customers,
                "trends": trends,
                "status": "Report data ready. PDF export will be added next.",
            }

        except Exception as error:
            print(f"Monthly report failed: {error}")
            return {}


if __name__ == "__main__":
    print("Testing connection against Supabase API backend infrastructure...")

    menu = BarberDatabaseManager.fetch_services()
    print(f"Successfully retrieved menu records! Total active services: {len(menu)}")

    for item in menu:
        print(f" - {item.get('service_name') or item.get('name')}: R{item.get('price_zar')}")

    test_phone = "27999999999"
    test_name = "Test"

    saved = BarberDatabaseManager.upsert_client(test_phone, test_name)
    print(f"Client save test: {saved}")

    client = BarberDatabaseManager.get_client(test_phone)
    print(f"Client lookup test: {client}")

    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    generated = BarberDatabaseManager.create_availability_slots_for_day(tomorrow)
    print(f"Tomorrow availability generated: {generated}")

    blocked = BarberDatabaseManager.block_time_range(
        start_datetime=f"{tomorrow}T10:00:00",
        end_datetime=f"{tomorrow}T12:00:00",
        reason="Owner unavailable",
    )
    print(f"Block test: {blocked}")

    slots = BarberDatabaseManager.get_available_slots()
    print(f"Available slots found: {len(slots)}")

    latest_booking = BarberDatabaseManager.get_latest_active_booking(test_phone)
    print(f"Latest active booking test: {latest_booking}")