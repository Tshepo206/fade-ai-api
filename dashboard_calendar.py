from datetime import datetime, timedelta
from db_manager import supabase, BarberDatabaseManager


class DashboardCalendarManager:
    """Builds day, week, and month calendar views for the Fade AI dashboard."""

    @staticmethod
    def _get_range(view: str):
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if view == "day":
            start_date = today_start
            end_date = start_date + timedelta(days=1)

        elif view == "week":
            start_date = today_start - timedelta(days=today_start.weekday())
            end_date = start_date + timedelta(days=7)

        elif view == "month":
            start_date = today_start.replace(day=1)

            if start_date.month == 12:
                end_date = start_date.replace(
                    year=start_date.year + 1,
                    month=1,
                    day=1,
                )
            else:
                end_date = start_date.replace(
                    month=start_date.month + 1,
                    day=1,
                )

        else:
            start_date = today_start
            end_date = start_date + timedelta(days=1)

        return start_date, end_date

    @staticmethod
    def get_calendar_bookings(view: str = "day"):
        try:
            start_date, end_date = DashboardCalendarManager._get_range(view)

            response = (
                supabase.table("bookings")
                .select("*")
                .gte("appointment_timestamp", start_date.isoformat())
                .lt("appointment_timestamp", end_date.isoformat())
                .neq("status", "CANCELLED")
                .order("appointment_timestamp")
                .execute()
            )

            bookings = response.data or []
            enriched = BarberDatabaseManager._enrich_bookings(bookings)

            return {
                "view": view,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "count": len(enriched),
                "bookings": enriched,
            }

        except Exception as error:
            print(f"Calendar bookings lookup failed: {error}")

            return {
                "view": view,
                "start_date": None,
                "end_date": None,
                "count": 0,
                "bookings": [],
            }

    @staticmethod
    def group_bookings_by_day(bookings: list):
        grouped = {}

        for booking in bookings:
            timestamp = booking.get("appointment_timestamp")

            if not timestamp:
                continue

            booking_datetime = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

            day_key = booking_datetime.strftime("%Y-%m-%d")

            if day_key not in grouped:
                grouped[day_key] = []

            grouped[day_key].append(booking)

        return grouped