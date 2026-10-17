"""Loopback WebSocket endpoint for streaming browser PCM to local FunASR."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading

from websockets.asyncio.server import serve

logger = logging.getLogger(__name__)


async def _send(socket, kind: str, **payload) -> None:
    await socket.send(json.dumps({"type": kind, **payload}, ensure_ascii=False))


async def _handle_connection(socket) -> None:
    stream = None
    try:
        async for message in socket:
            if isinstance(message, bytes):
                if stream is None:
                    await _send(socket, "error", message="语音连接尚未准备好，请重新开始录音")
                    continue
                transcript = await asyncio.to_thread(stream.push, message)
                if transcript is not None:
                    await _send(socket, "partial", text=transcript)
                continue

            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                await _send(socket, "error", message="无法识别语音控制消息")
                continue

            if event.get("type") == "start":
                await _send(socket, "status", stage="loading_model", message="正在加载本地语音模型…")
                try:
                    from .voice.funasr_stream import FunASRStream

                    stream = await asyncio.to_thread(FunASRStream)
                except Exception as exc:
                    logger.exception("Could not initialize local FunASR")
                    await _send(
                        socket,
                        "error",
                        message=f"本地语音模型启动失败（{type(exc).__name__}），详细原因已记入服务日志",
                    )
                    await socket.close(code=1011, reason="ASR initialization failed")
                    return
                await _send(socket, "ready")
            elif event.get("type") == "speech_end":
                if stream is None:
                    await _send(socket, "error", message="语音连接尚未准备好，请重新开始录音")
                    continue
                transcript = await asyncio.to_thread(stream.finish)
                await _send(socket, "final", text=transcript)
                await socket.close(code=1000, reason="transcription complete")
                return
    except Exception:
        logger.exception("Local ASR WebSocket session failed")


async def _serve_forever(host: str, port: int) -> None:
    app_port = os.getenv("PORT", "7860")
    origins = {f"http://127.0.0.1:{app_port}", f"http://localhost:{app_port}"}
    async with serve(_handle_connection, host, port, origins=origins, max_size=1_048_576):
        print(f"VoiceShop local ASR WebSocket listening at ws://{host}:{port}")
        await asyncio.Event().wait()


def _serve_in_thread() -> None:
    host = os.getenv("VOICE_WS_HOST", "127.0.0.1")
    port = int(os.getenv("VOICE_WS_PORT", "8765"))
    try:
        asyncio.run(_serve_forever(host, port))
    except OSError:
        logger.exception("Could not start local ASR WebSocket server on %s:%s", host, port)


def start_voice_server() -> threading.Thread:
    thread = threading.Thread(target=_serve_in_thread, name="voiceshop-asr-ws", daemon=True)
    thread.start()
    return thread
