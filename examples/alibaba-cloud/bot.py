#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Alibaba Cloud voice bot example using DashScope services.

Uses FunASR Realtime (STT) + Qwen 3.5 Flash (LLM) + CosyVoice v3 Flash (TTS)
over WebSocket transport.

Usage:
    python bot.py

    Then connect a WebSocket client to ws://localhost:8765 and send PCM audio
    (16-bit signed little-endian, mono, 16000 Hz).
"""

import os

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    LLMRunFrame,
    OutputAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.dashscope.stt import DashScopeSTTService
from pipecat.services.dashscope.tts import DashScopeTTSService
from pipecat.services.qwen.llm import QwenLLMService
from pipecat.transports.websocket.server import (
    WebsocketServerParams,
    WebsocketServerTransport,
)

load_dotenv(override=True)


class RawPCMSerializer(FrameSerializer):
    """Simple serializer that sends/receives raw PCM audio as binary frames."""

    def __init__(self, sample_rate_in: int = 16000, sample_rate_out: int = 22050):
        super().__init__()
        self._sample_rate_in = sample_rate_in
        self._sample_rate_out = sample_rate_out

    async def serialize(self, frame: Frame) -> str | bytes | None:
        """Serialize audio frames to raw PCM bytes."""
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """Deserialize raw PCM bytes to audio frames."""
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio=data,
                sample_rate=self._sample_rate_in,
                num_channels=1,
            )
        return None


async def main():
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        logger.error("DASHSCOPE_API_KEY not set")
        return

    transport = WebsocketServerTransport(
        params=WebsocketServerParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=22050,
            add_wav_header=False,
            serializer=RawPCMSerializer(
                sample_rate_in=16000,
                sample_rate_out=22050,
            ),
        ),
        host="0.0.0.0",
        port=8765,
    )

    stt = DashScopeSTTService(
        api_key=api_key,
        model="paraformer-realtime-v2",
        sample_rate=16000,
        language_hints=["zh", "en"],
    )

    llm = QwenLLMService(
        api_key=api_key,
        model="qwen3.5-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    tts = DashScopeTTSService(
        api_key=api_key,
        model="cosyvoice-v3-flash",
        voice="longanyang",
        sample_rate=22050,
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个友好的AI语音助手。请用简洁自然的中文回答用户的问题。"
                "你的回答会被语音合成朗读出来，所以请避免使用特殊字符、"
                "表情符号或markdown格式。保持回答简短精炼。"
            ),
        },
    ]

    context = LLMContext(messages)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=22050,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        messages.append({"role": "system", "content": "请用中文向用户问好，做一个简短的自我介绍。"})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner()
    logger.info("Starting Alibaba Cloud voice bot on ws://0.0.0.0:8765")
    await runner.run(task)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
