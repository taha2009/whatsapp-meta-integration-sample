"""
FastAPI backend skeleton for WhatsApp Cloud API (Meta Direct Integration)

This single file contains:
- Webhook verification endpoint (GET /webhook)
- Webhook receiver endpoint (POST /webhook)
- Send message endpoint (POST /send-message)
- Send template endpoint (POST /send-template)
- Media download helper endpoint (GET /media/{media_id})
- Health check endpoint (GET /health)

This file is designed to be:
- Cloud Run friendly
- Easy to extend for LLM agents (LangGraph / OpenAI / Vertex)
- Ready for async processing later

---------------------------------------------------
SETUP INSTRUCTIONS
---------------------------------------------------

1) Install dependencies:

pip install fastapi uvicorn requests python-dotenv

2) Set environment variables:

export WHATSAPP_VERIFY_TOKEN="my_verify_token"
export WHATSAPP_ACCESS_TOKEN="EAAG..."
export WHATSAPP_PHONE_NUMBER_ID="123456789"

3) Run locally:

uvicorn whatsapp_backend:app --reload --port 8000

4) Set webhook URL in Meta Developer Console:

https://your-domain/webhook

Use the same VERIFY_TOKEN there.

---------------------------------------------------
IMPORTANT META CONCEPTS
---------------------------------------------------

Meta calls YOUR server on:
    GET /webhook     -> for verification
    POST /webhook    -> for incoming messages/events

YOU call META servers when:
    Sending messages
    Sending templates
    Downloading media

---------------------------------------------------
PRODUCTION NOTES
---------------------------------------------------

• Always return 200 quickly from POST /webhook
• Do heavy processing async (queue / background task)
• Validate X-Hub-Signature-256 in production
• Store messages in DB for tracking
• Add retry logic for sending messages

"""

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import requests
import os

app = FastAPI()

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


# ---------------------------------------------------
# DATA MODELS
# ---------------------------------------------------

class SendMessage(BaseModel):
    phone: str
    message: str


class SendTemplate(BaseModel):
    phone: str
    template_name: str
    language: str = "en_US"


# ---------------------------------------------------
# 1️⃣ WEBHOOK VERIFICATION (Meta calls this once)
# ---------------------------------------------------
# When you configure webhook in Meta dashboard,
# it sends a GET request with:
#   hub.mode
#   hub.verify_token
#   hub.challenge
#
# You must:
#   - check token matches
#   - return hub.challenge as plain text

@app.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)

    raise HTTPException(status_code=403, detail="Verification failed")


# ---------------------------------------------------
# 2️⃣ WEBHOOK RECEIVER (MOST IMPORTANT ENDPOINT)
# ---------------------------------------------------
# Meta sends EVERYTHING here:
#   - Incoming messages
#   - Voice notes
#   - Images
#   - Delivery status
#   - Button clicks
#
# This is your main entrypoint for chatbot/LLM

@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()

    # NOTE:
    # Always return 200 fast.
    # Do NOT do heavy work here in production.
    # Push to background worker / queue.

    try:
        entry = data["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        # If it's a message event
        if "messages" in value:
            message = value["messages"][0]
            sender_phone = message["from"]
            msg_type = message["type"]

            print("Message from:", sender_phone)
            print("Type:", msg_type)

            # TEXT MESSAGE
            if msg_type == "text":
                text = message["text"]["body"]
                print("Text:", text)

                # HERE:
                # Send text to LLM agent
                # response = llm_agent(text)

                # Example auto reply
                send_whatsapp_text(sender_phone, f"You said: {text}")

            # AUDIO MESSAGE
            elif msg_type == "audio":
                media_id = message["audio"]["id"]
                print("Audio media id:", media_id)

                # Flow:
                # 1) Download audio
                # 2) Convert speech to text
                # 3) Send to LLM

            # IMAGE MESSAGE
            elif msg_type == "image":
                media_id = message["image"]["id"]
                print("Image media id:", media_id)

        # Status updates (delivered/read)
        elif "statuses" in value:
            print("Status update:", value["statuses"])

    except Exception as e:
        print("Webhook parse error:", str(e))

    return {"status": "ok"}


# ---------------------------------------------------
# 3️⃣ SEND TEXT MESSAGE (YOU call Meta)
# ---------------------------------------------------
# Used by:
#   - LLM agent
#   - CRM system
#   - Scheduler
#   - Manual trigger

@app.post("/send-message")
def send_message(payload: SendMessage):
    return send_whatsapp_text(payload.phone, payload.message)


def send_whatsapp_text(phone: str, message: str):
    url = f"{GRAPH_API_BASE}/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    body = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    response = requests.post(url, headers=headers, json=body)

    return {
        "status_code": response.status_code,
        "response": response.json()
    }


# ---------------------------------------------------
# 4️⃣ SEND TEMPLATE MESSAGE
# ---------------------------------------------------
# Required for:
#   - First message to a user
#   - Messages after 24-hour window
#   - Scheduled reminders

@app.post("/send-template")
def send_template(payload: SendTemplate):
    url = f"{GRAPH_API_BASE}/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    body = {
        "messaging_product": "whatsapp",
        "to": payload.phone,
        "type": "template",
        "template": {
            "name": payload.template_name,
            "language": {
                "code": payload.language
            }
        }
    }

    response = requests.post(url, headers=headers, json=body)

    return response.json()


# ---------------------------------------------------
# 5️⃣ DOWNLOAD MEDIA
# ---------------------------------------------------
# Flow:
# 1) Meta gives media_id
# 2) Call:
#    GET /{media_id}
#    -> returns download URL
# 3) Call download URL to fetch file

@app.get("/media/{media_id}")
def get_media(media_id: str):
    # Step 1: Get media URL
    url = f"{GRAPH_API_BASE}/{media_id}"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }

    meta_res = requests.get(url, headers=headers)
    media_url = meta_res.json().get("url")

    # Step 2: Download file
    file_res = requests.get(media_url, headers=headers)

    # You can save to:
    # - disk
    # - GCS
    # - S3

    return {
        "content_type": file_res.headers.get("Content-Type"),
        "size": len(file_res.content)
    }


# ---------------------------------------------------
# 6️⃣ HEALTH CHECK (for Cloud Run / Kubernetes)
# ---------------------------------------------------

@app.get("/health")
def health():
    return {"status": "healthy"}
