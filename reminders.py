import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def send_whatsapp_message(to_number: str, message_text: str):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message_text
        },
    }

    response = requests.post(url, headers=headers, json=data)

    print("WhatsApp reminder response:")
    print("Status:", response.status_code)
    print("Body:", response.text)

    return response


def format_booking_datetime(timestamp: str):
    clean_timestamp = timestamp.replace("Z", "+00:00")
    appointment_dt = datetime.fromisoformat(clean_timestamp)

    friendly_date = appointment_dt.strftime("%A, %d %B %Y")
    friendly_time = appointment_dt.strftime("%H:%M")

    return friendly_date, friendly_time


def get_service_name(service_id: int):
    try:
        response = (
            supabase
            .table("services")
            .select("*")
            .eq("id", service_id)
            .execute()
        )

        if response.data:
            return response.data[0].get("service_name", "Barber Service")

    except Exception as error:
        print("Service lookup failed:", error)

    return "Barber Service"


def send_24h_reminders():
    now = datetime.now()
    start_time = now + timedelta(hours=23)
    end_time = now + timedelta(hours=25)

    print("Checking 24-hour reminders...")
    print("Window start:", start_time.isoformat())
    print("Window end:", end_time.isoformat())

    response = (
        supabase
        .table("bookings")
        .select("*")
        .eq("status", "PENDING")
        .eq("reminder_24h_sent", False)
        .gte("appointment_timestamp", start_time.isoformat())
        .lte("appointment_timestamp", end_time.isoformat())
        .execute()
    )

    bookings = response.data or []

    print(f"Found {len(bookings)} booking(s) needing 24h reminders.")

    for booking in bookings:
        phone_number = booking["phone_number"]
        service_name = get_service_name(booking.get("service_id"))
        friendly_date, friendly_time = format_booking_datetime(
            booking["appointment_timestamp"]
        )

        client_response = (
            supabase
            .table("clients")
            .select("*")
            .eq("phone_number", phone_number)
            .execute()
        )

        customer_name = "there"

        if client_response.data:
            customer_name = client_response.data[0].get("first_name", "there")

        message = (
            f"Hi {customer_name} 👋\n\n"
            "Just a reminder that your appointment with KG Barber is tomorrow.\n\n"
            f"💈 *Service*\n{service_name}\n\n"
            f"📅 *Date*\n{friendly_date}\n\n"
            f"🕗 *Time*\n{friendly_time}\n\n"
            "See you soon 💈"
        )

        send_result = send_whatsapp_message(phone_number, message)

        if send_result.status_code in [200, 201]:
            (
                supabase
                .table("bookings")
                .update({"reminder_24h_sent": True})
                .eq("id", booking["id"])
                .execute()
            )

            print(f"24h reminder marked as sent for booking {booking['id']}")
        else:
            print(f"Reminder failed for booking {booking['id']}")


if __name__ == "__main__":
    send_24h_reminders()