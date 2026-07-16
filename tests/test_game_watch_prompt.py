import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.open_llm_vtuber.conversations import conversation_handler


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_text(self, raw_message):
        self.messages.append(json.loads(raw_message))


class FakeChatGroupManager:
    def get_client_group(self, client_uid):
        return None


class GameWatchPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_regular_ai_speak_signal_uses_proactive_prompt(self):
        call = await self._trigger_ai_speak_signal({})

        self.assertEqual(call["user_input"], "loaded:proactive_speak_prompt")
        self.assertTrue(call["metadata"]["proactive_speak"])
        self.assertTrue(call["metadata"]["skip_memory"])
        self.assertTrue(call["metadata"]["skip_history"])
        self.assertNotIn("game_watch", call["metadata"])

    async def test_game_watch_ai_speak_signal_uses_game_watch_prompt(self):
        images = [{"source": "screen", "data": "data:image/jpeg;base64,abc", "mime_type": "image/jpeg"}]
        call = await self._trigger_ai_speak_signal(
            {"metadata": {"game_watch": True}, "images": images}
        )

        self.assertEqual(call["user_input"], "loaded:game_watch_prompt")
        self.assertTrue(call["metadata"]["game_watch"])
        self.assertTrue(call["metadata"]["skip_memory"])
        self.assertTrue(call["metadata"]["skip_history"])
        self.assertEqual(call["images"], images)

    async def _trigger_ai_speak_signal(self, data):
        calls = []

        async def fake_process_single_conversation(**kwargs):
            calls.append(kwargs)
            return "ok"

        context = SimpleNamespace(
            system_config=SimpleNamespace(
                tool_prompts={
                    "proactive_speak_prompt": "proactive_speak_prompt",
                    "game_watch_prompt": "game_watch_prompt",
                }
            )
        )
        current_conversation_tasks = {}
        websocket = FakeWebSocket()

        with (
            patch.object(
                conversation_handler.prompt_loader,
                "load_util",
                side_effect=lambda prompt_name: f"loaded:{prompt_name}",
            ),
            patch.object(
                conversation_handler,
                "process_single_conversation",
                side_effect=fake_process_single_conversation,
            ),
            patch.object(conversation_handler.np.random, "choice", return_value="test"),
        ):
            await conversation_handler.handle_conversation_trigger(
                msg_type="ai-speak-signal",
                data=data,
                client_uid="client-1",
                context=context,
                websocket=websocket,
                client_contexts={},
                client_connections={},
                chat_group_manager=FakeChatGroupManager(),
                received_data_buffers={"client-1": np.array([])},
                current_conversation_tasks=current_conversation_tasks,
                broadcast_to_group=None,
            )
            await current_conversation_tasks["client-1"]

        self.assertEqual(websocket.messages[0]["type"], "full-text")
        self.assertEqual(len(calls), 1)
        return calls[0]


if __name__ == "__main__":
    unittest.main()
