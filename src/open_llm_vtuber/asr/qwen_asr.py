import io
import wave
import base64

import numpy as np
from loguru import logger
from openai import OpenAI

from .asr_interface import ASRInterface


class VoiceRecognition(ASRInterface):
    """Alibaba Bailian (DashScope) Qwen-ASR.

    Qwen3-ASR supports the OpenAI-compatible ``chat/completions`` endpoint:
    the audio is sent as a base64 Data URL inside an ``input_audio`` content
    block, and the recognized text comes back as the message content. This
    lets us reuse the ``openai`` SDK (already a project dependency) by simply
    pointing ``base_url`` at DashScope's compatible-mode endpoint.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-asr-flash",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        language: str | None = None,
        enable_itn: bool = False,
    ) -> None:
        logger.info("Initializing Qwen ASR (Alibaba Bailian / DashScope)...")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.language = language or None
        self.enable_itn = enable_itn

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

    def transcribe_np(self, audio: np.ndarray) -> str:
        logger.info("Transcribing audio (QwenASR)...")

        wav_bytes = self._audio_np_to_wav_bytes(audio)
        data_uri = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode()

        asr_options = {"enable_itn": self.enable_itn}
        if self.language:
            asr_options["language"] = self.language

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": data_uri},
                            }
                        ],
                    }
                ],
                stream=False,
                extra_body={"asr_options": asr_options},
            )
        except Exception as e:
            logger.error(f"Qwen ASR transcription failed: {e}")
            return ""

        content = completion.choices[0].message.content
        # content is normally a plain string; be defensive in case the API
        # returns a list of content parts.
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
        else:
            text = content or ""
        return text.strip()
