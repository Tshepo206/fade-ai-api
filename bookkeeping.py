import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def extract_transaction(text: str) -> dict:
    system_prompt = """
You are Fade AI's bookkeeping assistant for a South African barber shop.

Extract transaction data from barber messages or voice transcripts.

Examples:

"Thabo haircut 250 card"
customer: Thabo
service: Haircut
amount: 250
payment_method: Card
transaction_type: Service
description: Haircut

"Tshepo R180 cash"
customer: Tshepo
service: null
amount: 180
payment_method: Cash
transaction_type: Service
description: Service income

"Bought towels R300 cash"
customer: null
service: Towels
amount: 300
payment_method: Cash
transaction_type: Expense
description: Bought towels

"Bought some hair clippers for 550"
customer: null
service: Hair clippers
amount: 550
payment_method: null
transaction_type: Expense
description: Bought hair clippers

Rules:
- Bought, purchased, paid for, spent, rent, electricity, supplies, stock, petrol, lunch, towels, clippers, equipment are Expense transactions.
- Haircut, shave, combo, beard trim, blade cut, dye, bleach, powder are Service transactions.
- Expenses do not have customers.
- Card means Card.
- Cash means Cash.
- Amount must be a number only.
- If a field is missing, return null.
- Return only JSON.
"""

    user_prompt = f"""
Message or transcript:
{text}

Return JSON with exactly these fields:
customer
service
amount
payment_method
transaction_type
description
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw_json = response.choices[0].message.content.strip()

    print("[Bookkeeping Raw JSON]")
    print(raw_json)

    try:
        transaction = json.loads(raw_json)
    except Exception as error:
        print(f"[Bookkeeping JSON Parse Error] {error}")
        transaction = {}

    transaction_type = transaction.get("transaction_type") or "Service"

    cleaned_transaction = {
        "customer": transaction.get("customer"),
        "service": transaction.get("service"),
        "amount": transaction.get("amount"),
        "payment_method": transaction.get("payment_method"),
        "transaction_type": transaction_type,
        "description": transaction.get("description") or text,
    }

    if transaction_type == "Expense":
        cleaned_transaction["customer"] = None

    cleaned_transaction["missing_fields"] = get_missing_transaction_fields(
        cleaned_transaction
    )

    cleaned_transaction["complete"] = len(cleaned_transaction["missing_fields"]) == 0

    return cleaned_transaction


def extract_transaction_from_voice(transcript: str) -> dict:
    return extract_transaction(transcript)


def get_missing_transaction_fields(transaction: dict) -> list:
    transaction_type = transaction.get("transaction_type") or "Service"

    if transaction_type == "Expense":
        required_fields = [
            "service",
            "amount",
            "payment_method",
        ]
    else:
        required_fields = [
            "customer",
            "service",
            "amount",
            "payment_method",
        ]

    missing_fields = []

    for field in required_fields:
        value = transaction.get(field)

        if value is None:
            missing_fields.append(field)

        elif isinstance(value, str) and value.strip() == "":
            missing_fields.append(field)

    return missing_fields


def get_follow_up_question(missing_field: str) -> str:
    questions = {
        "customer": "Who was the customer?",
        "service": "What service or expense was this for?",
        "amount": "How much was it?",
        "payment_method": "Was it cash or card?",
    }

    return questions.get(
        missing_field,
        "What information is missing for this transaction?"
    )


def merge_transaction_update(pending_transaction: dict, field: str, answer: str) -> dict:
    updated_transaction = pending_transaction.copy()

    if field == "amount":
        cleaned_amount = (
            answer.lower()
            .replace("r", "")
            .replace("rand", "")
            .strip()
        )

        try:
            updated_transaction["amount"] = float(cleaned_amount)
        except ValueError:
            updated_transaction["amount"] = None

    elif field == "payment_method":
        answer_lower = answer.lower()

        if "cash" in answer_lower:
            updated_transaction["payment_method"] = "Cash"
        elif "card" in answer_lower:
            updated_transaction["payment_method"] = "Card"
        else:
            updated_transaction["payment_method"] = answer.strip().title()

    elif field == "service":
        updated_transaction["service"] = answer.strip().title()

    elif field == "customer":
        updated_transaction["customer"] = answer.strip().title()

    if updated_transaction.get("transaction_type") == "Expense":
        updated_transaction["customer"] = None

    updated_transaction["missing_fields"] = get_missing_transaction_fields(
        updated_transaction
    )

    updated_transaction["complete"] = len(updated_transaction["missing_fields"]) == 0

    return updated_transaction


def format_transaction_confirmation(transaction: dict) -> str:
    customer = transaction.get("customer") or "N/A"
    service = transaction.get("service") or "Unknown"
    amount = transaction.get("amount")
    payment_method = transaction.get("payment_method") or "Unknown payment method"
    transaction_type = transaction.get("transaction_type") or "Service"

    amount_text = f"R{amount}" if amount is not None else "Amount missing"

    if transaction_type == "Expense":
        return f"""✅ Expense recorded.

Type: Expense
Description: {service}
Amount: {amount_text}
Payment: {payment_method}"""

    return f"""✅ Transaction recorded.

Customer: {customer}
Type: {transaction_type}
Service: {service}
Amount: {amount_text}
Payment: {payment_method}"""