import asyncio
import logging
from pathlib import Path

import httpx

from config import BOT_TOKEN, TG
from pipeline import process_transaction_and_notify
from transcribe import transcribe_audio

logger = logging.getLogger(__name__)

VOICE_DIR = Path(__file__).parent / "voice_files"
VOICE_DIR.mkdir(exist_ok=True)


async def download_voice(file_id: str, file_unique_id: str, chat_id: int) -> Path:
    logger.info("Downloading voice chat_id=%s file_id=%s", chat_id, file_id)
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{TG}/getFile", params={"file_id": file_id})
        response.raise_for_status()
        file_path = response.json()["result"]["file_path"]

        audio = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
        audio.raise_for_status()

    dest = VOICE_DIR / f"{chat_id}_{file_unique_id}.oga"
    dest.write_bytes(audio.content)
    logger.info("Saved voice file chat_id=%s path=%s bytes=%s", chat_id, dest, len(audio.content))
    return dest


async def process_voice_note(
    file_id: str,
    file_unique_id: str,
    chat_id: int,
    message_id: int,
) -> str:
    """Download a voice note, transcribe it, log the transaction, and reply."""
    logger.info(
        "Processing voice note chat_id=%s message_id=%s",
        chat_id,
        message_id,
    )
    audio_path = None
    try:
        audio_path = await download_voice(file_id, file_unique_id, chat_id)
        text = await asyncio.to_thread(transcribe_audio, audio_path)
        logger.info("Transcribed voice chat_id=%s text=%r", chat_id, text)
        return await process_transaction_and_notify(text, chat_id, message_id)
    except Exception:
        logger.exception(
            "Voice note processing failed chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        await _send_error(chat_id, "Failed to process voice note. Please try typing the expense.")
        raise
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink()
            logger.info("Deleted voice file path=%s", audio_path)


async def _send_error(chat_id: int, message: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TG}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )
