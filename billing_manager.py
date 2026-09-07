import os
import requests


PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PLAN_CODE = os.getenv("PAYSTACK_PLAN_CODE")


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