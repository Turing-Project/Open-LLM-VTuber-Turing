import requests
from loguru import logger

from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    """Alibaba Bailian (DashScope) Qwen-TTS.

    Unlike ASR, Qwen-TTS does NOT support the OpenAI-compatible endpoint. It
    uses the DashScope native protocol (via the ``dashscope`` SDK), and the
    API returns a URL pointing to the generated audio (valid for 24h) rather
    than raw bytes. We call the model, pull the URL out of the response, then
    download and cache the audio locally so the rest of the pipeline can treat
    it like any other TTS engine.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-tts-flash",
        voice: str = "Cherry",
        language_type: str = "Chinese",
        base_http_api_url: str = "https://dashscope.aliyuncs.com/api/v1",
        audio_format: str = "wav",
    ):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.language_type = language_type
        self.base_http_api_url = base_http_api_url
        self.file_extension = audio_format
        logger.info(
            f"Qwen TTS (DashScope) initialized: model={model}, voice={voice}, "
            f"language_type={language_type}"
        )

    def generate_audio(self, text: str, file_name_no_ext=None) -> str:
        file_name = self.generate_cache_file_name(
            file_name_no_ext, self.file_extension
        )

        try:
            import dashscope

            dashscope.base_http_api_url = self.base_http_api_url
            response = dashscope.MultiModalConversation.call(
                model=self.model,
                api_key=self.api_key,
                text=text,
                voice=self.voice,
                language_type=self.language_type,
                stream=False,
            )

            audio_url = self._extract_audio_url(response)
            if not audio_url:
                logger.critical(f"Qwen TTS: no audio URL in response: {response}")
                return None

            audio_resp = requests.get(audio_url, timeout=30)
            audio_resp.raise_for_status()
            with open(file_name, "wb") as f:
                f.write(audio_resp.content)
        except Exception as e:
            logger.critical(f"Qwen TTS failed to generate audio: {e}")
            return None

        return file_name

    @staticmethod
    def _extract_audio_url(response) -> str | None:
        """Defensively pull the audio URL out of a DashScope response.

        The response may be a dict or an SDK object; the audio URL normally
        lives at ``output.audio.url``.
        """

        def _get(obj, key):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        audio = _get(_get(response, "output"), "audio")
        return _get(audio, "url")
