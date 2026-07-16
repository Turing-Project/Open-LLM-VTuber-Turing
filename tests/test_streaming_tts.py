import asyncio
import json
import os
import tempfile
import unittest
import wave
from types import SimpleNamespace

import numpy as np

from src.open_llm_vtuber.conversations.single_conversation import (
    process_single_conversation,
)
from src.open_llm_vtuber.agent.output_types import Actions, DisplayText, SentenceOutput
from src.open_llm_vtuber.message_handler import message_handler


class FakeASR:
    async def async_transcribe_np(self, audio):
        return "给我讲个笑话。"


class FakeAgent:
    def __init__(self, tokens):
        self.tokens = tokens
        self.chat_called = False

    async def stream_raw_text(self, batch_input):
        for token in self.tokens:
            await asyncio.sleep(0)
            yield token

    async def chat(self, batch_input):
        self.chat_called = True
        if False:
            yield None


class FakeSentenceAgent:
    def __init__(self, sentences):
        self.sentences = sentences

    async def chat(self, batch_input):
        for sentence in self.sentences:
            yield SentenceOutput(
                display_text=DisplayText(text=sentence),
                tts_text=sentence,
                actions=Actions(),
            )


class StreamingTTS:
    async def stream_llm_audio(self, text_stream):
        async for event in text_stream:
            text = getattr(event, "text", "")
            if text:
                yield f"audio:{text}".encode("utf-8")


class EmptyStreamingTTS:
    async def stream_llm_audio(self, text_stream):
        async for _event in text_stream:
            pass
        if False:
            yield b""

    async def async_generate_audio(self, text, file_name_no_ext=None):
        audio_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio_file.close()
        with wave.open(audio_file.name, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x01\x00" * 1600)
        return audio_file.name

    def remove_file(self, filepath, verbose=True):
        if os.path.exists(filepath):
            os.remove(filepath)


class ErrorAfterFirstChunkTTS:
    async def stream_llm_audio(self, text_stream):
        async for event in text_stream:
            text = getattr(event, "text", "")
            if text:
                yield b"first-audio"
                raise RuntimeError("stream broke after first chunk")


def make_context(agent, tts):
    return SimpleNamespace(
        asr_engine=FakeASR(),
        agent_engine=agent,
        tts_engine=tts,
        character_config=SimpleNamespace(
            conf_uid="test_conf",
            character_name="瞳宝",
            human_name="用户",
            avatar="",
        ),
        history_uid=None,
        live2d_model=None,
        translate_engine=None,
    )


class StreamingTTSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client_uid = "test-client"
        message_handler.cleanup_client(self.client_uid)

    async def asyncTearDown(self):
        message_handler.cleanup_client(self.client_uid)

    async def test_streaming_tts_sends_start_chunks_and_end(self):
        agent = FakeAgent(["你好", "，世界"])
        sent_messages = []

        async def websocket_send(raw_message):
            message = json.loads(raw_message)
            sent_messages.append(message)
            if message["type"] == "audio-stream-end":
                asyncio.create_task(self._send_playback_complete_soon())

        response = await process_single_conversation(
            context=make_context(agent, StreamingTTS()),
            websocket_send=websocket_send,
            client_uid=self.client_uid,
            user_input=np.zeros(1600, dtype=np.float32),
            metadata={"skip_history": True},
        )

        message_types = [message["type"] for message in sent_messages]
        self.assertEqual(response, "你好，世界")
        self.assertIn("audio-stream-start", message_types)
        self.assertIn("audio-stream-chunk", message_types)
        self.assertIn("audio-stream-end", message_types)
        self.assertFalse(agent.chat_called)

    async def test_empty_stream_falls_back_without_waiting_for_playback(self):
        agent = FakeAgent(["这段不会播"])
        sent_messages = []

        async def websocket_send(raw_message):
            message = json.loads(raw_message)
            sent_messages.append(message)
            if message["type"] == "backend-synth-complete":
                asyncio.create_task(self._send_playback_complete_soon())

        response = await asyncio.wait_for(
            process_single_conversation(
                context=make_context(agent, EmptyStreamingTTS()),
                websocket_send=websocket_send,
                client_uid=self.client_uid,
                user_input=np.zeros(1600, dtype=np.float32),
                metadata={"skip_history": True},
            ),
            timeout=1,
        )

        message_types = [message["type"] for message in sent_messages]
        self.assertEqual(response, "这段不会播")
        self.assertIn("audio-stream-error", message_types)
        self.assertNotIn("audio-stream-end", message_types)
        self.assertFalse(agent.chat_called)

    async def test_error_after_first_chunk_closes_stream_without_fallback(self):
        agent = FakeAgent(["后续文本"])
        sent_messages = []

        async def websocket_send(raw_message):
            message = json.loads(raw_message)
            sent_messages.append(message)
            if message["type"] == "audio-stream-end":
                asyncio.create_task(self._send_playback_complete_soon())

        response = await process_single_conversation(
            context=make_context(agent, ErrorAfterFirstChunkTTS()),
            websocket_send=websocket_send,
            client_uid=self.client_uid,
            user_input=np.zeros(1600, dtype=np.float32),
            metadata={"skip_history": True},
        )

        message_types = [message["type"] for message in sent_messages]
        self.assertEqual(response, "后续文本")
        self.assertIn("audio-stream-chunk", message_types)
        self.assertIn("audio-stream-end", message_types)
        self.assertNotIn("audio-stream-error", message_types)
        self.assertFalse(agent.chat_called)

    async def test_sentence_path_filters_reasoning_markup_before_tts(self):
        agent = FakeSentenceAgent(
            [
                "[thinking]The player is looking at a repository.",
                "[neutral] 哦？在看项目仓库呢。",
            ]
        )
        sent_messages = []

        async def websocket_send(raw_message):
            message = json.loads(raw_message)
            sent_messages.append(message)
            if message["type"] == "backend-synth-complete":
                asyncio.create_task(self._send_playback_complete_soon())

        response = await process_single_conversation(
            context=make_context(agent, EmptyStreamingTTS()),
            websocket_send=websocket_send,
            client_uid=self.client_uid,
            user_input="game watch prompt",
            metadata={"skip_history": True},
        )

        display_texts = [
            message.get("display_text", {}).get("text")
            for message in sent_messages
            if message.get("type") == "audio"
        ]
        self.assertEqual(response, "哦？在看项目仓库呢。")
        self.assertEqual(display_texts, ["哦？在看项目仓库呢。"])

    async def _send_playback_complete_soon(self):
        await asyncio.sleep(0.01)
        message_handler.handle_message(
            self.client_uid, {"type": "frontend-playback-complete"}
        )


if __name__ == "__main__":
    unittest.main()
