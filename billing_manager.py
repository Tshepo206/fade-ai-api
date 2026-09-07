import os
import requests

from datetime import datetime, timedelta, timezone
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
        
        # Ensure the workspace has a billing subscription record
        # before payment-method setup begins.
        now = datetime.now(timezone.utc)
        trial_end = now + timedelta(days=30)

        try:
            existing_response = (
                supabase
                .table("billing_subscriptions")
                .select("*")
                .eq("business_id", business_id)
                .maybe_single()
                .execute()
            )

            existing = existing_response.data

            if not existing:
                trial_record = {
                    "business_id": business_id,
                    "provider": "paystack",
                    "plan_name": "GoodKeeper Standard",
                    "plan_code": PAYSTACK_PLAN_CODE,
                    "customer_email": email,
                    "status": "trialing",
                    "amount": 69900,
                    "currency": "ZAR",
                    "trial_start": now.isoformat(),
                    "trial_end": trial_end.isoformat(),
                    "billing_start_date": trial_end.isoformat(),
                    "updated_at": now.isoformat(),
                }

                (
                    supabase
                    .table("billing_subscriptions")
                    .insert(trial_record)
                    .execute()
                )

                print(
                    "[Billing] Trial record created for:",
                    business_id,
                )

        except Exception as error:
            print(
                "[Billing] Failed to create trial record:",
                error,
            )

            return {
                "success": False,
                "error": (
                    "Unable to prepare the free trial."
                ),
            }

        payload = {
            "email": email,

            # R1 authorization/tokenization charge.
            # We intentionally DO NOT send the Paystack plan here,
            # otherwise the customer would be charged R699 immediately.
            "amount": 100,

            "currency": "ZAR",

            "callback_url": (
                "https://goodkeeper.syntaxcfo.co.za/onboarding"
            ),

            "metadata": {
                "business_id": business_id,
                "product": "GoodKeeper",
                "plan": "GoodKeeper Standard",
                "purpose": "trial_payment_method_setup",
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
        purpose = metadata.get("purpose")

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

        customer_code = customer.get("customer_code")
        authorization_code = authorization.get(
            "authorization_code"
        )

        # =====================================================
        # TRIAL PAYMENT METHOD SETUP
        # =====================================================

        if purpose == "trial_payment_method_setup":
            print(
                "[Billing] Trial payment method setup received "
                "for business:",
                business_id,
            )

            try:
                existing_response = (
                    supabase
                    .table("billing_subscriptions")
                    .select("*")
                    .eq("business_id", business_id)
                    .maybe_single()
                    .execute()
                )

                existing = existing_response.data or {}

                trial_end = existing.get("trial_end")

                if not trial_end:
                    return {
                        "success": False,
                        "error": (
                            "Trial end date is not configured."
                        ),
                    }

                if not customer_code:
                    return {
                        "success": False,
                        "error": (
                            "Paystack customer code is missing."
                        ),
                    }

                if not authorization_code:
                    return {
                        "success": False,
                        "error": (
                            "Reusable Paystack authorization "
                            "was not returned."
                        ),
                    }

                # Save the real live customer/card authorization
                # immediately.
                authorization_record = {
                    "business_id": business_id,
                    "provider": "paystack",
                    "plan_name": "GoodKeeper Standard",
                    "plan_code": PAYSTACK_PLAN_CODE,
                    "customer_email": customer.get("email"),
                    "customer_code": customer_code,
                    "authorization_code": authorization_code,
                    "card_brand": (
                        authorization.get("brand")
                        or authorization.get("card_type")
                    ),
                    "card_last4": authorization.get("last4"),
                    "status": "trialing",
                    "last_payment_reference": data.get(
                        "reference"
                    ),
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
                        authorization_record,
                        on_conflict="business_id",
                    )
                    .execute()
                )

                # Protect against Paystack webhook retries.
                # If we already created a subscription, do not
                # create another one.
                existing_subscription_code = existing.get(
                    "subscription_code"
                )

                if existing_subscription_code:
                    print(
                        "[Billing] Subscription already exists:",
                        existing_subscription_code,
                    )

                    return {
                        "success": True,
                        "business_id": business_id,
                        "subscription_code": (
                            existing_subscription_code
                        ),
                    }

                subscription_payload = {
                    "customer": customer_code,
                    "plan": PAYSTACK_PLAN_CODE,
                    "authorization": authorization_code,
                    "start_date": trial_end,
                }

                subscription_response = requests.post(
                    "https://api.paystack.co/subscription",
                    headers={
                        "Authorization": (
                            f"Bearer {PAYSTACK_SECRET_KEY}"
                        ),
                        "Content-Type": "application/json",
                    },
                    json=subscription_payload,
                    timeout=30,
                )

                subscription_result = (
                    subscription_response.json()
                )

                print(
                    "[Billing] Paystack subscription response:",
                    subscription_result,
                )

                if (
                    not subscription_response.ok
                    or not subscription_result.get("status")
                ):
                    return {
                        "success": False,
                        "error": subscription_result.get(
                            "message",
                            (
                                "Unable to create delayed "
                                "Paystack subscription."
                            ),
                        ),
                    }

                subscription_data = (
                    subscription_result.get("data") or {}
                )

                subscription_code = (
                    subscription_data.get(
                        "subscription_code"
                    )
                )

                email_token = subscription_data.get(
                    "email_token"
                )

                next_payment_date = (
                    subscription_data.get(
                        "next_payment_date"
                    )
                    or trial_end
                )

                final_record = {
                    "business_id": business_id,
                    "subscription_code": subscription_code,
                    "email_token": email_token,
                    "next_payment_date": next_payment_date,
                    "billing_start_date": trial_end,
                    "status": "trialing",
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                response = (
                    supabase
                    .table("billing_subscriptions")
                    .upsert(
                        final_record,
                        on_conflict="business_id",
                    )
                    .execute()
                )

                print(
                    "[Billing] Trial subscription created:",
                    response.data,
                )

                # Refund the R1 card verification charge.
                transaction_reference = data.get("reference")

                if transaction_reference:
                    try:
                        refund_response = requests.post(
                            "https://api.paystack.co/refund",
                            headers={
                                "Authorization": (
                                    f"Bearer {PAYSTACK_SECRET_KEY}"
                                ),
                                "Content-Type": "application/json",
                            },
                            json={
                                "transaction": transaction_reference,
                                "customer_note": (
                                    "GoodKeeper card verification refund"
                                ),
                                "merchant_note": (
                                    "Automatic refund of trial "
                                    "payment-method verification charge"
                                ),
                            },
                            timeout=30,
                        )

                        refund_result = refund_response.json()

                        print(
                            "[Billing] Verification refund response:",
                            refund_result,
                        )

                    except Exception as refund_error:
                        print(
                            "[Billing] Verification refund failed:",
                            refund_error,
                        )

                return {
                    "success": True,
                    "business_id": business_id,
                    "subscription_code": subscription_code,
                    "status": "trialing",
                }

            except Exception as error:
                print(
                    "[Billing] Trial setup failed:",
                    error,
                )

                raise

        # =====================================================
        # NORMAL SUBSCRIPTION PAYMENT
        # =====================================================

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
                or PAYSTACK_PLAN_CODE
            ),

            "customer_email": customer.get("email"),
            "customer_code": customer_code,

            "status": "active",

            # Paystack amount is in cents.
            "amount": data.get("amount"),

            "currency": data.get("currency") or "ZAR",

            "authorization_code": authorization_code,

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
                "[Billing] Subscription payment recorded for:",
                business_id,
            )

            print(
                "[Billing] Supabase result:",
                response.data,
            )

            # Refund the R1 card verification charge.
            transaction_reference = data.get("reference")

            if transaction_reference:
                try:
                    refund_response = requests.post(
                        "https://api.paystack.co/refund",
                        headers={
                            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "transaction": transaction_reference,
                            "customer_note": "GoodKeeper card verification refund",
                            "merchant_note": (
                                "Automatic refund of trial "
                                "payment-method verification charge"
                            ),
                        },
                        timeout=30,
                    )

                    refund_result = refund_response.json()

                    print(
                        "[Billing] Verification refund response:",
                        refund_result,
                    )

                except Exception as refund_error:
                    print(
                        "[Billing] Verification refund failed:",
                        refund_error,
                    )


            return {
                "success": True,
                "business_id": business_id,
            }

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