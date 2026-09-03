import logging
from pathlib import Path

from groq import Groq

from config import GROQ_API_KEY, WHISPER_MODEL

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=GROQ_API_KEY)


def transcribe_audio(audio_path: Path, language: str = "en") -> str:
    """Transcribe a downloaded Telegram .oga file using Groq Whisper."""
    logger.info("Transcribing audio path=%s language=%s", audio_path, language)

    try:
        with open(audio_path, "rb") as audio_file:
            # Groq accepts ogg/opus, not Telegram's .oga extension
            result = groq_client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=("voice.ogg", audio_file),
                language=language,
            )

        text = result.text
        logger.info("Transcription complete path=%s text=%r", audio_path, text)
        return text
    except Exception:
        logger.exception("Transcription failed path=%s", audio_path)
        raise
