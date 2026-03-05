# Alibaba Cloud Voice Bot Example

Real-time Chinese voice conversation bot using Alibaba Cloud (DashScope) services with Pipecat.

## Services

| Component | Service | Model |
|-----------|---------|-------|
| STT | FunASR Realtime | paraformer-realtime-v2 |
| LLM | Qwen | qwen3.5-flash |
| TTS | CosyVoice | cosyvoice-v3-flash |

## Setup

1. Get a DashScope API key from [Alibaba Cloud Console](https://dashscope.console.aliyun.com/)

2. Configure `.env`:
```
DASHSCOPE_API_KEY=your_api_key_here
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Run

Start the bot server:
```bash
python bot.py
```

Connect with the test client (requires PyAudio):
```bash
pip install pyaudio
python test_client.py
```

The bot listens on `ws://0.0.0.0:8765`. Send PCM audio (16-bit, mono, 16kHz) as binary WebSocket frames.
