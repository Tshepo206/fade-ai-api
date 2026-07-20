from datetime import datetime, timedelta
from typing import Optional

from ledger_manager import LedgerManager


SUPPORTED_TRANSACTION_PERIODS = {
    "last_7_days",
    "last_30_days",
    "this_month",
    "last_month",
    "quarter",
    "year",
    "last_year",
    "custom",
}


def _start_of_day(value: datetime) -> datetime:
    """Return midnight for the supplied datetime."""
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _first_day_of_next_month(value: datetime) -> datetime:
    """Return the first day of the month following the supplied datetime."""
    if value.month == 12:
        return datetime(value.year + 1, 1, 1)

    return datetime(value.year, value.month + 1, 1)


def _parse_custom_date(value: str, field_name: str) -> datetime:
    """
    Parse a custom date supplied as YYYY-MM-DD.

    A descriptive ValueError is raised when the value is missing or invalid.
    """
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required for a custom date range.")

    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(
            f"{field_name} must use the YYYY-MM-DD format."
        ) from error


def get_transaction_date_range(
    period: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    Convert a transaction-history period into an inclusive display range and
    an exclusive database-query range.

    The returned `query_end` is exclusive. This avoids losing transactions
    recorded during the final day of a custom or completed calendar period.
    """
    clean_period = (period or "last_30_days").strip().lower()

    if clean_period not in SUPPORTED_TRANSACTION_PERIODS:
        raise ValueError(
            "Unsupported transaction period. Use one of: "
            + ", ".join(sorted(SUPPORTED_TRANSACTION_PERIODS))
            + "."
        )

    now = datetime.utcnow()
    today_start = _start_of_day(now)

    if clean_period == "last_7_days":
        query_start = today_start - timedelta(days=6)
        query_end = now

    elif clean_period == "last_30_days":
        query_start = today_start - timedelta(days=29)
        query_end = now

    elif clean_period == "this_month":
        query_start = datetime(now.year, now.month, 1)
        query_end = now

    elif clean_period == "last_month":
        current_month_start = datetime(now.year, now.month, 1)

        if now.month == 1:
            query_start = datetime(now.year - 1, 12, 1)
        else:
            query_start = datetime(now.year, now.month - 1, 1)

        query_end = current_month_start

    elif clean_period == "quarter":
        quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        query_start = datetime(now.year, quarter_start_month, 1)
        query_end = now

    elif clean_period == "year":
        query_start = datetime(now.year, 1, 1)
        query_end = now

    elif clean_period == "last_year":
        query_start = datetime(now.year - 1, 1, 1)
        query_end = datetime(now.year, 1, 1)

    else:
        custom_start = _parse_custom_date(start_date, "start_date")
        custom_end = _parse_custom_date(end_date, "end_date")

        if custom_end < custom_start:
            raise ValueError("end_date cannot be earlier than start_date.")

        query_start = _start_of_day(custom_start)

        # Add one day so the selected end date is fully included.
        query_end = _start_of_day(custom_end) + timedelta(days=1)

        if query_start > now:
            raise ValueError("start_date cannot be in the future.")

    effective_query_end = min(query_end, now)

    # Completed periods such as last month and last year keep their natural
    # exclusive boundary. Current and rolling periods end at the present time.
    if clean_period in {"last_month", "last_year"}:
        effective_query_end = query_end

    display_end = effective_query_end

    if clean_period in {"last_month", "last_year", "custom"}:
        display_end = effective_query_end - timedelta(microseconds=1)

    return {
        "period": clean_period,
        "query_start": query_start,
        "query_end": effective_query_end,
        "start_date": query_start.strftime("%Y-%m-%d"),
        "end_date": display_end.strftime("%Y-%m-%d"),
        "start_datetime": query_start.isoformat(),
        "end_datetime": effective_query_end.isoformat(),
    }


def get_transactions_for_range(
    business_id: str,
    start_datetime: datetime,
    end_datetime: datetime,
    limit: int = 500,
) -> list:
    """Retrieve ledger records within a date range."""
    safe_limit = max(1, min(int(limit or 500), 2000))

    return LedgerManager.get_transactions_for_range(
        business_id, start_datetime, end_datetime, safe_limit
    )


def calculate_transaction_summary(transactions: list) -> dict:
    """Calculate financial totals for a filtered transaction collection."""
    revenue = 0.0
    expenses = 0.0
    cash = 0.0
    card = 0.0
    other_payments = 0.0

    income_transactions = 0
    expense_transactions = 0
    cash_transactions = 0
    card_transactions = 0
    other_payment_transactions = 0

    for transaction in transactions:
        credit = float(transaction.get("credit_amount") or 0)
        debit = float(transaction.get("debit_amount") or 0)

        payment_method = (
            transaction.get("payment_method") or ""
        ).strip().lower()

        revenue += credit
        expenses += debit

        if credit > 0:
            income_transactions += 1

            if payment_method == "cash":
                cash += credit
                cash_transactions += 1
            elif payment_method == "card":
                card += credit
                card_transactions += 1
            else:
                other_payments += credit
                other_payment_transactions += 1

        if debit > 0:
            expense_transactions += 1

    profit = revenue - expenses

    return {
        "revenue": round(revenue, 2),
        "income": round(revenue, 2),
        "expenses": round(expenses, 2),
        "profit": round(profit, 2),
        "net_movement": round(profit, 2),
        "cash": round(cash, 2),
        "card": round(card, 2),
        "other_payments": round(other_payments, 2),
        "transactions": len(transactions),
        "transaction_count": len(transactions),
        "income_transactions": income_transactions,
        "expense_transactions": expense_transactions,
        "cash_transactions": cash_transactions,
        "card_transactions": card_transactions,
        "other_payment_transactions": other_payment_transactions,
    }


def get_transaction_history(
    business_id: str,
    period: str = "last_30_days",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 500,
) -> dict:
    """
    Return filtered transaction history and its financial summary.

    This service is separate from the main dashboard periods. It does not
    change the existing Today, Week, and Month dashboard calculations.
    """
    try:
        date_range = get_transaction_date_range(
            period=period,
            start_date=start_date,
            end_date=end_date,
        )

        if not business_id:
            raise ValueError("A business workspace is required.")

        transactions = get_transactions_for_range(
            business_id=business_id,
            start_datetime=date_range["query_start"],
            end_datetime=date_range["query_end"],
            limit=limit,
        )

        summary = calculate_transaction_summary(transactions)

        return {
            "success": True,
            "period": date_range["period"],
            "start_date": date_range["start_date"],
            "end_date": date_range["end_date"],
            "start_datetime": date_range["start_datetime"],
            "end_datetime": date_range["end_datetime"],
            "summary": summary,
            "transactions": transactions,
            "error": None,
        }

    except ValueError as error:
        return {
            "success": False,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "start_datetime": None,
            "end_datetime": None,
            "summary": calculate_transaction_summary([]),
            "transactions": [],
            "error": str(error),
        }

    except Exception as error:
        print(f"Transaction history lookup failed: {error}")

        return {
            "success": False,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "start_datetime": None,
            "end_datetime": None,
            "summary": calculate_transaction_summary([]),
            "transactions": [],
            "error": "Transaction history could not be retrieved.",
        }
