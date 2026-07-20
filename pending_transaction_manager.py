from datetime import datetime
from typing import Optional

from customer_manager import CustomerManager
from db_manager import supabase


class PendingTransactionManager:
    """Tenant-scoped pending bookkeeping transaction management."""

    @staticmethod
    def save_pending_transaction(
        business_id: str,
        phone_number: str,
        transaction: dict,
        missing_field: str,
    ) -> bool:
        clean_phone = CustomerManager.normalise_phone_number(phone_number)

        if not business_id or not clean_phone:
            return False

        try:
            data = {
                "business_id": business_id,
                "phone_number": clean_phone,
                "transaction_json": transaction or {},
                "missing_field": missing_field,
                "created_at": datetime.utcnow().isoformat(),
            }

            response = (
                supabase.table("pending_transactions")
                .upsert(
                    data,
                    on_conflict="business_id,phone_number",
                )
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(
                "[Pending Transaction Manager] Save failed: "
                f"{error}"
            )
            return False

    @staticmethod
    def get_pending_transaction(
        business_id: str,
        phone_number: str,
    ) -> Optional[dict]:
        clean_phone = CustomerManager.normalise_phone_number(phone_number)

        if not business_id or not clean_phone:
            return None

        try:
            response = (
                supabase.table("pending_transactions")
                .select("*")
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .limit(1)
                .execute()
            )

            return response.data[0] if response.data else None

        except Exception as error:
            print(
                "[Pending Transaction Manager] Lookup failed: "
                f"{error}"
            )
            return None

    @staticmethod
    def delete_pending_transaction(
        business_id: str,
        phone_number: str,
    ) -> bool:
        clean_phone = CustomerManager.normalise_phone_number(phone_number)

        if not business_id or not clean_phone:
            return False

        try:
            response = (
                supabase.table("pending_transactions")
                .delete()
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(
                "[Pending Transaction Manager] Delete failed: "
                f"{error}"
            )
            return False

    @staticmethod
    def has_pending_transaction(
        business_id: str,
        phone_number: str,
    ) -> bool:
        return (
            PendingTransactionManager.get_pending_transaction(
                business_id=business_id,
                phone_number=phone_number,
            )
            is not None
        )