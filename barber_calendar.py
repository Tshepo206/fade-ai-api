from datetime import datetime, timedelta

from db_manager import supabase


class BarberCalendarManager:
    """Coordinates tenant-scoped booking slots and blocked barber times."""

    @staticmethod
    def get_open_slots_for_day(
        business_id: str,
        target_date_str: str,
    ) -> list:
        if not business_id or not target_date_str:
            return []

        try:
            start_dt = datetime.fromisoformat(
                f"{target_date_str}T00:00:00"
            )
            end_dt = start_dt + timedelta(days=1)

            bookings_response = (
                supabase.table("bookings")
                .select("appointment_timestamp")
                .eq("business_id", business_id)
                .gte(
                    "appointment_timestamp",
                    start_dt.isoformat(),
                )
                .lt(
                    "appointment_timestamp",
                    end_dt.isoformat(),
                )
                .neq("status", "CANCELLED")
                .execute()
            )

            blocked_response = (
                supabase.table("blocked_availability")
                .select("*")
                .eq("business_id", business_id)
                .lt("block_start", end_dt.isoformat())
                .gt("block_end", start_dt.isoformat())
                .execute()
            )

            unavailable_times = set()

            for booking in bookings_response.data or []:
                timestamp = booking.get(
                    "appointment_timestamp"
                )

                if not timestamp:
                    continue

                clean_timestamp = timestamp.replace(
                    "Z",
                    "+00:00",
                )

                booked_time = datetime.fromisoformat(
                    clean_timestamp
                ).strftime("%H:%M")

                unavailable_times.add(booked_time)

            for block in blocked_response.data or []:
                block_start_value = block.get("block_start")
                block_end_value = block.get("block_end")

                if not block_start_value or not block_end_value:
                    continue

                block_start = datetime.fromisoformat(
                    block_start_value.replace("Z", "+00:00")
                )

                block_end = datetime.fromisoformat(
                    block_end_value.replace("Z", "+00:00")
                )

                current = block_start

                while current < block_end:
                    if current.date() == start_dt.date():
                        unavailable_times.add(
                            current.strftime("%H:%M")
                        )

                    current += timedelta(minutes=30)

            all_slots = []

            current_time = datetime.fromisoformat(
                f"{target_date_str}T08:00:00"
            )

            closing_time = datetime.fromisoformat(
                f"{target_date_str}T17:00:00"
            )

            now = datetime.utcnow()

            while current_time < closing_time:
                slot_str = current_time.strftime("%H:%M")

                if (
                    current_time > now
                    and slot_str not in unavailable_times
                ):
                    all_slots.append(slot_str)

                current_time += timedelta(minutes=30)

            return all_slots

        except Exception as error:
            print(
                f"Tenant calendar search query failure: {error}"
            )
            return []

    @staticmethod
    def block_availability(
        business_id: str,
        block_start: datetime,
        block_end: datetime,
        reason: str = "Owner blocked availability",
        created_by: str = "OWNER",
    ) -> bool:
        if not business_id:
            return False

        if not block_start or not block_end:
            return False

        if block_end <= block_start:
            return False

        try:
            data = {
                "business_id": business_id,
                "block_start": block_start.isoformat(),
                "block_end": block_end.isoformat(),
                "reason": reason,
                "created_by": created_by,
            }

            response = (
                supabase.table("blocked_availability")
                .insert(data)
                .execute()
            )

            if not response.data:
                return False

            current = block_start

            while current < block_end:
                slot_datetime = current.isoformat()

                existing_slot = (
                    supabase.table("availability_slots")
                    .select("status")
                    .eq("business_id", business_id)
                    .eq("slot_datetime", slot_datetime)
                    .limit(1)
                    .execute()
                )

                existing_status = (
                    existing_slot.data[0].get("status")
                    if existing_slot.data
                    else None
                )

                if existing_status != "BOOKED":
                    (
                        supabase.table("availability_slots")
                        .upsert(
                            {
                                "business_id": business_id,
                                "slot_datetime": slot_datetime,
                                "status": "BLOCKED",
                                "booking_id": None,
                                "blocked_reason": reason,
                                "updated_at": (
                                    datetime.utcnow().isoformat()
                                ),
                            },
                            on_conflict=(
                                "business_id,slot_datetime"
                            ),
                        )
                        .execute()
                    )

                current += timedelta(minutes=30)

            print("[Tenant Blocked Availability Saved]")
            print(response.data)

            return True

        except Exception as error:
            print(
                f"Tenant blocked availability save failed: "
                f"{error}"
            )
            return False