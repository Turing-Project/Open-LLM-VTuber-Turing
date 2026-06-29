import io
import os
import wave

import numpy as np
from fishaudio import AsyncFishAudio, FishAudio
from loguru import logger

from .asr_interface import ASRInterface


def _resolve_fish_api_key(api_key: str) -> str:
    resolved = api_key or os.environ.get("FISH_API_KEY")
    if not resolved:
        raise ValueError(
            "Fish Audio API key is missing. Set api_key in conf.yaml "
            "(fish_audio_asr / fish_audio_tts), or set the FISH_API_KEY environment variable."
        )
    return resolved


class VoiceRecognition(ASRInterface):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.fish.audio",
        language: str | None = None,
    ) -> None:
        logger.info("Initializing Fish Audio ASR...")
        resolved_api_key = _resolve_fish_api_key(api_key)
        self.client = FishAudio(api_key=resolved_api_key, base_url=base_url)
        self.async_client = AsyncFishAudio(
            api_key=resolved_api_key, base_url=base_url
        )
        self.language = language or None

    def _audio_np_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        audio = np.clip(audio, -1, 1)
        audio_integer = (audio * 32767).astype(np.int16)
        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, "wb") as wf:
            wf.setnchannels(self.NUM_CHANNELS)
            wf.setsampwidth(self.SAMPLE_WIDTH)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(audio_integer.tobytes())
        return audio_buffer.getvalue()

    async def async_transcribe_np(self, audio: np.ndarray) -> str:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        audio_bytes = self._audio_np_to_wav_bytes(audio)
        return await self._transcribe_async(audio_bytes)

    def transcribe_np(self, audio: np.ndarray) -> str:
        logger.info("Transcribing audio (FishAudioASR)...")
        audio_bytes = self._audio_np_to_wav_bytes(audio)
        kwargs = {"audio": audio_bytes}
        if self.language:
            kwargs["language"] = self.language
        result = self.client.asr.transcribe(**kwargs)
        return result.text

    async def _transcribe_async(self, audio_bytes: bytes) -> str:
        logger.info("Transcribing audio (FishAudioASR)...")
        kwargs = {"audio": audio_bytes}
        if self.language:
            kwargs["language"] = self.language
        result = await self.async_client.asr.transcribe(**kwargs)
        return result.text
