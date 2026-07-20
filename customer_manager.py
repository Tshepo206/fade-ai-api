from typing import Optional

from db_manager import supabase


class CustomerManager:
    """Tenant-aware customer data access and management."""

    @staticmethod
    def normalise_phone_number(phone_number: str) -> str:
        if not phone_number:
            return ""

        clean_phone = "".join(
            character
            for character in str(phone_number)
            if character.isdigit()
        )

        if clean_phone.startswith("0") and len(clean_phone) == 10:
            clean_phone = f"27{clean_phone[1:]}"

        return clean_phone

    @staticmethod
    def get_customer(
        business_id: str,
        phone_number: str,
    ) -> Optional[dict]:
        try:
            clean_phone = CustomerManager.normalise_phone_number(
                phone_number
            )

            if not business_id or not clean_phone:
                return None

            response = (
                supabase.table("clients")
                .select("*")
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .limit(1)
                .execute()
            )

            if response.data:
                return response.data[0]

            return None

        except Exception as error:
            print(f"Tenant customer lookup failed: {error}")
            return None

    @staticmethod
    def get_all_customers(
        business_id: str,
        search_term: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        try:
            if not business_id:
                return []

            safe_limit = max(
                1,
                min(int(limit or 100), 500),
            )

            query = (
                supabase.table("clients")
                .select("*")
                .eq("business_id", business_id)
                .order("first_name")
                .limit(safe_limit)
            )

            if search_term and search_term.strip():
                search_value = search_term.strip()

                query = query.or_(
                    (
                        f"first_name.ilike.%{search_value}%,"
                        f"phone_number.ilike.%{search_value}%,"
                        f"email.ilike.%{search_value}%,"
                        f"notes.ilike.%{search_value}%"
                    )
                )

            response = query.execute()
            return response.data or []

        except Exception as error:
            print(f"Tenant customer-list lookup failed: {error}")
            return []

    @staticmethod
    def create_or_update_customer(
        business_id: str,
        phone_number: str,
        customer_name: str,
        email: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        try:
            if not business_id:
                return {
                    "success": False,
                    "error": "A business workspace is required.",
                    "customer": None,
                }

            clean_phone = CustomerManager.normalise_phone_number(
                phone_number
            )
            clean_name = (customer_name or "").strip().title()
            clean_email = (email or "").strip().lower()
            clean_notes = (notes or "").strip()

            if not clean_phone:
                return {
                    "success": False,
                    "error": "A valid phone number is required.",
                    "customer": None,
                }

            if len(clean_phone) < 10:
                return {
                    "success": False,
                    "error": "The phone number is too short.",
                    "customer": None,
                }

            if not clean_name:
                return {
                    "success": False,
                    "error": "The customer's name is required.",
                    "customer": None,
                }

            customer_data = {
                "business_id": business_id,
                "phone_number": clean_phone,
                "first_name": clean_name,
                "email": clean_email or None,
                "notes": clean_notes or None,
            }

            response = (
                supabase.table("clients")
                .upsert(
                    customer_data,
                    on_conflict="business_id,phone_number",
                )
                .execute()
            )

            if not response.data:
                return {
                    "success": False,
                    "error": (
                        "Supabase did not return the saved customer."
                    ),
                    "customer": None,
                }

            return {
                "success": True,
                "error": None,
                "customer": response.data[0],
            }

        except Exception as error:
            print(f"Tenant customer save failed: {error}")

            return {
                "success": False,
                "error": str(error),
                "customer": None,
            }

    @staticmethod
    def get_top_customers(
        business_id: str,
        period_start: Optional[str] = None,
        limit: int = 10,
    ) -> list:
        try:
            if not business_id:
                return []

            safe_limit = max(
                1,
                min(int(limit or 10), 50),
            )

            query = (
                supabase.table("financial_ledger")
                .select("*")
                .eq("business_id", business_id)
            )

            if period_start:
                query = query.gte(
                    "transaction_timestamp",
                    period_start,
                )

            response = query.execute()
            transactions = response.data or []

            customer_totals: dict[str, dict] = {}

            for transaction in transactions:
                credit = float(
                    transaction.get("credit_amount") or 0
                )

                if credit <= 0:
                    continue

                customer_name = (
                    transaction.get("customer_name")
                    or "Unknown customer"
                )

                if customer_name not in customer_totals:
                    customer_totals[customer_name] = {
                        "customer_name": customer_name,
                        "revenue": 0,
                        "visits": 0,
                    }

                customer_totals[customer_name]["revenue"] += credit
                customer_totals[customer_name]["visits"] += 1

            customers = list(customer_totals.values())

            customers.sort(
                key=lambda customer: customer["revenue"],
                reverse=True,
            )

            return customers[:safe_limit]

        except Exception as error:
            print(f"Tenant top-customers lookup failed: {error}")
            return []