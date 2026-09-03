import logging
import subprocess
import tempfile
from pathlib import Path

from groq import Groq

from config import GROQ_API_KEY, WHISPER_MODEL

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=GROQ_API_KEY)


def transcribe_audio(audio_path: Path, language: str = "en") -> str:
    """Convert a downloaded .oga file to text using Groq Whisper."""
    logger.info("Transcribing audio path=%s language=%s", audio_path, language)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        mp3_path = tmp.name

    try:
        subprocess.run(
            ["ffmpeg", "-i", str(audio_path), mp3_path, "-y", "-loglevel", "quiet"],
            check=True,
        )

        with open(mp3_path, "rb") as audio_file:
            result = groq_client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=("voice.mp3", audio_file),
                language=language,
            )

        text = result.text
        logger.info("Transcription complete path=%s text=%r", audio_path, text)
        return text
    except Exception:
        logger.exception("Transcription failed path=%s", audio_path)
        raise
    finally:
        Path(mp3_path).unlink(missing_ok=True)
