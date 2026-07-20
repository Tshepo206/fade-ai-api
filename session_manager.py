from datetime import datetime
from typing import Optional

from db_manager import supabase
from customer_manager import CustomerManager


class SessionManager:
    """Tenant-scoped WhatsApp conversation session management."""

    @staticmethod
    def get_or_create_session(
        business_id: str,
        phone_number: str,
    ) -> dict:
        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        if not business_id:
            raise ValueError(
                "A business workspace is required."
            )

        if not clean_phone:
            raise ValueError(
                "A valid customer phone number is required."
            )

        try:
            response = (
                supabase.table("client_sessions")
                .select("*")
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .limit(1)
                .execute()
            )

            if response.data:
                return response.data[0]

            session_data = {
                "business_id": business_id,
                "phone_number": clean_phone,
                "current_state": "INITIAL_CONTACT",
                "context_data": {},
                "last_interaction": datetime.utcnow().isoformat(),
            }

            insert_response = (
                supabase.table("client_sessions")
                .insert(session_data)
                .execute()
            )

            if not insert_response.data:
                raise RuntimeError(
                    "Supabase did not return the created session."
                )

            return insert_response.data[0]

        except Exception as error:
            print(
                "[Session Manager] Session lookup or creation failed: "
                f"{error}"
            )
            raise

    @staticmethod
    def get_session(
        business_id: str,
        phone_number: str,
    ) -> Optional[dict]:
        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        if not business_id or not clean_phone:
            return None

        try:
            response = (
                supabase.table("client_sessions")
                .select("*")
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .limit(1)
                .execute()
            )

            return (
                response.data[0]
                if response.data
                else None
            )

        except Exception as error:
            print(
                "[Session Manager] Session lookup failed: "
                f"{error}"
            )
            return None

    @staticmethod
    def update_session_state(
        business_id: str,
        phone_number: str,
        new_state: str,
        context_updates: Optional[dict] = None,
    ) -> bool:
        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        if not business_id or not clean_phone:
            return False

        try:
            update_data = {
                "current_state": (
                    new_state or "INITIAL_CONTACT"
                ),
                "last_interaction": datetime.utcnow().isoformat(),
            }

            if context_updates is not None:
                update_data["context_data"] = context_updates

            response = (
                supabase.table("client_sessions")
                .update(update_data)
                .eq("business_id", business_id)
                .eq("phone_number", clean_phone)
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(
                "[Session Manager] Session update failed: "
                f"{error}"
            )
            return False

    @staticmethod
    def ensure_session(
        business_id: str,
        phone_number: str,
        source: str = "WHATSAPP",
    ) -> bool:
        clean_phone = CustomerManager.normalise_phone_number(
            phone_number
        )

        if not business_id or not clean_phone:
            return False

        try:
            existing = SessionManager.get_session(
                business_id,
                clean_phone,
            )

            if existing:
                return True

            session_data = {
                "business_id": business_id,
                "phone_number": clean_phone,
                "current_state": "INITIAL_CONTACT",
                "context_data": {
                    "source": source,
                },
                "last_interaction": datetime.utcnow().isoformat(),
            }

            response = (
                supabase.table("client_sessions")
                .insert(session_data)
                .execute()
            )

            return bool(response.data)

        except Exception as error:
            print(
                "[Session Manager] Session creation failed: "
                f"{error}"
            )
            return False

    @staticmethod
    def reset_session(
        business_id: str,
        phone_number: str,
    ) -> bool:
        return SessionManager.update_session_state(
            business_id=business_id,
            phone_number=phone_number,
            new_state="INITIAL_CONTACT",
            context_updates={},
        )