from typing import Literal
import os

from fishaudio import AsyncFishAudio, FishAudio
from loguru import logger

from .tts_interface import TTSInterface


def _resolve_fish_api_key(api_key: str) -> str:
    resolved = api_key or os.environ.get("FISH_API_KEY")
    if not resolved:
        raise ValueError(
            "Fish Audio API key is missing. Set api_key in conf.yaml "
            "(fish_audio_asr / fish_audio_tts), or set the FISH_API_KEY environment variable."
        )
    return resolved


class TTSEngine(TTSInterface):
    """Fish Audio TTS using the official fish-audio-sdk."""

    def __init__(
        self,
        api_key: str,
        reference_id: str = "2eae72ac40a34d09917441fcb75f9703",
        latency: Literal["normal", "balanced"] = "balanced",
        base_url: str = "https://api.fish.audio",
        audio_format: Literal["wav", "pcm", "mp3", "opus"] = "wav",
    ):
        logger.info(
            f"Fish Audio TTS initialized: base_url={base_url}, "
            f"reference_id={reference_id}, latency={latency}"
        )
        self.reference_id = reference_id
        self.latency = latency
        self.audio_format = audio_format
        self.file_extension = "wav" if audio_format == "pcm" else audio_format
        resolved_api_key = _resolve_fish_api_key(api_key)
        self.client = FishAudio(api_key=resolved_api_key, base_url=base_url)
        self.async_client = AsyncFishAudio(
            api_key=resolved_api_key, base_url=base_url
        )

    def generate_audio(self, text, file_name_no_ext=None):
        file_name = self.generate_cache_file_name(
            file_name_no_ext, self.file_extension
        )

        try:
            audio = self.client.tts.convert(
                text=text,
                reference_id=self.reference_id,
                latency=self.latency,
                format=self.audio_format,
            )
            with open(file_name, "wb") as f:
                f.write(audio)
        except Exception as e:
            logger.critical(f"Fish Audio TTS failed to generate audio: {e}")
            return None

        return file_name

    async def async_generate_audio(self, text: str, file_name_no_ext=None) -> str:
        file_name = self.generate_cache_file_name(
            file_name_no_ext, self.file_extension
        )

        try:
            audio = await self.async_client.tts.convert(
                text=text,
                reference_id=self.reference_id,
                latency=self.latency,
                format=self.audio_format,
            )
            with open(file_name, "wb") as f:
                f.write(audio)
        except Exception as e:
            logger.critical(f"Fish Audio TTS failed to generate audio: {e}")
            return None

        return file_name
