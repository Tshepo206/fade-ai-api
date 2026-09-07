import os
import requests

from datetime import datetime, timezone
from supabase import create_client


PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PLAN_CODE = os.getenv("PAYSTACK_PLAN_CODE")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
)


class BillingManager:
    @staticmethod
    def initialize_subscription(
        email: str,
        business_id: str,
    ) -> dict:
        if not PAYSTACK_SECRET_KEY:
            return {
                "success": False,
                "error": "Paystack secret key is not configured.",
            }

        if not PAYSTACK_PLAN_CODE:
            return {
                "success": False,
                "error": "Paystack plan code is not configured.",
            }

        if not email:
            return {
                "success": False,
                "error": "Customer email is required.",
            }

        payload = {
            "email": email,
            "plan": PAYSTACK_PLAN_CODE,
            "currency": "ZAR",
            "callback_url": (
                "https://goodkeeper.syntaxcfo.co.za/billing"
            ),
            "metadata": {
                "business_id": business_id,
                "product": "GoodKeeper",
                "plan": "GoodKeeper Standard",
            },
        }

        try:
            response = requests.post(
                "https://api.paystack.co/transaction/initialize",
                headers={
                    "Authorization": (
                        f"Bearer {PAYSTACK_SECRET_KEY}"
                    ),
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            data = response.json()

            if not response.ok or not data.get("status"):
                return {
                    "success": False,
                    "error": data.get(
                        "message",
                        "Paystack initialization failed.",
                    ),
                }

            payment_data = data.get("data") or {}

            return {
                "success": True,
                "authorization_url": payment_data.get(
                    "authorization_url"
                ),
                "access_code": payment_data.get(
                    "access_code"
                ),
                "reference": payment_data.get(
                    "reference"
                ),
            }

        except Exception as error:
            print(
                "[Billing] Paystack initialization failed:",
                error,
            )

            return {
                "success": False,
                "error": "Unable to initialize subscription.",
            }
        
        @staticmethod
        def handle_paystack_event(
            event_type: str,
            data: dict,
        ) -> dict:
            if event_type == "charge.success":
                metadata = data.get("metadata") or {}
                business_id = metadata.get("business_id")

                if not business_id:
                    print(
                        "[Billing] charge.success has no business_id. "
                        "Ignoring."
                    )

                    return {
                        "success": True,
                        "ignored": True,
                    }

                customer = data.get("customer") or {}
                authorization = data.get("authorization") or {}
                plan_object = data.get("plan_object") or {}

                billing_record = {
                    "business_id": business_id,
                    "provider": "paystack",

                    "plan_name": (
                        plan_object.get("name")
                        or metadata.get("plan")
                        or "GoodKeeper Standard"
                    ),

                    "plan_code": (
                        plan_object.get("plan_code")
                        or data.get("plan")
                    ),

                    "customer_email": customer.get("email"),
                    "customer_code": customer.get("customer_code"),

                    "status": "active",

                    # Paystack amounts are in cents
                    "amount": data.get("amount"),

                    "currency": data.get("currency") or "ZAR",

                    "card_brand": (
                        authorization.get("brand")
                        or authorization.get("card_type")
                    ),

                    "card_last4": authorization.get("last4"),

                    "last_payment_reference": data.get("reference"),

                    "last_payment_at": (
                        data.get("paid_at")
                        or data.get("paidAt")
                    ),

                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                (
                    supabase
                    .table("billing_subscriptions")
                    .upsert(
                        billing_record,
                        on_conflict="business_id",
                    )
                    .execute()
                )

                print(
                    "[Billing] Subscription activated for business:",
                    business_id,
                )

                return {
                    "success": True,
                    "business_id": business_id,
                }

            print(
                "[Billing] Paystack event not handled:",
                event_type,
            )

            return {
                "success": True,
                "ignored": True,
            }