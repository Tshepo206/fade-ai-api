import os
import uvicorn
import requests

from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Optional

from agent import agent_engine
from db_manager import BarberDatabaseManager
from personality import get_time_of_day
from voice_processor import process_whatsapp_voice_note
from owner_router import handle_owner_text_message, handle_typed_bookkeeping
from dashboard_routes import router as dashboard_router
from fastapi.middleware.cors import CORSMiddleware


VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "fade-ai-verify-token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
OWNER_PHONE_NUMBER = os.getenv("OWNER_PHONE_NUMBER", "").strip()


app = FastAPI(
    title="AI Barber Receptionist Routing Portal",
    description="Processes WhatsApp messages and manages booking state.",
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
    phone_number: str = Field(..., examples=["27810000000"])
    incoming_text: str = Field(..., examples=["Hi"])
    weather_summary: str = Field(default="", examples=[""])
    day_of_week: str = Field(..., examples=["Friday"])
    time_of_day: str = Field(..., examples=["afternoon"])


class OutboundResponseSchema(BaseModel):
    current_state: str
    voice_note_script: Optional[str] = None
    text_response: str


@app.get("/")
def check_health():
    return {
        "status": "healthy",
        "service": "AI Barber Core Engine Active",
    }


@app.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    print("Webhook verification request received")

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("Webhook verified successfully.")
        return PlainTextResponse(content=hub_challenge)

    print("Webhook verification failed.")
    return PlainTextResponse(
        content="Verification failed",
        status_code=403,
    )


def send_whatsapp_message(to_number: str, message_text: str):
    if not WHATSAPP_ACCESS_TOKEN:
        raise ValueError("Missing WHATSAPP_ACCESS_TOKEN in .env")

    if not WHATSAPP_PHONE_NUMBER_ID:
        raise ValueError("Missing WHATSAPP_PHONE_NUMBER_ID in .env")

    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
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

    response = requests.post(url, headers=headers, json=data)

    print("WhatsApp send response:")
    print("Status:", response.status_code)
    print("Body:", response.text)

    return response


def is_owner(sender_phone: str) -> bool:
    return sender_phone.strip() == OWNER_PHONE_NUMBER


@app.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(request: Request):
    payload = await request.json()

    print("\n==============================")
    print("Incoming WhatsApp Webhook")
    print(payload)
    print("==============================\n")

    try:
        value = payload["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            print("No customer message found. Ignoring status/update webhook.")
            return {"status": "ignored"}

        message = value["messages"][0]
        message_type = message.get("type")
        sender_phone = message.get("from", "").strip()

        if not sender_phone:
            print("No sender phone found.")
            return {"status": "ignored_no_sender"}

        print(f"[WhatsApp Live Event] Phone: {sender_phone}")
        print(f"[WhatsApp Live Event] Type: {message_type}")

        if message_type == "audio":
            if not is_owner(sender_phone):
                send_whatsapp_message(
                    to_number=sender_phone,
                    message_text="Please send a text message for bookings.",
                )
                return {"status": "customer_audio_rejected"}

            media_id = message["audio"]["id"]
            transcript = process_whatsapp_voice_note(media_id)

            print(f"[Owner Voice Transcript] {transcript}")

            owner_response = handle_typed_bookkeeping(
                phone_number=sender_phone,
                message_text=transcript,
            )

            send_whatsapp_message(
                to_number=sender_phone,
                message_text=f"Transcript heard:\n{transcript}\n\n{owner_response}",
            )

            return {
                "status": "owner_voice_processed",
                "transcript": transcript,
            }

        if message_type != "text":
            send_whatsapp_message(
                to_number=sender_phone,
                message_text="Please send a text message or voice note for now.",
            )

            return {"status": "non_text_message_handled"}

        user_message = message["text"]["body"].strip()

        print(f"[WhatsApp Live Event] Message: '{user_message}'")

        if is_owner(sender_phone):
            print("[Owner Router] Routing owner message")

            owner_response = handle_owner_text_message(
                phone_number=sender_phone,
                message_text=user_message,
            )

            send_whatsapp_message(
                to_number=sender_phone,
                message_text=owner_response,
            )

            return {"status": "owner_message_processed"}

        now = datetime.now()
        time_of_day = get_time_of_day(now.hour)

        payload_for_agent = InboundPayloadSchema(
            phone_number=sender_phone,
            incoming_text=user_message,
            weather_summary="",
            day_of_week=now.strftime("%A"),
            time_of_day=time_of_day,
        )

        agent_response = route_transaction_to_agent(payload_for_agent)

        send_whatsapp_message(
            to_number=sender_phone,
            message_text=agent_response.text_response,
        )

        return {"status": "customer_message_processed"}

    except Exception as error:
        print("WhatsApp webhook processing error:", error)

        return {
            "status": "error",
            "detail": str(error),
        }


@app.post("/v1/process-message", response_model=OutboundResponseSchema)
def route_transaction_to_agent(payload: InboundPayloadSchema):
    try:
        sender_phone = payload.phone_number.strip()
        user_message = payload.incoming_text.strip()

        print(f"\n[Webhook Event] Phone: {sender_phone}")
        print(f"[Webhook Event] Message: '{user_message}'")

        session_data = BarberDatabaseManager.get_or_create_session(sender_phone)

        current_db_state = session_data.get(
            "current_state",
            "INITIAL_CONTACT",
        )

        cached_context = session_data.get("context_data", {}) or {}

        print(f"[Database Sync] Current state: {current_db_state}")

        state_input = {
            "phone_number": sender_phone,
            "current_state": current_db_state,
            "incoming_text": user_message,
            "weather_summary": payload.weather_summary,
            "day_of_week": payload.day_of_week,
            "time_of_day": payload.time_of_day,
            "selected_service": cached_context.get("selected_service"),
            "validated_date": cached_context.get("validated_date"),
            "validated_time": cached_context.get("validated_time"),
            "customer_name": cached_context.get("customer_name"),
            "voice_note_script": None,
            "text_response": "",
        }

        result_state = agent_engine.invoke(state_input)

        next_system_state = result_state.get(
            "current_state",
            current_db_state,
        )

        updated_context_payload = {
            "selected_service": result_state.get("selected_service"),
            "validated_date": result_state.get("validated_date"),
            "validated_time": result_state.get("validated_time"),
            "customer_name": result_state.get("customer_name"),
        }

        print(f"[Graph Transition] {current_db_state} -> {next_system_state}")

        BarberDatabaseManager.update_session_state(
            phone_number=sender_phone,
            new_state=next_system_state,
            context_updates=updated_context_payload,
        )

        return OutboundResponseSchema(
            current_state=next_system_state,
            voice_note_script=result_state.get("voice_note_script"),
            text_response=result_state.get("text_response", ""),
        )

    except Exception as error:
        print(f"[Fatal Server Runtime Malfunction]: {error}")

        raise HTTPException(
            status_code=500,
            detail=f"Internal LangGraph computation error: {str(error)}",
        )
    
@app.get("/health")
def health():
        return {
            "status": "healthy",
            "service": "Fade AI",
            "version": "1.0.0"
        }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

  