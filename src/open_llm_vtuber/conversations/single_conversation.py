from typing import Union, List, Dict, Any, Optional
import asyncio
import base64
import json
import time
from loguru import logger
import numpy as np
from fishaudio.types import FlushEvent, TextEvent

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext
from ..utils.tts_preprocessor import StreamingReasoningMarkupFilter

# Import necessary types from agent outputs
from ..agent.output_types import SentenceOutput, AudioOutput, DisplayText


FIRST_AUDIO_TIMEOUT_SECONDS = 8.0
NEXT_AUDIO_IDLE_TIMEOUT_SECONDS = 6.0


def _format_timeline_offset(started_at: float) -> str:
    elapsed = max(0.0, time.perf_counter() - started_at)
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    return f"{minutes}:{seconds:06.3f}"


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    perf_trace = dict((metadata or {}).get("perf_trace") or {})
    request_id = perf_trace.get("request_id") or f"{client_uid}-{time.time_ns()}"
    perf_trace["request_id"] = request_id
    perf_trace["input_kind"] = "voice" if isinstance(user_input, np.ndarray) else "text"
    perf_trace["backend_conversation_start_epoch_ms"] = round(time.time() * 1000, 1)
    timeline_started_at = time.perf_counter()
    perf_trace["timeline_started_at"] = timeline_started_at
    timeline_events: List[Dict[str, str]] = []
    perf_trace["timeline_events"] = timeline_events

    def log_timeline(message: str) -> None:
        timeline_events.append(
            {
                "offset": _format_timeline_offset(timeline_started_at),
                "message": message,
            }
        )

    async def try_process_llm_tts_stream(batch_input) -> Optional[str]:
        if not isinstance(user_input, np.ndarray):
            return None
        if not hasattr(context.agent_engine, "stream_raw_text"):
            return None
        if not hasattr(context.tts_engine, "stream_llm_audio"):
            return None

        stream_id = request_id
        token_queue: asyncio.Queue[Optional[Any]] = asyncio.Queue()
        response_chunks: List[str] = []
        first_llm_chunk_seen = False
        reasoning_filter = StreamingReasoningMarkupFilter()

        async def produce_llm_tokens() -> None:
            nonlocal first_llm_chunk_seen
            try:
                log_timeline("发送LLM")
                async for token in context.agent_engine.stream_raw_text(batch_input):
                    token = reasoning_filter.feed(token)
                    if token:
                        if not first_llm_chunk_seen:
                            first_llm_chunk_seen = True
                            log_timeline("接收到LLM回复")
                            logger.info(
                                f"[stream-tts] request={request_id} first LLM text received"
                            )
                        response_chunks.append(token)
                        await token_queue.put(token)
            finally:
                remaining_text = reasoning_filter.flush()
                if remaining_text:
                    if not first_llm_chunk_seen:
                        first_llm_chunk_seen = True
                        log_timeline("接收到LLM回复")
                        logger.info(
                            f"[stream-tts] request={request_id} first LLM text received"
                        )
                    response_chunks.append(remaining_text)
                    await token_queue.put(remaining_text)
                await token_queue.put(None)

        async def fish_text_stream():
            while True:
                token = await token_queue.get()
                if token is None:
                    break
                yield TextEvent(text=token)
            yield FlushEvent()
            logger.info(
                f"[stream-tts] request={request_id} final text flushed to Fish"
            )

        await websocket_send(
            json.dumps(
                {
                    "type": "audio-stream-start",
                    "stream_id": stream_id,
                    "format": "mp3",
                    "display_text": {
                        "text": "",
                        "name": context.character_config.character_name,
                        "avatar": context.character_config.avatar,
                    },
                }
            )
        )
        tts_manager.mark_playback_expected()
        log_timeline("fish websocket tts开始")
        logger.info(f"[stream-tts] request={request_id} Fish websocket tts started")

        producer_task = asyncio.create_task(produce_llm_tokens())
        first_audio_chunk_seen = False
        audio_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def consume_fish_audio() -> None:
            try:
                async for audio_chunk in context.tts_engine.stream_llm_audio(
                    fish_text_stream()
                ):
                    if audio_chunk:
                        await audio_queue.put(("chunk", audio_chunk))
            except Exception as exc:
                await audio_queue.put(("error", exc))
            finally:
                await audio_queue.put(("done", None))

        audio_task = asyncio.create_task(consume_fish_audio())
        stream_error: Optional[BaseException] = None
        try:
            while True:
                try:
                    event_type, payload = await asyncio.wait_for(
                        audio_queue.get(),
                        timeout=(
                            FIRST_AUDIO_TIMEOUT_SECONDS
                            if not first_audio_chunk_seen
                            else NEXT_AUDIO_IDLE_TIMEOUT_SECONDS
                        ),
                    )
                except asyncio.TimeoutError:
                    if not first_audio_chunk_seen:
                        raise TimeoutError(
                            "Fish stream produced no first audio chunk within "
                            f"{FIRST_AUDIO_TIMEOUT_SECONDS:g}s"
                        )
                    log_timeline("流式tts空闲超时, 结束当前流")
                    break

                if event_type == "done":
                    if not first_audio_chunk_seen:
                        raise RuntimeError("Fish stream finished before first audio chunk")
                    logger.info(f"[stream-tts] request={request_id} Fish audio stream done")
                    break
                if event_type == "error":
                    raise payload
                audio_chunk = payload
                if not first_audio_chunk_seen:
                    first_audio_chunk_seen = True
                    log_timeline("首个流式音频chunk已生成")
                    logger.info(
                        f"[stream-tts] request={request_id} first audio chunk received, bytes={len(audio_chunk)}"
                    )
                await websocket_send(
                    json.dumps(
                        {
                            "type": "audio-stream-chunk",
                            "stream_id": stream_id,
                            "format": "mp3",
                            "audio": base64.b64encode(audio_chunk).decode("ascii"),
                        }
                    )
                )
        except Exception as e:
            stream_error = e
            if not first_audio_chunk_seen:
                logger.warning(f"Fish LLM streaming TTS failed, falling back: {e}")
                log_timeline(f"流式tts失败, 回退旧TTS: {e}")
                producer_task.cancel()
                audio_task.cancel()
                await asyncio.gather(producer_task, audio_task, return_exceptions=True)
                tts_manager.clear_playback_expected()
                await websocket_send(
                    json.dumps({"type": "audio-stream-error", "stream_id": stream_id})
                )
                fallback_text = "".join(response_chunks)
                if fallback_text:
                    await tts_manager.speak(
                        tts_text=fallback_text,
                        display_text=DisplayText(
                            text=fallback_text,
                            name=context.character_config.character_name,
                            avatar=context.character_config.avatar,
                        ),
                        actions=None,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,
                    )
                    return fallback_text
                return None
            logger.warning(f"Fish LLM streaming TTS stopped after audio started: {e}")
            log_timeline(f"流式tts中断, 已结束当前流: {e}")
        finally:
            if not audio_task.done():
                audio_task.cancel()
                await asyncio.gather(audio_task, return_exceptions=True)

        try:
            await producer_task
        except asyncio.CancelledError:
            if stream_error is None:
                raise
        full_stream_response = "".join(response_chunks)
        if not full_stream_response.strip():
            logger.warning(
                f"[stream-tts] request={request_id} LLM stream returned no speakable text; falling back"
            )
            log_timeline("流式LLM结束: 未收到可播放文本, 回退旧TTS")
            tts_manager.clear_playback_expected()
            await websocket_send(
                json.dumps({"type": "audio-stream-error", "stream_id": stream_id})
            )
            return None

        await websocket_send(
            json.dumps(
                {
                    "type": "audio-stream-end",
                    "stream_id": stream_id,
                    "text": full_stream_response,
                    "display_text": {
                        "text": full_stream_response,
                        "name": context.character_config.character_name,
                        "avatar": context.character_config.avatar,
                    },
                }
            )
        )
        log_timeline("流式音频已发送完毕")
        logger.info(f"[stream-tts] request={request_id} audio-stream-end sent")
        return full_stream_response

    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager(perf_trace=perf_trace)
    full_response = ""  # Initialize full_response here

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send)
        logger.info(f"New Conversation Chain {session_emoji} started!")
        if isinstance(user_input, np.ndarray):
            log_timeline(f"收到用户语音: {len(user_input)} samples")
        else:
            log_timeline(f"收到用户文本: {user_input}")

        # Process user input
        input_started_at = time.perf_counter()
        input_text = await process_user_input(
            user_input, context.asr_engine, websocket_send
        )
        input_process_ms = (time.perf_counter() - input_started_at) * 1000
        if isinstance(user_input, np.ndarray):
            perf_trace["asr_ms"] = round(input_process_ms, 1)
            logger.debug(
                f"[perf] request={request_id} transcribe_ms={perf_trace['asr_ms']}"
            )
            log_timeline(f"transcribe完成, 用户文本: {input_text}")
        else:
            perf_trace["input_process_ms"] = round(input_process_ms, 1)

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        skip_history = metadata and metadata.get("skip_history", False)
        if context.history_uid and not skip_history:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="human",
                content=input_text,
                name=context.character_config.human_name,
            )

        if skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        streamed_response = await try_process_llm_tts_stream(batch_input)
        if streamed_response is not None:
            full_response = streamed_response
        else:
            llm_response_logged = False
            reasoning_filter = StreamingReasoningMarkupFilter()
            try:
                log_timeline("发送LLM")
                # agent.chat yields Union[SentenceOutput, Dict[str, Any]]
                agent_output_stream = context.agent_engine.chat(batch_input)

                async for output_item in agent_output_stream:
                    if (
                        isinstance(output_item, dict)
                        and output_item.get("type") == "tool_call_status"
                    ):
                        # Handle tool status event: send WebSocket message
                        output_item["name"] = context.character_config.character_name
                        logger.debug(f"Sending tool status update: {output_item}")

                        await websocket_send(json.dumps(output_item))

                    elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                        if isinstance(output_item, SentenceOutput):
                            clean_text = reasoning_filter.feed(
                                output_item.display_text.text
                            ).strip()
                            if not clean_text:
                                continue
                            output_item.display_text.text = clean_text
                            output_item.tts_text = clean_text

                        if not llm_response_logged:
                            log_timeline("接收到LLM回复")
                            llm_response_logged = True
                        # Handle SentenceOutput or AudioOutput
                        response_part = await process_agent_output(
                            output=output_item,
                            character_config=context.character_config,
                            live2d_model=context.live2d_model,
                            tts_engine=context.tts_engine,
                            websocket_send=websocket_send,  # Pass websocket_send for audio/tts messages
                            tts_manager=tts_manager,
                            translate_engine=context.translate_engine,
                        )
                        # Ensure response_part is treated as a string before concatenation
                        response_part_str = (
                            str(response_part) if response_part is not None else ""
                        )
                        full_response += response_part_str  # Accumulate text response
                    else:
                        logger.warning(
                            f"Received unexpected item type from agent chat stream: {type(output_item)}"
                        )
                        logger.debug(f"Unexpected item content: {output_item}")

            except Exception as e:
                logger.exception(
                    f"Error processing agent response stream: {e}"
                )  # Log with stack trace
                await websocket_send(
                    json.dumps(
                        {
                            "type": "error",
                            "message": f"Error processing agent response: {str(e)}",
                        }
                    )
                )
                # full_response will contain partial response before error
            # --- End processing agent response ---
            if not llm_response_logged:
                log_timeline("LLM回复结束: 未收到可播放内容")

        # Wait for any pending TTS tasks
        if tts_manager.task_list:
            await asyncio.gather(*tts_manager.task_list)
            await websocket_send(json.dumps({"type": "backend-synth-complete"}))

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if context.history_uid and full_response:  # Check full_response before storing
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            logger.info(f"AI response: {full_response}")

        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await websocket_send(
            json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"})
        )
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)
