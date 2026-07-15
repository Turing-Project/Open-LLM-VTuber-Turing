import asyncio
import json
import re
import uuid
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from loguru import logger

from ..agent.output_types import DisplayText, Actions
from ..live2d_model import Live2dModel
from ..tts.tts_interface import TTSInterface
from ..utils.stream_audio import prepare_audio_payload
from .types import WebSocketSend


class TTSTaskManager:
    """Manages TTS tasks and ensures ordered delivery to frontend while allowing parallel TTS generation"""

    def __init__(self, perf_trace: Optional[Dict[str, Any]] = None) -> None:
        self.task_list: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        # Queue to store ordered payloads
        self._payload_queue: asyncio.Queue[Dict] = asyncio.Queue()
        # Task to handle sending payloads in order
        self._sender_task: Optional[asyncio.Task] = None
        # Counter for maintaining order
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        self._perf_trace = perf_trace or {}
        self._conversation_started_at = time.perf_counter()
        self._tts_timeline_logged = False
        self._tts_start_timeline_logged = False
        self._audio_send_timeline_logged = False
        self._playback_expected = False

    def _format_timeline_offset(self) -> str:
        started_at = self._perf_trace.get("timeline_started_at")
        if not isinstance(started_at, (int, float)):
            started_at = self._conversation_started_at
        elapsed = max(0.0, time.perf_counter() - started_at)
        minutes = int(elapsed // 60)
        seconds = elapsed % 60
        return f"{minutes}:{seconds:06.3f}"

    def log_timeline(self, message: str) -> None:
        timeline_events = self._perf_trace.get("timeline_events")
        if isinstance(timeline_events, list):
            timeline_events.append(
                {
                    "offset": self._format_timeline_offset(),
                    "message": message,
                }
            )

    def print_timeline_summary(self) -> None:
        request_id = self._perf_trace.get("request_id", "unknown")
        timeline_events = self._perf_trace.get("timeline_events")
        if not isinstance(timeline_events, list) or not timeline_events:
            return

        lines = [
            "",
            f"========== Conversation Timeline | request={request_id} ==========",
        ]
        lines.extend(
            f"{event.get('offset', '0:00.000')}  {event.get('message', '')}"
            for event in timeline_events
        )
        lines.append("==============================================================")
        logger.info("\n".join(lines))

    def mark_playback_expected(self) -> None:
        self._playback_expected = True

    def clear_playback_expected(self) -> None:
        self._playback_expected = False

    @property
    def playback_expected(self) -> bool:
        return self._playback_expected

    async def speak(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        websocket_send: WebSocketSend,
    ) -> None:
        """
        Queue a TTS task while maintaining order of delivery.

        Args:
            tts_text: Text to synthesize
            display_text: Text to display in UI
            actions: Live2D model actions
            live2d_model: Live2D model instance
            tts_engine: TTS engine instance
            websocket_send: WebSocket send function
        """
        if len(re.sub(r'[\s.,!?，。！？\'"』」）】\s]+', "", tts_text)) == 0:
            logger.debug("Empty TTS text, sending silent display payload")
            # Get current sequence number for silent payload
            current_sequence = self._sequence_counter
            self._sequence_counter += 1

            # Start sender task if not running
            if not self._sender_task or self._sender_task.done():
                self._sender_task = asyncio.create_task(
                    self._process_payload_queue(websocket_send)
                )

            await self._send_silent_payload(display_text, actions, current_sequence)
            return

        logger.debug(
            f"🏃Queuing TTS task for: '''{tts_text}''' (by {display_text.name})"
        )

        # Get current sequence number
        current_sequence = self._sequence_counter
        self._sequence_counter += 1

        # Start sender task if not running
        if not self._sender_task or self._sender_task.done():
            self._sender_task = asyncio.create_task(
                self._process_payload_queue(websocket_send)
            )

        # Create and queue the TTS task
        task = asyncio.create_task(
            self._process_tts(
                tts_text=tts_text,
                display_text=display_text,
                actions=actions,
                live2d_model=live2d_model,
                tts_engine=tts_engine,
                sequence_number=current_sequence,
            )
        )
        self.task_list.append(task)

    async def _process_payload_queue(self, websocket_send: WebSocketSend) -> None:
        """
        Process and send payloads in correct order.
        Runs continuously until all payloads are processed.
        """
        buffered_payloads: Dict[int, Dict] = {}

        while True:
            try:
                # Get payload from queue
                payload, sequence_number = await self._payload_queue.get()
                buffered_payloads[sequence_number] = payload

                # Send payloads in order
                while self._next_sequence_to_send in buffered_payloads:
                    next_payload = buffered_payloads.pop(self._next_sequence_to_send)
                    await websocket_send(json.dumps(next_payload))
                    perf_trace = next_payload.get("perf_trace") or {}
                    if (
                        not self._audio_send_timeline_logged
                        and next_payload.get("audio")
                        and not perf_trace.get("silent")
                    ):
                        self._audio_send_timeline_logged = True
                        self.log_timeline("首段音频已发送前端")
                    self._next_sequence_to_send += 1

                self._payload_queue.task_done()

            except asyncio.CancelledError:
                break

    async def _send_silent_payload(
        self,
        display_text: DisplayText,
        actions: Optional[Actions],
        sequence_number: int,
    ) -> None:
        """Queue a silent audio payload"""
        audio_payload = prepare_audio_payload(
            audio_path=None,
            display_text=display_text,
            actions=actions,
            perf_trace=self._build_perf_trace(
                sequence_number=sequence_number,
                tts_text="",
                tts_synthesis_ms=0,
                payload_prepare_ms=0,
                silent=True,
            ),
        )
        await self._payload_queue.put((audio_payload, sequence_number))

    async def _process_tts(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        sequence_number: int,
    ) -> None:
        """Process TTS generation and queue the result for ordered delivery"""
        audio_file_path = None
        try:
            tts_started_at = time.perf_counter()
            if not self._tts_start_timeline_logged:
                self._tts_start_timeline_logged = True
                self.log_timeline("tts开始")
            audio_file_path = await self._generate_audio(tts_engine, tts_text)
            tts_synthesis_ms = (time.perf_counter() - tts_started_at) * 1000
            if not audio_file_path:
                raise RuntimeError("TTS engine returned no audio file")
            payload_started_at = time.perf_counter()
            payload = prepare_audio_payload(
                audio_path=audio_file_path,
                display_text=display_text,
                actions=actions,
                perf_trace=self._build_perf_trace(
                    sequence_number=sequence_number,
                    tts_text=tts_text,
                    tts_synthesis_ms=tts_synthesis_ms,
                    payload_prepare_ms=0,
                ),
            )
            payload["perf_trace"]["payload_prepare_ms"] = round(
                (time.perf_counter() - payload_started_at) * 1000, 1
            )
            payload["perf_trace"]["backend_total_to_audio_payload_ms"] = round(
                (time.perf_counter() - self._conversation_started_at) * 1000, 1
            )
            if not self._tts_timeline_logged:
                self._tts_timeline_logged = True
                logger.debug(
                    "[perf] "
                    f"request={payload['perf_trace'].get('request_id')} "
                    f"tts_ms={payload['perf_trace']['tts_synthesis_ms']}"
                )
                self.log_timeline(
                    f"tts完成: {payload['perf_trace']['tts_synthesis_ms']}ms"
                )
            # Queue the payload with its sequence number
            await self._payload_queue.put((payload, sequence_number))

        except Exception as e:
            logger.error(f"Error preparing audio payload: {e}")
            # Queue silent payload for error case
            payload = prepare_audio_payload(
                audio_path=None,
                display_text=display_text,
                actions=actions,
                perf_trace=self._build_perf_trace(
                    sequence_number=sequence_number,
                    tts_text=tts_text,
                    tts_synthesis_ms=0,
                    payload_prepare_ms=0,
                    silent=True,
                    error=str(e),
                ),
            )
            await self._payload_queue.put((payload, sequence_number))

        finally:
            if audio_file_path:
                tts_engine.remove_file(audio_file_path, verbose=False)

    async def _generate_audio(self, tts_engine: TTSInterface, text: str) -> str:
        """Generate audio file from text"""
        logger.debug(f"🏃Generating audio for '''{text}'''...")
        return await tts_engine.async_generate_audio(
            text=text,
            file_name_no_ext=f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}",
        )

    def _build_perf_trace(
        self,
        sequence_number: int,
        tts_text: str,
        tts_synthesis_ms: float,
        payload_prepare_ms: float,
        silent: bool = False,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        trace = dict(self._perf_trace)
        trace.pop("timeline_started_at", None)
        trace.pop("timeline_events", None)
        trace.update(
            {
                "sequence": sequence_number,
                "tts_text_length": len(tts_text or ""),
                "tts_synthesis_ms": round(tts_synthesis_ms, 1),
                "payload_prepare_ms": round(payload_prepare_ms, 1),
                "backend_total_to_audio_payload_ms": round(
                    (time.perf_counter() - self._conversation_started_at) * 1000, 1
                ),
                "silent": silent,
            }
        )
        if error:
            trace["error"] = error
        return trace

    def clear(self) -> None:
        """Clear all pending tasks and reset state"""
        self.task_list.clear()
        if self._sender_task:
            self._sender_task.cancel()
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        # Create a new queue to clear any pending items
        self._payload_queue = asyncio.Queue()
