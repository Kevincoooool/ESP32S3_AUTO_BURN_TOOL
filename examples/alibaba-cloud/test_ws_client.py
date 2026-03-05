#!/usr/bin/env python3
"""Headless WebSocket test client (no audio devices required).

Connects to the bot, waits for the greeting audio response,
and prints received data statistics.

Usage:
    python test_ws_client.py
"""

import asyncio

from websockets.asyncio.client import connect as websocket_connect

SERVER_URL = "ws://localhost:8765"


async def main():
    print(f"Connecting to {SERVER_URL}...")

    async with websocket_connect(SERVER_URL) as ws:
        print("Connected! Waiting for bot greeting response...")

        audio_bytes_received = 0
        text_messages = []

        try:
            while True:
                message = await asyncio.wait_for(ws.recv(), timeout=30)
                if isinstance(message, bytes):
                    audio_bytes_received += len(message)
                    if audio_bytes_received % 10000 < len(message):
                        print(f"  Audio received: {audio_bytes_received} bytes")
                elif isinstance(message, str):
                    text_messages.append(message)
                    print(f"  Text message: {message[:200]}")
        except asyncio.TimeoutError:
            print("\nTimeout - no more data received.")
        except Exception as e:
            print(f"\nConnection ended: {e}")

        print(f"\nSummary:")
        print(f"  Audio bytes received: {audio_bytes_received}")
        print(f"  Text messages: {len(text_messages)}")

        if audio_bytes_received > 0:
            duration_s = audio_bytes_received / (22050 * 2)  # 16-bit mono 22050Hz
            print(f"  Estimated audio duration: {duration_s:.1f}s")
            print("  SUCCESS: Bot generated audio response!")
        else:
            print("  No audio received from bot.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")
