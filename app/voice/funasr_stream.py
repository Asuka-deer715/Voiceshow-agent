"""Local, chunked FunASR inference for browser microphone streams."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MODELSCOPE_CACHE", str(ROOT / "models" / "modelscope"))

MODEL_PATH = Path(
    os.getenv(
        "VOICE_ASR_MODEL_PATH",
        ROOT
        / "models"
        / "modelscope"
        / "models"
        / "iic--speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
        / "snapshots"
        / "master",
    )
).expanduser()
SAMPLE_RATE = 16_000
CHUNK_SIZE = [0, 8, 4]
CHUNK_SAMPLES = CHUNK_SIZE[1] * 960
FINAL_SILENCE_SAMPLES = SAMPLE_RATE * 3 // 10

_model = None
_model_lock = threading.Lock()
_inference_lock = threading.Lock()


def _load_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                import torch
                from funasr import AutoModel

                if not MODEL_PATH.is_dir():
                    raise FileNotFoundError(f"FunASR model directory not found: {MODEL_PATH}")
                configured_device = os.getenv("VOICE_ASR_DEVICE", "auto")
                device = "cuda" if configured_device == "auto" and torch.cuda.is_available() else configured_device
                if device == "auto":
                    device = "cpu"
                if device == "cuda" and not torch.cuda.is_available():
                    raise RuntimeError("VOICE_ASR_DEVICE=cuda, but CUDA is unavailable")
                _model = AutoModel(
                    model=str(MODEL_PATH),
                    device=device,
                    disable_update=True,
                    disable_pbar=True,
                )
    return _model


class FunASRStream:
    """Maintain independent decoder state for one browser utterance."""

    def __init__(self, model=None):
        self._model = model or _load_model()
        self._cache: dict = {}
        self._audio = np.empty(0, dtype=np.float32)
        self._transcript = ""

    def push(self, pcm_bytes: bytes) -> str | None:
        if len(pcm_bytes) % 2:
            raise ValueError("PCM audio must contain 16-bit samples")
        samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768.0
        if samples.size == 0:
            return None
        self._audio = np.concatenate((self._audio, samples))
        changed = False
        while self._audio.size >= CHUNK_SAMPLES:
            chunk, self._audio = self._audio[:CHUNK_SAMPLES], self._audio[CHUNK_SAMPLES:]
            changed = bool(self._decode(chunk, is_final=False)) or changed
        return self._transcript if changed else None

    def finish(self) -> str:
        final_audio = np.concatenate((self._audio, np.zeros(FINAL_SILENCE_SAMPLES, dtype=np.float32)))
        if final_audio.size < CHUNK_SAMPLES:
            padded = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
            padded[: final_audio.size] = final_audio
            final_audio = padded
        self._decode(final_audio, is_final=True)
        self._audio = np.empty(0, dtype=np.float32)
        return self._transcript

    def _decode(self, audio: np.ndarray, is_final: bool) -> str:
        with _inference_lock:
            result = self._model.generate(
                input=audio,
                cache=self._cache,
                is_final=is_final,
                chunk_size=CHUNK_SIZE,
                encoder_chunk_look_back=4,
                decoder_chunk_look_back=1,
                disable_pbar=True,
            )
        output = result[0] if isinstance(result, list) else result
        text = str(output.get("text", "")) if isinstance(output, dict) else ""
        self._transcript += text
        return text
