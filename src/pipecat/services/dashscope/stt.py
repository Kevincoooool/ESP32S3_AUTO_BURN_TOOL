#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""DashScope FunASR Realtime speech-to-text service implementation.

Uses DashScope's WebSocket API for real-time streaming speech recognition
with the paraformer-realtime-v2 model.
"""

import asyncio
import json
import uuid
from typing import AsyncGenerator, List, Optional

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use DashScope STT, you need to `pip install websockets`.")
    raise Exception(f"Missing module: {e}")


class DashScopeSTTService(STTService):
    """DashScope FunASR Realtime speech-to-text service.

    Provides real-time speech recognition using DashScope's paraformer-realtime-v2
    model via WebSocket API. Supports streaming audio input with interim and final
    transcription results.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "paraformer-realtime-v2",
        base_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        sample_rate: Optional[int] = 16000,
        language_hints: Optional[List[str]] = None,
        **kwargs,
    ):
        """Initialize the DashScope FunASR STT service.

        Args:
            api_key: DashScope API key for authentication.
            model: ASR model to use. Defaults to "paraformer-realtime-v2".
            base_url: WebSocket API endpoint URL.
            sample_rate: Audio sample rate in Hz. Defaults to 16000.
            language_hints: Language hints for recognition (e.g. ["zh", "en"]).
            **kwargs: Additional arguments passed to the parent STTService.
        """
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._language_hints = language_hints or ["zh", "en"]

        self._websocket = None
        self._receive_task = None
        self._task_id = None

        self.set_model_name(model)

    async def start(self, frame: StartFrame):
        """Start the DashScope STT service.

        Args:
            frame: The start frame containing initialization parameters.
        """
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        """Stop the DashScope STT service.

        Args:
            frame: The end frame.
        """
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        """Cancel the DashScope STT service.

        Args:
            frame: The cancel frame.
        """
        await super().cancel(frame)
        await self._disconnect()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Send audio data to DashScope for transcription.

        Args:
            audio: Raw PCM audio bytes to transcribe.

        Yields:
            Frame: None (transcription results come via WebSocket callbacks).
        """
        if self._websocket and self._websocket.state is State.OPEN:
            try:
                await self._websocket.send(audio)
            except Exception as e:
                logger.error(f"{self} error sending audio: {e}")
                await self._reconnect()
        yield None

    async def _connect(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return

            self._task_id = uuid.uuid4().hex

            logger.debug(f"Connecting to DashScope FunASR: {self._base_url}")
            headers = {"Authorization": f"Bearer {self._api_key}"}
            self._websocket = await websocket_connect(self._base_url, additional_headers=headers)

            # Send run-task message
            run_task_msg = {
                "header": {
                    "action": "run-task",
                    "task_id": self._task_id,
                    "streaming": "duplex",
                },
                "payload": {
                    "task_group": "audio",
                    "task": "asr",
                    "function": "recognition",
                    "model": self._model,
                    "parameters": {
                        "format": "pcm",
                        "sample_rate": self.sample_rate,
                        "language_hints": self._language_hints,
                        "punctuation_prediction_enabled": True,
                        "inverse_text_normalization_enabled": True,
                    },
                    "input": {},
                },
            }
            await self._websocket.send(json.dumps(run_task_msg))

            # Wait for task-started event
            response = await asyncio.wait_for(self._websocket.recv(), timeout=10)
            msg = json.loads(response)
            event = msg.get("header", {}).get("event", "")
            if event == "task-started":
                logger.debug("DashScope FunASR task started")
                await self._call_event_handler("on_connected")
            elif event == "task-failed":
                error = msg.get("payload", {}).get("error", "Unknown error")
                logger.error(f"DashScope FunASR task failed: {error}")
                await self._call_event_handler("on_connection_error", f"{error}")
                await self._close_websocket()
                return

            # Start receive task
            if self._websocket and not self._receive_task:
                self._receive_task = self.create_task(
                    self._receive_task_handler(), name="dashscope_stt_receive"
                )

        except Exception as e:
            logger.error(f"Error connecting to DashScope FunASR: {e}")
            await self._call_event_handler("on_connection_error", f"{e}")
            await self._close_websocket()

    async def _disconnect(self):
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None

        if self._websocket and self._websocket.state is State.OPEN:
            try:
                # Send finish-task message
                finish_msg = {
                    "header": {
                        "action": "finish-task",
                        "task_id": self._task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {}},
                }
                await self._websocket.send(json.dumps(finish_msg))
                # Wait briefly for task-finished
                try:
                    await asyncio.wait_for(self._websocket.recv(), timeout=2)
                except (asyncio.TimeoutError, Exception):
                    pass
            except Exception as e:
                logger.warning(f"Error during DashScope FunASR disconnect: {e}")

        await self._close_websocket()
        await self._call_event_handler("on_disconnected")

    async def _close_websocket(self):
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

    async def _reconnect(self):
        logger.warning("Reconnecting to DashScope FunASR")
        await self._disconnect()
        await self._connect()

    async def _receive_task_handler(self):
        try:
            async for message in self._websocket:
                try:
                    if isinstance(message, str):
                        msg = json.loads(message)
                        event = msg.get("header", {}).get("event", "")

                        if event == "result-generated":
                            await self._handle_result(msg)
                        elif event == "task-finished":
                            logger.debug("DashScope FunASR task finished")
                            break
                        elif event == "task-failed":
                            error = msg.get("payload", {}).get("error", "Unknown")
                            logger.error(f"DashScope FunASR task failed: {error}")
                            break
                except Exception as e:
                    logger.error(f"Error processing DashScope FunASR message: {e}")
        except Exception as e:
            logger.warning(f"DashScope FunASR receive error: {e}")

    async def _handle_result(self, msg: dict):
        output = msg.get("payload", {}).get("output", {})
        sentence = output.get("sentence", {})
        text = sentence.get("text", "")
        is_sentence_end = sentence.get("sentence_end", False)

        if not text:
            return

        if is_sentence_end:
            await self.push_frame(
                TranscriptionFrame(
                    text=text,
                    user_id=self._user_id,
                    timestamp=time_now_iso8601(),
                )
            )
        else:
            await self.push_frame(
                InterimTranscriptionFrame(
                    text=text,
                    user_id=self._user_id,
                    timestamp=time_now_iso8601(),
                )
            )
