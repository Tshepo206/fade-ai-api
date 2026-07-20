from typing import Optional

from db_manager import supabase


class WhatsAppTenantManager:
    """Resolve the correct business for an incoming WhatsApp webhook."""

    @staticmethod
    def get_business_by_phone_number_id(
        whatsapp_phone_number_id: str,
    ) -> Optional[dict]:
        if not whatsapp_phone_number_id:
            return None

        normalized_phone_number_id = str(
            whatsapp_phone_number_id
        ).strip()

        if not normalized_phone_number_id:
            return None

        try:
            response = (
                supabase.table("businesses")
                .select(
                    "id, name, slug, status, "
                    "whatsapp_phone_number_id, "
                    "whatsapp_business_account_id, "
                    "owner_phone_number, "
                    "whatsapp_access_token"
                )
                .eq(
                    "whatsapp_phone_number_id",
                    normalized_phone_number_id,
                )
                .eq("status", "active")
                .limit(1)
                .execute()
            )

            if not response.data:
                return None

            business = response.data[0]

            business_id = business.get("id")

            if not business_id:
                print(
                    "[WhatsApp Tenant] Business record has no ID "
                    f"for phone_number_id={normalized_phone_number_id}"
                )
                return None

            return {
                "business_id": str(business_id),
                "business_name": (
                    business.get("name")
                    or "GoodKeeper Workspace"
                ),
                "business_slug": business.get("slug"),
                "status": business.get("status"),
                "whatsapp_phone_number_id": business.get(
                    "whatsapp_phone_number_id"
                ),
                "whatsapp_business_account_id": business.get(
                    "whatsapp_business_account_id"
                ),
                "owner_phone_number": str(
                    business.get("owner_phone_number") or ""
                ).strip(),
                "whatsapp_access_token": business.get(
                    "whatsapp_access_token"
                ),
            }

        except Exception as error:
            print(
                "[WhatsApp Tenant] Business lookup failed: "
                f"{error}"
            )
            return None

    @staticmethod
    def is_owner(
        business: dict,
        sender_phone: str,
    ) -> bool:
        if not business or not sender_phone:
            return False

        owner_phone = "".join(
            character
            for character in str(
                business.get("owner_phone_number") or ""
            )
            if character.isdigit()
        )

        normalized_sender_phone = "".join(
            character
            for character in str(sender_phone)
            if character.isdigit()
        )

        return bool(
            owner_phone
            and normalized_sender_phone
            and normalized_sender_phone == owner_phone
        )