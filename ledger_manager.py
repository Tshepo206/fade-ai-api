from datetime import datetime

from db_manager import supabase


class LedgerManager:
    """Tenant-scoped financial ledger access."""

    @staticmethod
    def record_transaction(business_id: str, customer_name=None, service_name=None,
                           amount=None, payment_method=None,
                           transaction_type="Service", booking_id=None) -> bool:
        if not business_id or amount is None:
            return False
        try:
            if booking_id is not None:
                booking_response = (
                    supabase.table("bookings").select("id")
                    .eq("business_id", business_id).eq("id", booking_id)
                    .limit(1).execute()
                )
                if not booking_response.data:
                    return False
            amount_value = float(amount)
            transaction_type = (transaction_type or "Service").strip().title()
            is_expense = transaction_type == "Expense"
            account_type = (
                "Expense" if is_expense else "Retail Revenue"
                if transaction_type == "Retail" else "Service Revenue"
            )
            parts = [value.strip().title() for value in
                     (service_name or "", customer_name or "", payment_method or "")
                     if value and value.strip()]
            response = supabase.table("financial_ledger").insert({
                "business_id": business_id,
                "transaction_timestamp": datetime.utcnow().isoformat(),
                "account_type": account_type,
                "debit_amount": amount_value if is_expense else 0,
                "credit_amount": 0 if is_expense else amount_value,
                "narrative": " - ".join(parts) or f"{account_type} transaction",
                "customer_name": (customer_name or "").strip().title() or None,
                "service_name": (service_name or "").strip().title() or None,
                "payment_method": (payment_method or "").strip().title() or None,
                "booking_id": booking_id,
            }).execute()
            return bool(response.data)
        except Exception as error:
            print(f"Tenant transaction ledger save failed: {error}")
            return False

    @staticmethod
    def get_recent_transactions(business_id: str, limit: int = 20) -> list:
        if not business_id:
            return []
        try:
            safe_limit = max(1, min(int(limit or 20), 2000))
            response = (
                supabase.table("financial_ledger").select("*")
                .eq("business_id", business_id)
                .order("transaction_timestamp", desc=True).limit(safe_limit).execute()
            )
            return response.data or []
        except Exception as error:
            print(f"Tenant transaction lookup failed: {error}")
            return []

    @staticmethod
    def get_transactions_for_range(business_id: str, start_datetime: datetime,
                                   end_datetime: datetime, limit: int = 500) -> list:
        if not business_id:
            return []
        safe_limit = max(1, min(int(limit or 500), 2000))
        response = (
            supabase.table("financial_ledger").select("*")
            .eq("business_id", business_id)
            .gte("transaction_timestamp", start_datetime.isoformat())
            .lt("transaction_timestamp", end_datetime.isoformat())
            .order("transaction_timestamp", desc=True).limit(safe_limit).execute()
        )
        return response.data or []
