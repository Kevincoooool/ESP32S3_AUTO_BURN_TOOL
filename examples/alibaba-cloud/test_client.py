#!/usr/bin/env python3
"""Simple WebSocket test client for the Alibaba Cloud voice bot.

Records audio from the microphone, sends it to the bot via WebSocket,
and plays back the bot's audio response.

Requirements:
    pip install websockets pyaudio

Usage:
    1. Start the bot: python bot.py
    2. Run this client: python test_client.py
    3. Speak into your microphone
    4. Press Ctrl+C to stop
"""

import asyncio
import sys

try:
    import pyaudio
except ImportError:
    print("PyAudio not found. Install with: pip install pyaudio")
    sys.exit(1)

try:
    from websockets.asyncio.client import connect as websocket_connect
except ImportError:
    print("websockets not found. Install with: pip install websockets")
    sys.exit(1)

# Audio configuration
INPUT_SAMPLE_RATE = 16000
INPUT_CHANNELS = 1
INPUT_FORMAT = pyaudio.paInt16
INPUT_CHUNK_SIZE = 3200  # 100ms at 16kHz, 16-bit mono

OUTPUT_SAMPLE_RATE = 22050
OUTPUT_CHANNELS = 1
OUTPUT_FORMAT = pyaudio.paInt16

SERVER_URL = "ws://localhost:8765"


async def main():
    pa = pyaudio.PyAudio()

    # Open input stream (microphone)
    input_stream = pa.open(
        format=INPUT_FORMAT,
        channels=INPUT_CHANNELS,
        rate=INPUT_SAMPLE_RATE,
        input=True,
        frames_per_buffer=INPUT_CHUNK_SIZE // 2,  # frames = bytes / 2 for 16-bit
    )

    # Open output stream (speaker)
    output_stream = pa.open(
        format=OUTPUT_FORMAT,
        channels=OUTPUT_CHANNELS,
        rate=OUTPUT_SAMPLE_RATE,
        output=True,
        frames_per_buffer=1024,
    )

    print(f"Connecting to {SERVER_URL}...")

    async with websocket_connect(SERVER_URL) as ws:
        print("Connected! Speak into your microphone. Press Ctrl+C to stop.")

        async def send_audio():
            """Read from microphone and send to server."""
            try:
                while True:
                    audio_data = input_stream.read(
                        INPUT_CHUNK_SIZE // 2, exception_on_overflow=False
                    )
                    await ws.send(audio_data)
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                pass

        async def receive_audio():
            """Receive from server and play through speaker."""
            try:
                async for message in ws:
                    if isinstance(message, bytes):
                        output_stream.write(message)
                    elif isinstance(message, str):
                        # JSON control messages
                        print(f"  Server: {message}")
            except asyncio.CancelledError:
                pass

        try:
            await asyncio.gather(send_audio(), receive_audio())
        except KeyboardInterrupt:
            print("\nDisconnecting...")

    input_stream.stop_stream()
    input_stream.close()
    output_stream.stop_stream()
    output_stream.close()
    pa.terminate()
    print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")
