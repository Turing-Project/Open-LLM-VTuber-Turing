"""text to speech"""
import asyncio
from fishaudio import AsyncFishAudio
from fishaudio.utils import play

async def main():
    client = AsyncFishAudio()

    # Simulate streaming LLM response
    async def llm_stream():
        """Simulates text chunks from an LLM."""
        tokens = [
            "The ", "weather ", "today ", "is ", "sunny ",
            "with ", "clear ", "skies. ", "Perfect ",
            "for ", "outdoor ", "activities!"
        ]
        for token in tokens:
            yield token

    # Stream to speech in real-time
    audio_stream = await client.tts.stream_websocket(
        llm_stream(),
        latency="balanced",
        reference_id="2eae72ac40a34d09917441fcb75f9703"
    )
    play(audio_stream)

asyncio.run(main())

"""speech to text"""
import asyncio
from fishaudio import AsyncFishAudio

async def main():
    client = AsyncFishAudio()

    # Transcribe audio
    with open("audio.mp3", "rb") as f:
        result = await client.asr.transcribe(audio=f.read())

    print(f"Transcription: {result.text}")
    print(f"Duration: {result.duration}ms")

asyncio.run(main())