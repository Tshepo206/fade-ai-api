from datetime import datetime, timedelta

from bookkeeping import (
    extract_transaction,
    format_transaction_confirmation,
    get_follow_up_question,
    merge_transaction_update,
)
from db_manager import BarberDatabaseManager


def save_transaction_to_ledger(transaction: dict) -> bool:
    return BarberDatabaseManager.record_transaction(
        customer_name=transaction.get("customer"),
        service_name=transaction.get("service"),
        amount=transaction.get("amount"),
        payment_method=transaction.get("payment_method"),
        transaction_type=transaction.get("transaction_type", "Service"),
    )


def handle_pending_transaction(phone_number: str, message_text: str) -> str:
    pending = BarberDatabaseManager.get_pending_transaction(phone_number)

    if not pending:
        return ""

    pending_transaction = pending.get("transaction_json") or {}
    missing_field = pending.get("missing_field")

    updated_transaction = merge_transaction_update(
        pending_transaction=pending_transaction,
        field=missing_field,
        answer=message_text,
    )

    missing_fields = updated_transaction.get("missing_fields", [])

    if missing_fields:
        next_missing_field = missing_fields[0]

        BarberDatabaseManager.save_pending_transaction(
            phone_number=phone_number,
            transaction=updated_transaction,
            missing_field=next_missing_field,
        )

        return get_follow_up_question(next_missing_field)

    save_success = save_transaction_to_ledger(updated_transaction)
    BarberDatabaseManager.delete_pending_transaction(phone_number)

    if not save_success:
        return "⚠️ I understood the transaction, but I could not save it to the ledger."

    return format_transaction_confirmation(updated_transaction).replace(
        "✅ Transaction recorded.",
        "✅ Transaction recorded and saved.",
    )


def looks_like_block_command(message_text: str) -> bool:
    text = message_text.lower().strip()

    block_keywords = [
        "block",
        "unavailable",
        "not available",
        "closed",
        "off tomorrow",
        "off today",
    ]

    return any(keyword in text for keyword in block_keywords)


def looks_like_bookkeeping(message_text: str) -> bool:
    text = message_text.lower().strip()

    money_keywords = ["r", "cash", "card", "paid", "payment"]
    service_keywords = [
        "haircut",
        "cut",
        "shave",
        "beard",
        "combo",
        "blade",
        "dye",
        "bleach",
        "powder",
    ]

    has_money_signal = any(keyword in text for keyword in money_keywords)
    has_service_signal = any(keyword in text for keyword in service_keywords)

    return has_money_signal or has_service_signal


def handle_typed_bookkeeping(phone_number: str, message_text: str) -> str:
    transaction = extract_transaction(message_text)
    missing_fields = transaction.get("missing_fields", [])

    if missing_fields:
        first_missing_field = missing_fields[0]

        BarberDatabaseManager.save_pending_transaction(
            phone_number=phone_number,
            transaction=transaction,
            missing_field=first_missing_field,
        )

        return get_follow_up_question(first_missing_field)

    save_success = save_transaction_to_ledger(transaction)

    if not save_success:
        return "⚠️ I understood the transaction, but I could not save it to the ledger."

    return format_transaction_confirmation(transaction).replace(
        "✅ Transaction recorded.",
        "✅ Transaction recorded and saved.",
    )


def get_next_weekday(target_weekday: int) -> datetime:
    today = datetime.now()
    days_ahead = target_weekday - today.weekday()

    if days_ahead < 0:
        days_ahead += 7

    return today + timedelta(days=days_ahead)


def parse_block_command(message_text: str):
    text = message_text.lower().strip()
    now = datetime.now()

    target_date = now

    if "tomorrow" in text:
        target_date = now + timedelta(days=1)
    elif "monday" in text:
        target_date = get_next_weekday(0)
    elif "tuesday" in text:
        target_date = get_next_weekday(1)
    elif "wednesday" in text:
        target_date = get_next_weekday(2)
    elif "thursday" in text:
        target_date = get_next_weekday(3)
    elif "friday" in text:
        target_date = get_next_weekday(4)
    elif "saturday" in text:
        target_date = get_next_weekday(5)
    elif "sunday" in text:
        target_date = get_next_weekday(6)

    if "morning" in text:
        start_time = "08:00"
        end_time = "12:00"
    elif "afternoon" in text:
        start_time = "12:00"
        end_time = "17:00"
    elif "evening" in text:
        start_time = "17:00"
        end_time = "20:00"
    elif "2pm-4pm" in text or "2pm to 4pm" in text:
        start_time = "14:00"
        end_time = "16:00"
    elif "3pm-5pm" in text or "3pm to 5pm" in text:
        start_time = "15:00"
        end_time = "17:00"
    elif "10am-12pm" in text or "10am to 12pm" in text:
        start_time = "10:00"
        end_time = "12:00"
    else:
        start_time = "08:00"
        end_time = "17:00"

    block_start = datetime.strptime(
        f"{target_date.strftime('%Y-%m-%d')} {start_time}",
        "%Y-%m-%d %H:%M",
    )

    block_end = datetime.strptime(
        f"{target_date.strftime('%Y-%m-%d')} {end_time}",
        "%Y-%m-%d %H:%M",
    )

    return block_start, block_end


def handle_block_availability(message_text: str) -> str:
    block_start, block_end = parse_block_command(message_text)

    saved = BarberDatabaseManager.block_time_range(
        start_datetime=block_start.isoformat(),
        end_datetime=block_end.isoformat(),
        reason=message_text,
        created_by="OWNER",
    )

    if not saved:
        return "⚠️ I understood the block command, but I could not save it."

    return (
        "✅ Availability blocked.\n\n"
        f"Date: {block_start.strftime('%A, %d %B %Y')}\n"
        f"Time: {block_start.strftime('%H:%M')} - {block_end.strftime('%H:%M')}"
    )


def handle_owner_text_message(phone_number: str, message_text: str) -> str:
    clean_message = message_text.strip()

    pending = BarberDatabaseManager.get_pending_transaction(phone_number)

    if pending:
        return handle_pending_transaction(
            phone_number=phone_number,
            message_text=clean_message,
        )

    if looks_like_block_command(clean_message):
        return handle_block_availability(clean_message)

    if looks_like_bookkeeping(clean_message):
        return handle_typed_bookkeeping(
            phone_number=phone_number,
            message_text=clean_message,
        )

    return (
        "I’m ready. You can send me sales like:\n\n"
        "Tshepo haircut R180 cash\n\n"
        "Or block time like:\n\n"
        "Block tomorrow\n"
        "Block today 2pm-4pm"
    )

if __name__ == "__main__":
    response = handle_owner_text_message(
        phone_number="27633732799",
        message_text="Block tomorrow 2pm-4pm",
    )

    print(response)