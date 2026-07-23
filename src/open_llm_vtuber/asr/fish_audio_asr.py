import io
import wave

import httpx
import numpy as np
from loguru import logger

from .asr_interface import ASRInterface


class VoiceRecognition(ASRInterface):
    def __init__(
        self,
        api_key: str = "",
        base_url: str = "http://124.221.95.34:8000/transcribe",
        language: str | None = None,
    ) -> None:
        logger.info("Initializing HTTP ASR endpoint...")
        self.api_key = api_key or ""
        self.endpoint = base_url.rstrip("/")
        self.language = language or "zh-CN"

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
        logger.info("Transcribing audio (HTTP ASR endpoint)...")
        audio_bytes = self._audio_np_to_wav_bytes(audio)
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"language": self.language}
        headers = self._get_headers()

        try:
            with httpx.Client(timeout=30.0, trust_env=False) as client:
                response = client.post(
                    self.endpoint,
                    files=files,
                    data=data,
                    headers=headers,
                )
                response.raise_for_status()
                return self._extract_text(response)
        except Exception as e:
            logger.error(f"HTTP ASR transcription failed: {e}")
            return ""

    async def _transcribe_async(self, audio_bytes: bytes) -> str:
        logger.info("Transcribing audio (HTTP ASR endpoint)...")
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"language": self.language}
        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                response = await client.post(
                    self.endpoint,
                    files=files,
                    data=data,
                    headers=headers,
                )
                response.raise_for_status()
                return self._extract_text(response)
        except Exception as e:
            logger.error(f"HTTP ASR transcription failed: {e}")
            return ""

    def _get_headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _extract_text(self, response: httpx.Response) -> str:
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response.text.strip()

        payload = response.json()
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            for key in ("text", "transcription", "result"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value.strip()
            data = payload.get("data")
            if isinstance(data, dict):
                for key in ("text", "transcription", "result"):
                    value = data.get(key)
                    if isinstance(value, str):
                        return value.strip()

        logger.warning(f"Unexpected ASR response format: {payload}")
        return ""
