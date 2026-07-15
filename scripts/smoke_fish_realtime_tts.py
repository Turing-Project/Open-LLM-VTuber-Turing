import asyncio
import time

import yaml
from fishaudio import AsyncFishAudio
from fishaudio.types import FlushEvent, TextEvent, TTSConfig


FISH_TTS_MODEL = "s2-pro"


def load_fish_tts_settings() -> dict:
    with open("conf.yaml", "r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    return config["character_config"]["tts_config"]["fish_audio_tts"]


async def main() -> None:
    settings = load_fish_tts_settings()
    api_key = settings.get("api_key") or None
    base_url = settings.get("base_url") or "https://api.fish.audio"
    reference_id = settings.get("reference_id")
    latency = settings.get("latency") or "balanced"

    client = AsyncFishAudio(api_key=api_key, base_url=base_url)
    print(
        "fish smoke: "
        f"base_url={base_url} "
        f"api_key={'set' if api_key else 'missing'} "
        f"reference_id={'set' if reference_id else 'missing'} "
        f"latency={latency} "
        f"model={FISH_TTS_MODEL}"
    )

    started_at = time.perf_counter()
    try:
        audio = await client.tts.convert(
            text="你好，我想一下。",
            reference_id=reference_id,
            latency=latency,
            format="mp3",
            model=FISH_TTS_MODEL,
        )
        print(
            f"convert ok: bytes={len(audio)} "
            f"elapsed={time.perf_counter() - started_at:.3f}s"
        )
    except Exception as exc:
        print(
            f"convert failed: {type(exc).__name__}: {exc!r} "
            f"elapsed={time.perf_counter() - started_at:.3f}s"
        )

    async def text_stream():
        yield TextEvent(text="你好，我想一下。")
        yield FlushEvent()
        await asyncio.sleep(2)

    started_at = time.perf_counter()
    total_bytes = 0
    first_chunk_elapsed = None
    config = TTSConfig(
        format="mp3",
        latency=latency,
        reference_id=reference_id,
        chunk_length=100,
        min_chunk_length=50,
    )
    try:
        async for chunk in client.tts.stream_websocket(
            text_stream(),
            reference_id=reference_id,
            format="mp3",
            latency=latency,
            config=config,
            model=FISH_TTS_MODEL,
        ):
            if not chunk:
                continue
            total_bytes += len(chunk)
            if first_chunk_elapsed is None:
                first_chunk_elapsed = time.perf_counter() - started_at
                print(
                    f"stream first chunk: bytes={len(chunk)} "
                    f"elapsed={first_chunk_elapsed:.3f}s"
                )
        print(
            f"stream ok: total={total_bytes} "
            f"elapsed={time.perf_counter() - started_at:.3f}s"
        )
    except Exception as exc:
        print(
            f"stream failed: {type(exc).__name__}: {exc!r} "
            f"elapsed={time.perf_counter() - started_at:.3f}s"
        )


if __name__ == "__main__":
    asyncio.run(main())
