from contextlib import asynccontextmanager
import logging

import httpx
from fastapi import BackgroundTasks, FastAPI, Request

from api import router as api_router
from config import TG
from db import init_db
from handlers import handle_command, is_command
from logging_config import setup_logging
from pipeline import process_transaction_and_notify
from voice import process_voice_note

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting expense tracker server")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down expense tracker server")


app = FastAPI(lifespan=lifespan)
app.include_router(api_router)


@app.post("/")
async def webhook(req: Request, background_tasks: BackgroundTasks):
    body = await req.json()
    message = body.get("message", {})
    if not message or "chat" not in message:
        logger.debug("Ignoring update without message/chat")
        return {"ok": True}

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")
    text = message.get("text", "") or ""
    voice = message.get("voice")

    if voice:
        logger.info(
            "Voice message received chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        background_tasks.add_task(
            process_voice_note,
            voice["file_id"],
            voice["file_unique_id"],
            chat_id,
            message_id,
        )
        reply_text = "Voice note received."
    elif is_command(text):
        logger.info(
            "Command received chat_id=%s message_id=%s command=%s",
            chat_id,
            message_id,
            text.split()[0],
        )
        reply_text = await handle_command(text, chat_id, message_id)
    elif text:
        logger.info(
            "Text expense received chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        background_tasks.add_task(
            process_transaction_and_notify,
            text,
            chat_id,
            message_id,
        )
        reply_text = "Got it, logging..."
    else:
        logger.debug("Ignoring unsupported update chat_id=%s", chat_id)
        return {"ok": True}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TG}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": reply_text,
            },
        )
        if response.is_error:
            logger.error(
                "Failed to send Telegram reply chat_id=%s status=%s body=%s",
                chat_id,
                response.status_code,
                response.text,
            )
        else:
            logger.debug("Sent immediate reply chat_id=%s", chat_id)

    return {"ok": True}
