#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""DashScope CosyVoice text-to-speech service implementation.

Uses DashScope's WebSocket API for streaming text-to-speech synthesis
with the CosyVoice model family.
"""

import asyncio
import json
import uuid
from typing import AsyncGenerator, Optional

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterruptionFrame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.tts_service import TTSService

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use DashScope TTS, you need to `pip install websockets`.")
    raise Exception(f"Missing module: {e}")


class DashScopeTTSService(TTSService):
    """DashScope CosyVoice text-to-speech service.

    Provides streaming text-to-speech synthesis using DashScope's CosyVoice
    models via WebSocket API. Supports bidirectional streaming for low-latency
    audio generation.
    """

    def __init__(
        self,
        *,
        api_key: str,
        voice: str = "longanyang",
        model: str = "cosyvoice-v3-flash",
        base_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        sample_rate: int = 22050,
        volume: int = 50,
        speech_rate: float = 1.0,
        pitch_rate: float = 1.0,
        **kwargs,
    ):
        """Initialize the DashScope CosyVoice TTS service.

        Args:
            api_key: DashScope API key for authentication.
            voice: Voice ID to use. Defaults to "longanyang".
            model: TTS model to use. Defaults to "cosyvoice-v3-flash".
            base_url: WebSocket API endpoint URL.
            sample_rate: Audio output sample rate in Hz. Defaults to 22050.
            volume: Volume level (0-100). Defaults to 50.
            speech_rate: Speech speed multiplier (0.5-2.0). Defaults to 1.0.
            pitch_rate: Pitch multiplier (0.5-2.0). Defaults to 1.0.
            **kwargs: Additional arguments passed to the parent TTSService.
        """
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._api_key = api_key
        self._voice = voice
        self._model = model
        self._base_url = base_url
        self._volume = volume
        self._speech_rate = speech_rate
        self._pitch_rate = pitch_rate

        self._websocket = None
        self._receive_task = None
        self._task_id = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._tts_done_event = asyncio.Event()

        self.set_model_name(model)

    def can_generate_metrics(self) -> bool:
        """Check if this service can generate processing metrics."""
        return True

    async def start(self, frame: StartFrame):
        """Start the DashScope TTS service.

        Args:
            frame: The start frame containing initialization parameters.
        """
        await super().start(frame)

    async def stop(self, frame: EndFrame):
        """Stop the DashScope TTS service.

        Args:
            frame: The end frame.
        """
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        """Cancel the DashScope TTS service.

        Args:
            frame: The cancel frame.
        """
        await super().cancel(frame)
        await self._disconnect()

    async def _connect(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return

            self._task_id = uuid.uuid4().hex

            logger.debug(f"Connecting to DashScope CosyVoice: {self._base_url}")
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
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "model": self._model,
                    "parameters": {
                        "voice": self._voice,
                        "format": "pcm",
                        "sample_rate": self.sample_rate,
                        "volume": self._volume,
                        "rate": self._speech_rate,
                        "pitch": self._pitch_rate,
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
                logger.debug("DashScope CosyVoice task started")
                await self._call_event_handler("on_connected")
            elif event == "task-failed":
                error = msg.get("payload", {}).get("error", "Unknown error")
                logger.error(f"DashScope CosyVoice task failed: {error}")
                await self._call_event_handler("on_connection_error", f"{error}")
                await self._close_websocket()
                return

            # Start receive task
            if self._websocket and not self._receive_task:
                self._receive_task = self.create_task(
                    self._receive_task_handler(), name="dashscope_tts_receive"
                )

        except Exception as e:
            logger.error(f"Error connecting to DashScope CosyVoice: {e}")
            await self._call_event_handler("on_connection_error", f"{e}")
            await self._close_websocket()

    async def _disconnect(self):
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None

        if self._websocket and self._websocket.state is State.OPEN:
            try:
                finish_msg = {
                    "header": {
                        "action": "finish-task",
                        "task_id": self._task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {}},
                }
                await self._websocket.send(json.dumps(finish_msg))
                try:
                    await asyncio.wait_for(self._websocket.recv(), timeout=2)
                except (asyncio.TimeoutError, Exception):
                    pass
            except Exception as e:
                logger.warning(f"Error during DashScope CosyVoice disconnect: {e}")

        await self._close_websocket()
        await self._call_event_handler("on_disconnected")

    async def _close_websocket(self):
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

    async def _receive_task_handler(self):
        try:
            async for message in self._websocket:
                try:
                    if isinstance(message, bytes):
                        # Binary frame = audio data
                        await self._audio_queue.put(message)
                    elif isinstance(message, str):
                        msg = json.loads(message)
                        event = msg.get("header", {}).get("event", "")
                        if event == "result-generated":
                            # Check if synthesis is complete for this chunk
                            pass
                        elif event == "task-finished":
                            logger.debug("DashScope CosyVoice task finished")
                            self._tts_done_event.set()
                            break
                        elif event == "task-failed":
                            error = msg.get("payload", {}).get("error", "Unknown")
                            logger.error(f"DashScope CosyVoice error: {error}")
                            self._tts_done_event.set()
                            break
                except Exception as e:
                    logger.error(f"Error processing DashScope CosyVoice message: {e}")
        except Exception as e:
            logger.warning(f"DashScope CosyVoice receive error: {e}")
        finally:
            self._tts_done_event.set()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Generate speech from text using DashScope CosyVoice.

        Args:
            text: The text to synthesize into speech.
            context_id: The context ID for tracking audio frames.

        Yields:
            Frame: Audio frames and control frames for the synthesized speech.
        """
        logger.debug(f"{self}: Generating CosyVoice TTS: [{text}]")

        try:
            # Ensure connection
            if not self._websocket or self._websocket.state is not State.OPEN:
                await self._connect()

            if not self._websocket or self._websocket.state is not State.OPEN:
                yield ErrorFrame(error="Failed to connect to DashScope CosyVoice")
                return

            await self.start_ttfb_metrics()
            await self.start_tts_usage_metrics(text)

            yield TTSStartedFrame(context_id=context_id)

            # Clear audio queue and done event
            while not self._audio_queue.empty():
                self._audio_queue.get_nowait()
            self._tts_done_event.clear()

            # Send text via continue-task
            continue_msg = {
                "header": {
                    "action": "continue-task",
                    "task_id": self._task_id,
                    "streaming": "duplex",
                },
                "payload": {"input": {"text": text}},
            }
            await self._websocket.send(json.dumps(continue_msg))

            # Send finish-task to signal end of text
            finish_msg = {
                "header": {
                    "action": "finish-task",
                    "task_id": self._task_id,
                    "streaming": "duplex",
                },
                "payload": {"input": {}},
            }
            await self._websocket.send(json.dumps(finish_msg))

            # Collect audio chunks until done
            ttfb_reported = False
            while True:
                try:
                    audio_data = await asyncio.wait_for(self._audio_queue.get(), timeout=15)
                    if audio_data and len(audio_data) > 0:
                        if not ttfb_reported:
                            await self.stop_ttfb_metrics()
                            ttfb_reported = True
                        yield TTSAudioRawFrame(
                            audio=audio_data,
                            sample_rate=self.sample_rate,
                            num_channels=1,
                        )
                except asyncio.TimeoutError:
                    logger.warning("DashScope CosyVoice audio timeout")
                    break

                if self._tts_done_event.is_set() and self._audio_queue.empty():
                    break

            yield TTSStoppedFrame(context_id=context_id)

            # Reconnect for next utterance (task is finished)
            await self._close_websocket()
            self._receive_task = None

        except Exception as e:
            logger.error(f"DashScope CosyVoice TTS error: {e}")
            yield ErrorFrame(error=f"DashScope CosyVoice error: {e}")
            yield TTSStoppedFrame(context_id=context_id)
            await self._close_websocket()
            self._receive_task = None
