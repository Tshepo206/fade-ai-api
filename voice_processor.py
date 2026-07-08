import os
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)


def get_whatsapp_media_url(media_id: str) -> str:
    url = f"https://graph.facebook.com/v20.0/{media_id}"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    response = requests.get(url, headers=headers)

    print("Media URL response:")
    print("Status:", response.status_code)
    print("Body:", response.text)

    response.raise_for_status()

    media_data = response.json()
    return media_data["url"]


def download_whatsapp_audio(media_url: str, output_path: str = "voice_note.ogg") -> str:
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    response = requests.get(media_url, headers=headers)

    print("Audio download response:")
    print("Status:", response.status_code)

    response.raise_for_status()

    with open(output_path, "wb") as audio_file:
        audio_file.write(response.content)

    return output_path


def transcribe_audio(audio_path: str) -> str:
    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            prompt=(
        "This is a South African barber shop called Fade. "
        "Common customer names include Tshepo, Lebo, Thabo, Sipho, Sibusiso, Kabelo, Themba, Mpho, Mandla, Bongi, KG. "
        "Common barber services include haircut, pay cut, blade cut, shave, beard trim, combo, kiddies cut, hair dye, bleach, powder. "
        "Common payment methods include cash and card. "
        "Examples: Tshepo haircut 180 card. Lebo shave 80 cash. Thabo combo 220 card."
    )
)
    return transcript.text


def process_whatsapp_voice_note(media_id: str) -> str:
    media_url = get_whatsapp_media_url(media_id)
    audio_path = download_whatsapp_audio(media_url)
    transcript = transcribe_audio(audio_path)

    print("Voice note transcript:")
    print(transcript)

    return transcript