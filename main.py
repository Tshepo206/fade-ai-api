import os
from datetime import datetime
from typing import Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from agent import agent_engine
from dashboard_routes import router as dashboard_router
from owner_router import (
    handle_owner_text_message,
    handle_typed_bookkeeping,
)
from personality import get_time_of_day
from session_manager import SessionManager
from voice_processor import process_whatsapp_voice_note
from whatsapp_tenant_manager import WhatsAppTenantManager


VERIFY_TOKEN = os.getenv(
    "WHATSAPP_VERIFY_TOKEN",
    "fade-ai-verify-token",
)

DEFAULT_WHATSAPP_ACCESS_TOKEN = os.getenv(
    "WHATSAPP_ACCESS_TOKEN"
)

DEFAULT_WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "WHATSAPP_PHONE_NUMBER_ID"
)


app = FastAPI(
    title="GoodKeeper AI Business Assistant",
    description=(
        "Processes tenant-scoped WhatsApp messages, "
        "bookings, bookkeeping and dashboard requests."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://fade-dashboard-qrdyk.sevalla.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)


class InboundPayloadSchema(BaseModel):
    phone_number: str = Field(
        ...,
        examples=["27810000000"],
    )
    incoming_text: str = Field(
        ...,
        examples=["Hi"],
    )
    weather_summary: str = Field(
        default="",
        examples=[""],
    )
    day_of_week: str = Field(
        ...,
        examples=["Friday"],
    )
    time_of_day: str = Field(
        ...,
        examples=["afternoon"],
    )
    business_id: Optional[str] = None


class OutboundResponseSchema(BaseModel):
    current_state: str
    voice_note_script: Optional[str] = None
    text_response: str


@app.get("/")
def check_health():
    return {
        "status": "healthy",
        "service": "GoodKeeper Core Engine",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "GoodKeeper",
        "version": "2.0.0",
    }


@app.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(
        default=None,
        alias="hub.mode",
    ),
    hub_verify_token: str = Query(
        default=None,
        alias="hub.verify_token",
    ),
    hub_challenge: str = Query(
        default=None,
        alias="hub.challenge",
    ),
):
    print("[WhatsApp Webhook] Verification request received.")

    if (
        hub_mode == "subscribe"
        and hub_verify_token == VERIFY_TOKEN
    ):
        print("[WhatsApp Webhook] Verification successful.")

        return PlainTextResponse(
            content=hub_challenge or "",
        )

    print("[WhatsApp Webhook] Verification failed.")

    return PlainTextResponse(
        content="Verification failed",
        status_code=403,
    )


def send_whatsapp_message(
    to_number: str,
    message_text: str,
    whatsapp_phone_number_id: Optional[str] = None,
    whatsapp_access_token: Optional[str] = None,
):
    phone_number_id = (
        whatsapp_phone_number_id
        or DEFAULT_WHATSAPP_PHONE_NUMBER_ID
    )

    access_token = (
        whatsapp_access_token
        or DEFAULT_WHATSAPP_ACCESS_TOKEN
    )

    if not access_token:
        raise ValueError(
            "No WhatsApp access token is configured."
        )

    if not phone_number_id:
        raise ValueError(
            "No WhatsApp phone number ID is configured."
        )

    url = (
        "https://graph.facebook.com/v20.0/"
        f"{phone_number_id}/messages"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message_text,
        },
    }

    response = requests.post(
        url,
        headers=headers,
        json=data,
        timeout=30,
    )

    print("[WhatsApp Send] Status:", response.status_code)
    print("[WhatsApp Send] Body:", response.text)

    response.raise_for_status()

    return response


def resolve_webhook_business(
    value: dict,
) -> Optional[dict]:
    metadata = value.get("metadata") or {}

    whatsapp_phone_number_id = str(
        metadata.get("phone_number_id") or ""
    ).strip()

    if not whatsapp_phone_number_id:
        print(
            "[WhatsApp Tenant] Webhook metadata did not "
            "contain phone_number_id."
        )
        return None

    business = (
        WhatsAppTenantManager
        .get_business_by_phone_number_id(
            whatsapp_phone_number_id
        )
    )

    if not business:
        print(
            "[WhatsApp Tenant] No active business was found "
            f"for phone_number_id={whatsapp_phone_number_id}"
        )

    return business


def process_agent_message(
    business_id: str,
    payload: InboundPayloadSchema,
) -> OutboundResponseSchema:
    sender_phone = payload.phone_number.strip()
    user_message = payload.incoming_text.strip()

    if not business_id:
        raise HTTPException(
            status_code=400,
            detail="A business workspace is required.",
        )

    if not sender_phone:
        raise HTTPException(
            status_code=400,
            detail="A sender phone number is required.",
        )

    print(
        f"\n[Agent Event] Business: {business_id}"
    )
    print(
        f"[Agent Event] Phone: {sender_phone}"
    )
    print(
        f"[Agent Event] Message: '{user_message}'"
    )

    session_data = SessionManager.get_or_create_session(
        business_id=business_id,
        phone_number=sender_phone,
    )

    current_db_state = session_data.get(
        "current_state",
        "INITIAL_CONTACT",
    )

    cached_context = (
        session_data.get("context_data") or {}
    )

    print(
        "[Session Sync] Current state: "
        f"{current_db_state}"
    )

    state_input = {
        "business_id": business_id,
        "phone_number": sender_phone,
        "current_state": current_db_state,
        "incoming_text": user_message,
        "weather_summary": payload.weather_summary,
        "day_of_week": payload.day_of_week,
        "time_of_day": payload.time_of_day,
        "selected_service": cached_context.get(
            "selected_service"
        ),
        "validated_date": cached_context.get(
            "validated_date"
        ),
        "validated_time": cached_context.get(
            "validated_time"
        ),
        "customer_name": cached_context.get(
            "customer_name"
        ),
        "voice_note_script": None,
        "text_response": "",
    }

    result_state = agent_engine.invoke(
        state_input
    )

    next_system_state = result_state.get(
        "current_state",
        current_db_state,
    )

    updated_context_payload = {
        "selected_service": result_state.get(
            "selected_service"
        ),
        "validated_date": result_state.get(
            "validated_date"
        ),
        "validated_time": result_state.get(
            "validated_time"
        ),
        "customer_name": result_state.get(
            "customer_name"
        ),
    }

    print(
        "[Graph Transition] "
        f"{current_db_state} -> {next_system_state}"
    )

    session_updated = (
        SessionManager.update_session_state(
            business_id=business_id,
            phone_number=sender_phone,
            new_state=next_system_state,
            context_updates=updated_context_payload,
        )
    )

    if not session_updated:
        print(
            "[Session Sync] Warning: session state "
            "could not be updated."
        )

    return OutboundResponseSchema(
        current_state=next_system_state,
        voice_note_script=result_state.get(
            "voice_note_script"
        ),
        text_response=result_state.get(
            "text_response",
            "",
        ),
    )


@app.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(
    request: Request,
):
    payload = await request.json()

    print("\n==============================")
    print("Incoming WhatsApp Webhook")
    print(payload)
    print("==============================\n")

    try:
        value = (
            payload["entry"][0]
            ["changes"][0]
            ["value"]
        )

        if "messages" not in value:
            print(
                "[WhatsApp Webhook] No customer message "
                "found. Ignoring status webhook."
            )

            return {
                "status": "ignored",
            }

        business = resolve_webhook_business(
            value
        )

        if not business:
            return {
                "status": "ignored_unknown_business",
            }

        business_id = business["business_id"]

        message = value["messages"][0]
        message_type = message.get("type")
        sender_phone = str(
            message.get("from") or ""
        ).strip()

        if not sender_phone:
            print(
                "[WhatsApp Webhook] No sender phone found."
            )

            return {
                "status": "ignored_no_sender",
            }

        print(
            "[WhatsApp Event] Business: "
            f"{business.get('business_name')}"
        )
        print(
            "[WhatsApp Event] Business ID: "
            f"{business_id}"
        )
        print(
            "[WhatsApp Event] Sender: "
            f"{sender_phone}"
        )
        print(
            "[WhatsApp Event] Type: "
            f"{message_type}"
        )

        sender_is_owner = (
            WhatsAppTenantManager.is_owner(
                business=business,
                sender_phone=sender_phone,
            )
        )

        outbound_phone_number_id = (
            business.get(
                "whatsapp_phone_number_id"
            )
        )

        outbound_access_token = (
            business.get(
                "whatsapp_access_token"
            )
            or DEFAULT_WHATSAPP_ACCESS_TOKEN
        )

        if message_type == "audio":
            if not sender_is_owner:
                send_whatsapp_message(
                    to_number=sender_phone,
                    message_text=(
                        "Please send a text message "
                        "for bookings."
                    ),
                    whatsapp_phone_number_id=(
                        outbound_phone_number_id
                    ),
                    whatsapp_access_token=(
                        outbound_access_token
                    ),
                )

                return {
                    "status": (
                        "customer_audio_rejected"
                    ),
                }

            media_id = message["audio"]["id"]

            transcript = (
                process_whatsapp_voice_note(
                    media_id
                )
            )

            print(
                "[Owner Voice Transcript] "
                f"{transcript}"
            )

            # This owner-router call will become tenant-aware
            # in the next migration step.
            owner_response = (
                handle_typed_bookkeeping(
                    phone_number=sender_phone,
                    message_text=transcript,
                )
            )

            send_whatsapp_message(
                to_number=sender_phone,
                message_text=(
                    "Transcript heard:\n"
                    f"{transcript}\n\n"
                    f"{owner_response}"
                ),
                whatsapp_phone_number_id=(
                    outbound_phone_number_id
                ),
                whatsapp_access_token=(
                    outbound_access_token
                ),
            )

            return {
                "status": (
                    "owner_voice_processed"
                ),
                "business_id": business_id,
                "transcript": transcript,
            }

        if message_type != "text":
            send_whatsapp_message(
                to_number=sender_phone,
                message_text=(
                    "Please send a text message "
                    "or voice note for now."
                ),
                whatsapp_phone_number_id=(
                    outbound_phone_number_id
                ),
                whatsapp_access_token=(
                    outbound_access_token
                ),
            )

            return {
                "status": (
                    "non_text_message_handled"
                ),
            }

        user_message = (
            message["text"]["body"].strip()
        )

        print(
            "[WhatsApp Event] Message: "
            f"'{user_message}'"
        )

        if sender_is_owner:
            print(
                "[Owner Router] Routing owner message"
            )

            # This owner-router call will become tenant-aware
            # in the next migration step.
            owner_response = (
                handle_owner_text_message(
                    phone_number=sender_phone,
                    message_text=user_message,
                )
            )

            send_whatsapp_message(
                to_number=sender_phone,
                message_text=owner_response,
                whatsapp_phone_number_id=(
                    outbound_phone_number_id
                ),
                whatsapp_access_token=(
                    outbound_access_token
                ),
            )

            return {
                "status": (
                    "owner_message_processed"
                ),
                "business_id": business_id,
            }

        now = datetime.now()

        payload_for_agent = InboundPayloadSchema(
            business_id=business_id,
            phone_number=sender_phone,
            incoming_text=user_message,
            weather_summary="",
            day_of_week=now.strftime("%A"),
            time_of_day=get_time_of_day(
                now.hour
            ),
        )

        agent_response = process_agent_message(
            business_id=business_id,
            payload=payload_for_agent,
        )

        send_whatsapp_message(
            to_number=sender_phone,
            message_text=(
                agent_response.text_response
            ),
            whatsapp_phone_number_id=(
                outbound_phone_number_id
            ),
            whatsapp_access_token=(
                outbound_access_token
            ),
        )

        return {
            "status": (
                "customer_message_processed"
            ),
            "business_id": business_id,
        }

    except Exception as error:
        print(
            "[WhatsApp Webhook] Processing error:",
            error,
        )

        return {
            "status": "error",
            "detail": str(error),
        }


@app.post(
    "/v1/process-message",
    response_model=OutboundResponseSchema,
)
def route_transaction_to_agent(
    payload: InboundPayloadSchema,
):
    try:
        business_id = (
            payload.business_id or ""
        ).strip()

        if not business_id:
            default_business = (
                WhatsAppTenantManager
                .get_business_by_phone_number_id(
                    DEFAULT_WHATSAPP_PHONE_NUMBER_ID
                    or ""
                )
            )

            if default_business:
                business_id = (
                    default_business["business_id"]
                )

        if not business_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A valid business_id is required "
                    "for direct message processing."
                ),
            )

        return process_agent_message(
            business_id=business_id,
            payload=payload,
        )

    except HTTPException:
        raise

    except Exception as error:
        print(
            "[Fatal Server Runtime Error]: "
            f"{error}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Internal LangGraph computation error: "
                f"{str(error)}"
            ),
        ) from error


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )