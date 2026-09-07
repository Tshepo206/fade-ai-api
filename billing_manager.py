import os
import requests

from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

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

        if not business_id:
            return {
                "success": False,
                "error": "Business ID is required.",
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
        if event_type != "charge.success":
            print(
                "[Billing] Paystack event not handled:",
                event_type,
            )

            return {
                "success": True,
                "ignored": True,
            }

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

            # Paystack amounts are in the smallest currency unit.
            # For ZAR, 69900 = R699.00.
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

        try:
            response = (
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

            print(
                "[Billing] Supabase result:",
                response.data,
            )

            return {
                "success": True,
                "business_id": business_id,
            }

        except Exception as error:
            print(
                "[Billing] Failed to persist subscription:",
                error,
            )

            raise

    @staticmethod
    def get_subscription(
        business_id: str,
    ) -> dict:
        try:
            response = (
                supabase
                .table("billing_subscriptions")
                .select("*")
                .eq("business_id", business_id)
                .maybe_single()
                .execute()
            )

            return {
                "success": True,
                "subscription": response.data,
            }

        except Exception as error:
            print(
                "[Billing] Failed to fetch subscription:",
                error,
            )

            return {
                "success": False,
                "error": str(error),
            }
        
    @staticmethod
    def get_billing_profile(
        business_id: str,
    ) -> dict:
        try:
            response = (
                supabase
                .table("billing_profiles")
                .select("*")
                .eq("business_id", business_id)
                .maybe_single()
                .execute()
            )

            return {
                "success": True,
                "profile": response.data,
            }

        except Exception as error:
            print(
                "[Billing] Failed to fetch billing profile:",
                error,
            )

            return {
                "success": False,
                "error": str(error),
            }

    @staticmethod
    def upsert_billing_profile(
        business_id: str,
        billing_name: str,
        billing_email: str,
        billing_phone: str | None = None,
        address_line_1: str | None = None,
        address_line_2: str | None = None,
        city: str | None = None,
        province: str | None = None,
        postal_code: str | None = None,
        country: str = "ZA",
        company_registration_number: str | None = None,
        vat_number: str | None = None,
    ) -> dict:
        if not billing_name:
            return {
                "success": False,
                "error": "Billing name is required.",
            }

        if not billing_email:
            return {
                "success": False,
                "error": "Billing email is required.",
            }

        billing_record = {
            "business_id": business_id,
            "billing_name": billing_name,
            "billing_email": billing_email,
            "billing_phone": billing_phone,
            "address_line_1": address_line_1,
            "address_line_2": address_line_2,
            "city": city,
            "province": province,
            "postal_code": postal_code,
            "country": country or "ZA",
            "company_registration_number": (
                company_registration_number
            ),
            "vat_number": vat_number,
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        try:
            response = (
                supabase
                .table("billing_profiles")
                .upsert(
                    billing_record,
                    on_conflict="business_id",
                )
                .execute()
            )

            return {
                "success": True,
                "profile": (
                    response.data[0]
                    if response.data
                    else billing_record
                ),
            }

        except Exception as error:
            print(
                "[Billing] Failed to save billing profile:",
                error,
            )

            return {
                "success": False,
                "error": str(error),
            }

    @staticmethod
    def get_manage_subscription_link(
        business_id: str,
    ) -> dict:
        try:
            subscription_response = (
                supabase
                .table("billing_subscriptions")
                .select(
                    "subscription_code,"
                    "customer_code,"
                    "email_token"
                )
                .eq("business_id", business_id)
                .maybe_single()
                .execute()
            )

            subscription = (
                subscription_response.data or {}
            )

            subscription_code = subscription.get(
                "subscription_code"
            )

            if not subscription_code:
                return {
                    "success": False,
                    "error": (
                        "Subscription management is not "
                        "available yet because the Paystack "
                        "subscription code has not been saved."
                    ),
                }

            response = requests.get(
                (
                    "https://api.paystack.co/subscription/"
                    f"{subscription_code}/manage/link"
                ),
                headers={
                    "Authorization": (
                        f"Bearer {PAYSTACK_SECRET_KEY}"
                    ),
                },
                timeout=30,
            )

            data = response.json()

            if not response.ok or not data.get("status"):
                return {
                    "success": False,
                    "error": data.get(
                        "message",
                        "Unable to create subscription management link.",
                    ),
                }

            manage_data = data.get("data") or {}

            return {
                "success": True,
                "link": manage_data.get("link"),
            }

        except Exception as error:
            print(
                "[Billing] Failed to generate management link:",
                error,
            )

            return {
                "success": False,
                "error": str(error),
            }