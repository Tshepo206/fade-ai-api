from datetime import datetime, timedelta
from typing import Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from availability_manager import AvailabilityManager
from booking_manager import BookingManager
from customer_manager import CustomerManager
from personality import get_opening_line
from service_manager import ServiceManager


load_dotenv()


class BarberAgentState(TypedDict):
    business_id: str
    phone_number: str
    current_state: str
    incoming_text: str
    weather_summary: str
    day_of_week: str
    time_of_day: str
    selected_service: Optional[str]
    validated_date: Optional[str]
    validated_time: Optional[str]
    customer_name: Optional[str]
    voice_note_script: Optional[str]
    text_response: str


def build_date_options() -> list[tuple[str, str, str]]:
    today = datetime.now().date()
    options = []

    for index in range(7):
        date_obj = today + timedelta(days=index)
        label = date_obj.strftime("%A %d %B %Y")
        iso_date = date_obj.strftime("%Y-%m-%d")
        options.append((str(index + 1), label, iso_date))

    return options


def format_date_for_customer(iso_date: str) -> str:
    date_obj = datetime.strptime(iso_date, "%Y-%m-%d")
    return date_obj.strftime("%A, %d %B %Y")


def format_booking_datetime(timestamp: str) -> tuple[str, str]:
    clean_timestamp = str(timestamp).replace("Z", "+00:00")
    appointment_dt = datetime.fromisoformat(clean_timestamp)
    return (
        appointment_dt.strftime("%A, %d %B %Y"),
        appointment_dt.strftime("%H:%M"),
    )


def _normalise_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)

    return parsed


def _generate_default_slots_for_day(
    business_id: str,
    target_date: str,
    start_hour: int = 9,
    end_hour: int = 18,
    interval_minutes: int = 30,
) -> None:
    start_dt = datetime.fromisoformat(f"{target_date}T{start_hour:02d}:00:00")
    end_dt = datetime.fromisoformat(f"{target_date}T{end_hour:02d}:00:00")
    current = start_dt

    while current < end_dt:
        AvailabilityManager.create_slot(
            business_id=business_id,
            slot_datetime=current.isoformat(),
        )
        current += timedelta(minutes=interval_minutes)


def get_available_times_for_date(
    business_id: str,
    target_date: str,
) -> list[str]:
    if not business_id:
        return []

    start_dt = datetime.fromisoformat(f"{target_date}T00:00:00")
    end_dt = start_dt + timedelta(days=1)

    slots = AvailabilityManager.get_calendar_slots(
        business_id=business_id,
        start_datetime=start_dt.isoformat(),
        end_datetime=end_dt.isoformat(),
    )

    if not slots:
        _generate_default_slots_for_day(
            business_id=business_id,
            target_date=target_date,
        )

        slots = AvailabilityManager.get_calendar_slots(
            business_id=business_id,
            start_datetime=start_dt.isoformat(),
            end_datetime=end_dt.isoformat(),
        )

    now = datetime.utcnow()
    available_times = []

    for slot in slots:
        if str(slot.get("status") or "").upper() != "AVAILABLE":
            continue

        slot_datetime = slot.get("slot_datetime")

        if not slot_datetime:
            continue

        try:
            slot_dt = _normalise_datetime(slot_datetime)
        except (TypeError, ValueError):
            continue

        if slot_dt <= now:
            continue

        available_times.append(slot_dt.strftime("%H:%M"))

    return sorted(set(available_times))


def get_service_id(
    business_id: str,
    service_name: str,
) -> Optional[int]:
    if not business_id or not service_name:
        return None

    requested_name = service_name.strip().casefold()

    for service in ServiceManager.get_services(business_id):
        stored_name = (
            service.get("service_name")
            or service.get("name")
            or ""
        )

        if str(stored_name).strip().casefold() == requested_name:
            try:
                return int(service.get("id"))
            except (TypeError, ValueError):
                return None

    return None


def get_service_name_from_booking(
    business_id: str,
    booking: dict,
) -> str:
    service_id = booking.get("service_id")

    try:
        service = ServiceManager.get_service_by_id(
            business_id,
            int(service_id),
        )
    except (TypeError, ValueError):
        service = None

    if service:
        return (
            service.get("service_name")
            or service.get("name")
            or "Barber Service"
        )

    return booking.get("service_name") or "Barber Service"


def create_main_menu_text() -> str:
    return (
        "1. Make an appointment\n"
        "2. Reschedule an appointment\n"
        "3. Check existing appointment\n"
        "4. Cancel appointment"
    )


def create_booking_confirmation(
    customer_name: str,
    service_name: str,
    target_date: str,
    chosen_time: str,
) -> str:
    friendly_date = format_date_for_customer(target_date)

    return (
        "✅ *You're booked!*\n\n"
        f"Hi {customer_name},\n\n"
        "Your appointment has been confirmed.\n\n"
        f"💈 *Service*\n{service_name}\n\n"
        f"📅 *Date*\n{friendly_date}\n\n"
        f"🕗 *Time*\n{chosen_time}\n\n"
        "📍 *Location*\n"
        "KG Barber\n"
        "https://maps.google.com/?q=-26.033667,28.035757\n\n"
        "We're looking forward to seeing you!\n\n"
        "If you're running a few minutes late, just send us a WhatsApp message.\n\n"
        "Need to make a change?\n\n"
        "Simply send *Hi* on this WhatsApp chat and choose:\n\n"
        "2️⃣ Reschedule appointment\n"
        "3️⃣ Check existing appointment\n"
        "4️⃣ Cancel appointment\n\n"
        "📲 We'll send you a reminder before your appointment.\n\n"
        "See you soon! 👊💈"
    )


def create_reschedule_confirmation(
    customer_name: str,
    service_name: str,
    old_date: str,
    old_time: str,
    new_date: str,
    new_time: str,
) -> str:
    return (
        "✅ *Your appointment has been rescheduled!*\n\n"
        f"Hi {customer_name},\n\n"
        "Your booking has been moved.\n\n"
        "Previous appointment:\n"
        f"📅 {old_date}\n"
        f"🕗 {old_time}\n\n"
        "New appointment:\n"
        f"💈 *Service*\n{service_name}\n\n"
        f"📅 *Date*\n{format_date_for_customer(new_date)}\n\n"
        f"🕗 *Time*\n{new_time}\n\n"
        "📍 *Location*\n"
        "KG Barber\n"
        "https://maps.google.com/?q=-26.033667,28.035757\n\n"
        "See you then! 👊💈"
    )


def _missing_business_response() -> dict:
    return {
        "current_state": "INITIAL_CONTACT",
        "text_response": (
            "I couldn't identify the business workspace for this message. "
            "Please try again shortly."
        ),
        "voice_note_script": None,
    }


def initial_contact_node(state: BarberAgentState) -> dict:
    day = state.get("day_of_week", "today")
    time = state.get("time_of_day", "day")
    opening_line = get_opening_line(day, time)

    return {
        "current_state": "MAIN_MENU",
        "voice_note_script": None,
        "text_response": (
            f"{opening_line}\n\n"
            "Yo! My name is Fade, *KG Barber's* AI booking assistant 💈\n\n"
            "How can I help you today?\n\n"
            f"{create_main_menu_text()}"
        ),
    }


def main_menu_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()
    business_id = state.get("business_id")
    phone = state.get("phone_number")

    if not business_id:
        return _missing_business_response()

    if text == "1":
        return {
            "current_state": "SELECTING_SERVICE",
            "text_response": (
                "Perfect. What service would you like?\n\n"
                "1. Standard Haircut & Fade\n"
                "2. Beard Trim & Line-up\n"
                "3. The Combo (Hair + Beard)"
            ),
            "voice_note_script": None,
        }

    if text == "2":
        client = CustomerManager.get_customer(business_id, phone)
        booking = BookingManager.get_latest_active_booking(
            business_id,
            phone,
        )

        if not booking:
            return {
                "current_state": "MAIN_MENU",
                "text_response": (
                    "I couldn't find an active booking to reschedule.\n\n"
                    "Would you like to make a new appointment?\n\n"
                    f"{create_main_menu_text()}"
                ),
                "voice_note_script": None,
            }

        customer_name = client.get("first_name", "there") if client else "there"
        service_name = get_service_name_from_booking(business_id, booking)
        old_date, old_time = format_booking_datetime(
            booking.get("appointment_timestamp")
        )

        date_options = build_date_options()
        date_text = "\n".join(
            f"{number}. {label}"
            for number, label, _ in date_options
        )

        return {
            "current_state": "RESCHEDULE_DATE",
            "selected_service": service_name,
            "customer_name": customer_name,
            "text_response": (
                f"Sure {customer_name}, let's move your booking.\n\n"
                "Your current appointment is:\n\n"
                f"💈 *Service*\n{service_name}\n\n"
                f"📅 *Date*\n{old_date}\n\n"
                f"🕗 *Time*\n{old_time}\n\n"
                "Please choose a new date:\n\n"
                f"{date_text}"
            ),
            "voice_note_script": None,
        }

    if text == "3":
        client = CustomerManager.get_customer(business_id, phone)
        booking = BookingManager.get_latest_active_booking(
            business_id,
            phone,
        )

        if not booking:
            return {
                "current_state": "MAIN_MENU",
                "text_response": (
                    "I couldn't find an active booking for this WhatsApp number.\n\n"
                    "Would you like to make one?\n\n"
                    f"{create_main_menu_text()}"
                ),
                "voice_note_script": None,
            }

        customer_name = client.get("first_name", "there") if client else "there"
        service_name = get_service_name_from_booking(business_id, booking)
        friendly_date, friendly_time = format_booking_datetime(
            booking.get("appointment_timestamp")
        )

        return {
            "current_state": "MAIN_MENU",
            "text_response": (
                f"Hi {customer_name} 👋\n\n"
                "Your next appointment is:\n\n"
                f"💈 *Service*\n{service_name}\n\n"
                f"📅 *Date*\n{friendly_date}\n\n"
                f"🕗 *Time*\n{friendly_time}\n\n"
                "📍 *Location*\n"
                "KG Barber\n"
                "https://maps.google.com/?q=-26.033667,28.035757\n\n"
                "Need to make a change?\n\n"
                "2️⃣ Reschedule appointment\n"
                "4️⃣ Cancel appointment"
            ),
            "voice_note_script": None,
        }

    if text == "4":
        client = CustomerManager.get_customer(business_id, phone)
        booking = BookingManager.get_latest_active_booking(
            business_id,
            phone,
        )

        if not booking:
            return {
                "current_state": "MAIN_MENU",
                "text_response": (
                    "I couldn't find an active booking to cancel.\n\n"
                    "Please choose an option:\n\n"
                    f"{create_main_menu_text()}"
                ),
                "voice_note_script": None,
            }

        customer_name = client.get("first_name", "there") if client else "there"
        service_name = get_service_name_from_booking(business_id, booking)
        friendly_date, friendly_time = format_booking_datetime(
            booking.get("appointment_timestamp")
        )

        return {
            "current_state": "CANCEL_CONFIRMATION",
            "customer_name": customer_name,
            "selected_service": service_name,
            "text_response": (
                f"Sure {customer_name}, I found your booking:\n\n"
                f"💈 *Service*\n{service_name}\n\n"
                f"📅 *Date*\n{friendly_date}\n\n"
                f"🕗 *Time*\n{friendly_time}\n\n"
                "Are you sure you want to cancel this appointment?\n\n"
                "1. Yes, cancel it\n"
                "2. No, keep it"
            ),
            "voice_note_script": None,
        }

    return {
        "current_state": "MAIN_MENU",
        "text_response": (
            "Please reply with a number:\n\n"
            + create_main_menu_text()
        ),
        "voice_note_script": None,
    }


def service_selection_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()

    service_mapping = {
        "1": "Standard Haircut & Fade",
        "2": "Beard Trim & Line-up",
        "3": "The Combo (Hair + Beard)",
    }

    if text not in service_mapping:
        return {
            "current_state": "SELECTING_SERVICE",
            "text_response": (
                "Please choose a service by replying with a number:\n\n"
                "1. Standard Haircut & Fade\n"
                "2. Beard Trim & Line-up\n"
                "3. The Combo (Hair + Beard)"
            ),
            "voice_note_script": None,
        }

    chosen_service = service_mapping[text]
    date_options = build_date_options()
    date_text = "\n".join(
        f"{number}. {label}"
        for number, label, _ in date_options
    )

    return {
        "current_state": "SELECTING_DATE",
        "selected_service": chosen_service,
        "text_response": (
            f"Got it. You selected *{chosen_service}*.\n\n"
            "What day works for you?\n\n"
            f"{date_text}"
        ),
        "voice_note_script": None,
    }


def date_selection_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()
    business_id = state.get("business_id")

    if not business_id:
        return _missing_business_response()

    date_options = build_date_options()
    date_mapping = {
        number: iso_date
        for number, _, iso_date in date_options
    }

    if text not in date_mapping:
        date_text = "\n".join(
            f"{number}. {label}"
            for number, label, _ in date_options
        )
        return {
            "current_state": "SELECTING_DATE",
            "text_response": (
                "Please choose a date by replying with a number:\n\n"
                + date_text
            ),
            "voice_note_script": None,
        }

    selected_date = date_mapping[text]
    available_slots = get_available_times_for_date(
        business_id,
        selected_date,
    )

    if not available_slots:
        return {
            "current_state": "SELECTING_DATE",
            "validated_date": selected_date,
            "text_response": (
                "KG Barber is fully booked on "
                f"{format_date_for_customer(selected_date)}.\n\n"
                "Please choose another date."
            ),
            "voice_note_script": None,
        }

    slots_to_show = available_slots[:8]
    slot_text = "\n".join(
        f"{index + 1}. {slot}"
        for index, slot in enumerate(slots_to_show)
    )

    return {
        "current_state": "SELECTING_SLOT",
        "validated_date": selected_date,
        "text_response": (
            "Nice. These times are available on "
            f"*{format_date_for_customer(selected_date)}*:\n\n"
            f"{slot_text}\n\n"
            "Reply with the number for the time you want."
        ),
        "voice_note_script": None,
    }


def slot_selection_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()
    business_id = state.get("business_id")
    phone = state.get("phone_number")
    target_date = state.get("validated_date")
    service_name = (
        state.get("selected_service")
        or "Standard Haircut & Fade"
    )

    if not business_id:
        return _missing_business_response()

    if not target_date:
        return {
            "current_state": "SELECTING_DATE",
            "text_response": "Please choose your booking date first.",
            "voice_note_script": None,
        }

    available_slots = get_available_times_for_date(
        business_id,
        target_date,
    )
    slots_to_show = available_slots[:8]

    try:
        slot_index = int(text) - 1
        if slot_index < 0:
            raise ValueError
        chosen_time = slots_to_show[slot_index]
    except (ValueError, IndexError):
        slot_text = "\n".join(
            f"{index + 1}. {slot}"
            for index, slot in enumerate(slots_to_show)
        )
        return {
            "current_state": "SELECTING_SLOT",
            "text_response": (
                "Please choose a time by replying with a number:\n\n"
                + slot_text
            ),
            "voice_note_script": None,
        }

    service_id = get_service_id(business_id, service_name)

    if service_id is None:
        return {
            "current_state": "SELECTING_SERVICE",
            "text_response": (
                "I couldn't match that service to this business's service list. "
                "Please choose the service again."
            ),
            "voice_note_script": None,
        }

    existing_client = CustomerManager.get_customer(
        business_id,
        phone,
    )

    if existing_client:
        customer_name = existing_client.get("first_name", "there")
        final_timestamp = f"{target_date}T{chosen_time}:00"

        db_result = BookingManager.insert_booking(
            business_id=business_id,
            phone_number=phone,
            service_id=service_id,
            timestamp_str=final_timestamp,
        )

        if not db_result:
            return {
                "current_state": "SELECTING_SLOT",
                "text_response": (
                    "That slot may have just been taken. "
                    "Please choose another time."
                ),
                "voice_note_script": None,
            }

        return {
            "current_state": "BOOKED",
            "validated_time": chosen_time,
            "customer_name": customer_name,
            "text_response": create_booking_confirmation(
                customer_name,
                service_name,
                target_date,
                chosen_time,
            ),
            "voice_note_script": None,
        }

    return {
        "current_state": "COLLECTING_NAME",
        "validated_time": chosen_time,
        "text_response": (
            "Perfect 👍\n\n"
            "Before I confirm your booking, what's your name?"
        ),
        "voice_note_script": None,
    }


def reschedule_date_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()
    business_id = state.get("business_id")

    if not business_id:
        return _missing_business_response()

    date_options = build_date_options()
    date_mapping = {
        number: iso_date
        for number, _, iso_date in date_options
    }

    if text not in date_mapping:
        date_text = "\n".join(
            f"{number}. {label}"
            for number, label, _ in date_options
        )
        return {
            "current_state": "RESCHEDULE_DATE",
            "text_response": (
                "Please choose a new date by replying with a number:\n\n"
                + date_text
            ),
            "voice_note_script": None,
        }

    selected_date = date_mapping[text]
    available_slots = get_available_times_for_date(
        business_id,
        selected_date,
    )

    if not available_slots:
        return {
            "current_state": "RESCHEDULE_DATE",
            "validated_date": selected_date,
            "text_response": (
                "KG Barber is fully booked on "
                f"{format_date_for_customer(selected_date)}.\n\n"
                "Please choose another date."
            ),
            "voice_note_script": None,
        }

    slots_to_show = available_slots[:8]
    slot_text = "\n".join(
        f"{index + 1}. {slot}"
        for index, slot in enumerate(slots_to_show)
    )

    return {
        "current_state": "RESCHEDULE_SLOT",
        "validated_date": selected_date,
        "text_response": (
            "Nice. These times are available on "
            f"*{format_date_for_customer(selected_date)}*:\n\n"
            f"{slot_text}\n\n"
            "Reply with the number for the new time you want."
        ),
        "voice_note_script": None,
    }


def reschedule_slot_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()
    business_id = state.get("business_id")
    phone = state.get("phone_number")
    target_date = state.get("validated_date")

    if not business_id:
        return _missing_business_response()

    if not target_date:
        return {
            "current_state": "RESCHEDULE_DATE",
            "text_response": "Please choose your new date first.",
            "voice_note_script": None,
        }

    booking = BookingManager.get_latest_active_booking(
        business_id,
        phone,
    )

    if not booking:
        return {
            "current_state": "MAIN_MENU",
            "text_response": (
                "I couldn't find an active booking to reschedule.\n\n"
                "Please choose an option:\n\n"
                f"{create_main_menu_text()}"
            ),
            "voice_note_script": None,
        }

    old_date, old_time = format_booking_datetime(
        booking.get("appointment_timestamp")
    )
    service_name = get_service_name_from_booking(
        business_id,
        booking,
    )

    client = CustomerManager.get_customer(business_id, phone)
    customer_name = client.get("first_name", "there") if client else "there"

    available_slots = get_available_times_for_date(
        business_id,
        target_date,
    )
    slots_to_show = available_slots[:8]

    try:
        slot_index = int(text) - 1
        if slot_index < 0:
            raise ValueError
        chosen_time = slots_to_show[slot_index]
    except (ValueError, IndexError):
        slot_text = "\n".join(
            f"{index + 1}. {slot}"
            for index, slot in enumerate(slots_to_show)
        )
        return {
            "current_state": "RESCHEDULE_SLOT",
            "text_response": (
                "Please choose a new time by replying with a number:\n\n"
                + slot_text
            ),
            "voice_note_script": None,
        }

    new_timestamp = f"{target_date}T{chosen_time}:00"

    updated_booking = BookingManager.reschedule_latest_booking(
        business_id=business_id,
        phone_number=phone,
        new_timestamp_str=new_timestamp,
    )

    if not updated_booking:
        return {
            "current_state": "RESCHEDULE_SLOT",
            "text_response": (
                "That time may have just been taken. "
                "Please choose another time."
            ),
            "voice_note_script": None,
        }

    return {
        "current_state": "BOOKED",
        "validated_date": target_date,
        "validated_time": chosen_time,
        "selected_service": service_name,
        "customer_name": customer_name,
        "text_response": create_reschedule_confirmation(
            customer_name,
            service_name,
            old_date,
            old_time,
            target_date,
            chosen_time,
        ),
        "voice_note_script": None,
    }


def collecting_name_node(state: BarberAgentState) -> dict:
    business_id = state.get("business_id")
    phone = state.get("phone_number")
    customer_name = state.get("incoming_text", "").strip().title()
    target_date = state.get("validated_date")
    chosen_time = state.get("validated_time")
    service_name = (
        state.get("selected_service")
        or "Standard Haircut & Fade"
    )

    if not business_id:
        return _missing_business_response()

    if len(customer_name) < 2:
        return {
            "current_state": "COLLECTING_NAME",
            "text_response": (
                "Please send your name so I can confirm the booking."
            ),
            "voice_note_script": None,
        }

    if not target_date or not chosen_time:
        return {
            "current_state": "SELECTING_DATE",
            "text_response": "Please choose your booking date and time again.",
            "voice_note_script": None,
        }

    customer_result = CustomerManager.create_or_update_customer(
        business_id=business_id,
        phone_number=phone,
        customer_name=customer_name,
    )

    if not customer_result.get("success"):
        return {
            "current_state": "COLLECTING_NAME",
            "text_response": (
                "I couldn't save your details. Please send your name again."
            ),
            "voice_note_script": None,
        }

    service_id = get_service_id(business_id, service_name)

    if service_id is None:
        return {
            "current_state": "SELECTING_SERVICE",
            "text_response": (
                "I couldn't match that service to this business's service list. "
                "Please choose the service again."
            ),
            "voice_note_script": None,
        }

    final_timestamp = f"{target_date}T{chosen_time}:00"

    db_result = BookingManager.insert_booking(
        business_id=business_id,
        phone_number=phone,
        service_id=service_id,
        timestamp_str=final_timestamp,
    )

    if not db_result:
        return {
            "current_state": "SELECTING_SLOT",
            "text_response": (
                "That slot may have just been taken. "
                "Please choose another time."
            ),
            "voice_note_script": None,
        }

    return {
        "current_state": "BOOKED",
        "customer_name": customer_name,
        "text_response": create_booking_confirmation(
            customer_name,
            service_name,
            target_date,
            chosen_time,
        ),
        "voice_note_script": None,
    }


def cancel_confirmation_node(state: BarberAgentState) -> dict:
    text = state.get("incoming_text", "").strip()
    business_id = state.get("business_id")
    phone = state.get("phone_number")

    if not business_id:
        return _missing_business_response()

    if text == "1":
        cancelled_booking = BookingManager.cancel_latest_booking(
            business_id,
            phone,
        )

        if not cancelled_booking:
            return {
                "current_state": "MAIN_MENU",
                "text_response": (
                    "I couldn't find an active booking to cancel.\n\n"
                    "Please choose an option:\n\n"
                    f"{create_main_menu_text()}"
                ),
                "voice_note_script": None,
            }

        return {
            "current_state": "INITIAL_CONTACT",
            "selected_service": None,
            "validated_date": None,
            "validated_time": None,
            "customer_name": None,
            "text_response": (
                "✅ *Your appointment has been cancelled.*\n\n"
                "No stress — these things happen.\n\n"
                "When you're ready for another fresh cut, just send *Hi*."
            ),
            "voice_note_script": None,
        }

    if text == "2":
        return {
            "current_state": "MAIN_MENU",
            "text_response": (
                "No problem — your appointment is still confirmed. 👍\n\n"
                "Please choose an option:\n\n"
                f"{create_main_menu_text()}"
            ),
            "voice_note_script": None,
        }

    return {
        "current_state": "CANCEL_CONFIRMATION",
        "text_response": (
            "Please reply with a number:\n\n"
            "1. Yes, cancel it\n"
            "2. No, keep it"
        ),
        "voice_note_script": None,
    }


def booked_node(state: BarberAgentState) -> dict:
    return {
        "current_state": "INITIAL_CONTACT",
        "selected_service": None,
        "validated_date": None,
        "validated_time": None,
        "customer_name": None,
        "text_response": (
            "You already have a confirmed booking.\n\n"
            "To start again, type *Hi*."
        ),
        "voice_note_script": None,
    }


def route_by_current_state(state: BarberAgentState) -> str:
    current_state = state.get("current_state", "INITIAL_CONTACT")

    routes = {
        "INITIAL_CONTACT": "initial_contact",
        "MAIN_MENU": "main_menu",
        "SELECTING_SERVICE": "service_selection",
        "SELECTING_DATE": "date_selection",
        "SELECTING_SLOT": "slot_selection",
        "COLLECTING_NAME": "collecting_name",
        "BOOKED": "booked",
        "RESCHEDULE_DATE": "reschedule_date",
        "RESCHEDULE_SLOT": "reschedule_slot",
        "CANCEL_CONFIRMATION": "cancel_confirmation",
    }

    return routes.get(current_state, "initial_contact")


workflow = StateGraph(BarberAgentState)

workflow.add_node("initial_contact", initial_contact_node)
workflow.add_node("main_menu", main_menu_node)
workflow.add_node("service_selection", service_selection_node)
workflow.add_node("date_selection", date_selection_node)
workflow.add_node("slot_selection", slot_selection_node)
workflow.add_node("collecting_name", collecting_name_node)
workflow.add_node("booked", booked_node)
workflow.add_node("reschedule_date", reschedule_date_node)
workflow.add_node("reschedule_slot", reschedule_slot_node)
workflow.add_node("cancel_confirmation", cancel_confirmation_node)

workflow.set_conditional_entry_point(
    route_by_current_state,
    {
        "initial_contact": "initial_contact",
        "main_menu": "main_menu",
        "service_selection": "service_selection",
        "date_selection": "date_selection",
        "slot_selection": "slot_selection",
        "collecting_name": "collecting_name",
        "booked": "booked",
        "reschedule_date": "reschedule_date",
        "reschedule_slot": "reschedule_slot",
        "cancel_confirmation": "cancel_confirmation",
    },
)

workflow.add_edge("initial_contact", END)
workflow.add_edge("main_menu", END)
workflow.add_edge("service_selection", END)
workflow.add_edge("date_selection", END)
workflow.add_edge("slot_selection", END)
workflow.add_edge("collecting_name", END)
workflow.add_edge("booked", END)
workflow.add_edge("reschedule_date", END)
workflow.add_edge("reschedule_slot", END)
workflow.add_edge("cancel_confirmation", END)

agent_engine = workflow.compile()


if __name__ == "__main__":
    test_state: BarberAgentState = {
        "business_id": "replace-with-a-real-business-id",
        "phone_number": "27633732799",
        "current_state": "SELECTING_SLOT",
        "incoming_text": "1",
        "weather_summary": "",
        "day_of_week": "Monday",
        "time_of_day": "afternoon",
        "selected_service": "Standard Haircut & Fade",
        "validated_date": (
            datetime.utcnow() + timedelta(days=1)
        ).strftime("%Y-%m-%d"),
        "validated_time": None,
        "customer_name": None,
        "voice_note_script": None,
        "text_response": "",
    }

    result = agent_engine.invoke(test_state)
    print(result)