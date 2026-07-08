from datetime import datetime, timedelta
from db_manager import supabase


class BarberCalendarManager:
    """Coordinates available booking slots and blocked barber times."""

    @staticmethod
    def get_open_slots_for_day(target_date_str: str) -> list:
        try:
            start_bound = f"{target_date_str}T00:00:00"
            end_bound = f"{target_date_str}T23:59:59"

            bookings_response = (
                supabase.table("bookings")
                .select("appointment_timestamp")
                .gte("appointment_timestamp", start_bound)
                .lte("appointment_timestamp", end_bound)
                .neq("status", "CANCELLED")
                .execute()
            )

            blocked_response = (
                supabase.table("blocked_availability")
                .select("*")
                .lt("block_start", end_bound)
                .gt("block_end", start_bound)
                .execute()
            )

            unavailable_times = set()

            for booking in bookings_response.data or []:
                timestamp = booking.get("appointment_timestamp")

                if timestamp:
                    clean_timestamp = timestamp.replace("Z", "+00:00")
                    booked_time = datetime.fromisoformat(clean_timestamp).strftime("%H:%M")
                    unavailable_times.add(booked_time)

            for block in blocked_response.data or []:
                block_start = datetime.fromisoformat(
                    block["block_start"].replace("Z", "+00:00")
                )
                block_end = datetime.fromisoformat(
                    block["block_end"].replace("Z", "+00:00")
                )

                current = block_start

                while current < block_end:
                    unavailable_times.add(current.strftime("%H:%M"))
                    current += timedelta(minutes=30)

            all_slots = []

            current_time = datetime.strptime("08:00", "%H:%M")
            end_time = datetime.strptime("17:00", "%H:%M")

            while current_time < end_time:
                slot_str = current_time.strftime("%H:%M")

                if slot_str not in unavailable_times:
                    all_slots.append(slot_str)

                current_time += timedelta(minutes=30)

            return all_slots

        except Exception as error:
            print(f"Calendar search query failure: {error}")
            return []

    @staticmethod
    def block_availability(
        block_start: datetime,
        block_end: datetime,
        reason: str = "Owner blocked availability",
    ) -> bool:
        try:
            data = {
                "block_start": block_start.isoformat(),
                "block_end": block_end.isoformat(),
                "reason": reason,
            }

            response = supabase.table("blocked_availability").insert(data).execute()

            print("[Blocked Availability Saved]")
            print(response.data)

            return True

        except Exception as error:
            print(f"Blocked availability save failed: {error}")
            return False