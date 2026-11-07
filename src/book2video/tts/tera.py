"""TeraTTSv2 backend.

TeraTTSv2 is an ONNX model served through ``transformers`` remote code.  It
ships its own Russian accentuation, so raw text is passed to
``normalize_text`` first and the result is used unchanged.  Long inputs are
split into sentence-sized chunks; chunk audio is concatenated with a short
pause.  Tera always renders at natural speed; rate changes belong to
:mod:`book2video.speed`.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from ..gpu import nvidia_devices_visible

MODEL_ID = "TeraSpace/TeraTTSv2"
SAMPLE_RATE = 44_100
DEFAULT_PAUSE_SEC = 0.18

_PROVIDER_ALIASES = {
    "auto": None,
    "cpu": "CPUExecutionProvider",
    "cuda": "CUDAExecutionProvider",
}

_SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]*", re.UNICODE)


def available_providers() -> tuple[str, ...]:
    """Return the ONNX Runtime execution providers in this image."""
    import onnxruntime as ort

    return tuple(ort.get_available_providers())


def resolve_provider(requested: str = "auto", *, log=None) -> str:
    """Resolve ``auto``/``cpu``/``cuda`` to an ONNX execution provider.

    ``auto`` uses CUDA only when the NVIDIA devices are mounted and this
    onnxruntime build has the CUDA provider.  The loaded model is still allowed
    to fall back to CPU if session creation fails, which handles a missing
    driver library.  Explicit ``cuda`` never falls back silently.
    """
    key = (requested or "auto").lower()
    if key not in _PROVIDER_ALIASES:
        resolved = requested
        if resolved not in available_providers():
            raise ValueError(
                f"Unknown ONNX provider {requested!r}. Available: "
                f"{', '.join(available_providers())}"
            )
        return resolved

    resolved = _PROVIDER_ALIASES[key]
    if resolved is None:
        if not nvidia_devices_visible():
            if log:
                log("TTS provider: CPUExecutionProvider (no NVIDIA device)")
            return "CPUExecutionProvider"
        if "CUDAExecutionProvider" not in available_providers():
            if log:
                log("TTS provider: CPUExecutionProvider (no CUDA in onnxruntime)")
            return "CPUExecutionProvider"
        if log:
            log("TTS provider: CUDAExecutionProvider")
        return "CUDAExecutionProvider"

    if resolved not in available_providers():
        hint = (
            " This image has the CPU onnxruntime; build the GPU image."
            if resolved == "CUDAExecutionProvider"
            else ""
        )
        raise RuntimeError(
            f"ONNX provider {resolved} is not available. Available: "
            f"{', '.join(available_providers())}.{hint}"
        )
    if resolved == "CUDAExecutionProvider" and not nvidia_devices_visible():
        raise RuntimeError(
            "CUDA was requested, but no NVIDIA device is exposed to the "
            "container. Start it with --gpus all, or use --no-gpu."
        )
    if log:
        log(f"TTS provider: {resolved}")
    return resolved


def split_sentences(text: str, max_chars: int = 350) -> list[str]:
    """Split text into sentence-ish chunks no longer than ``max_chars``."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    sentences = [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            # Fall back to clause/word splitting for very long sentences.
            parts = re.split(r"(?<=[,;:])\s+", sentence)
            for part in parts:
                if len(current) + len(part) + 1 <= max_chars:
                    current = f"{current} {part}".strip()
                else:
                    if current:
                        chunks.append(current)
                    while len(part) > max_chars:
                        cut = part.rfind(" ", 0, max_chars)
                        cut = cut if cut > 0 else max_chars
                        chunks.append(part[:cut].strip())
                        part = part[cut:].strip()
                    current = part
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


class TeraBackend:
    def __init__(
        self,
        cache_dir: str | Path | None = None,
        provider: str = "auto",
        threads: int | None = None,
        model_id: str = MODEL_ID,
        log=None,
    ) -> None:
        self.model_id = model_id
        self._auto_provider = (provider or "auto").lower() == "auto"
        self._log = log or (lambda *_: None)
        self.provider = resolve_provider(provider, log=self._log)
        self.threads = threads or min(16, os.cpu_count() or 8)
        default_cache = Path(os.environ.get("BOOK2VIDEO_CACHE", "~/.cache/book2video"))
        self.cache_dir = Path(cache_dir or default_cache).expanduser() / "tts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = self._load_model(self.provider)
        return self._model

    def _load_model(self, provider: str):
        if provider == "CUDAExecutionProvider":
            try:
                self._prepare_cuda()
            except Exception as exc:
                if not self._auto_provider:
                    raise RuntimeError(
                        f"CUDA is exposed, but onnxruntime could not load its "
                        f"libraries: {exc}"
                    ) from exc
                self._log(f"GPU: CUDA setup failed ({exc}); falling back to CPU")
                self.provider = "CPUExecutionProvider"
                return self._load_model(self.provider)

        from transformers import AutoModel

        try:
            return AutoModel.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                provider=provider,
                threads=self.threads,
                ruaccent_device="CUDA" if provider == "CUDAExecutionProvider" else "CPU",
            )
        except Exception as exc:
            if not self._auto_provider or provider != "CUDAExecutionProvider":
                raise
            self._log(f"GPU: CUDA model load failed ({exc}); falling back to CPU")
            self.provider = "CPUExecutionProvider"
            return self._load_model(self.provider)

    @staticmethod
    def _prepare_cuda() -> None:
        import onnxruntime as ort

        preload = getattr(ort, "preload_dlls", None)
        if preload is not None:
            preload()

    def mark_text(self, text: str) -> str:
        """Return Tera's own stress markup, unchanged.

        The input must be *raw* text (no ``+``): Tera skips its accentizer for
        any span that already contains a manual mark.  We do not correct the
        result: model mistakes are accepted as-is.
        """
        wrapped = text if text.lstrip().startswith("<ru>") else f"<ru>{text}</ru>"
        return self.model.normalize_text(wrapped)

    def _cache_path(self, marked_text: str, voice: str) -> Path:
        key = hashlib.sha256(
            f"{self.model_id}\0{voice}\0{marked_text}".encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{key}.wav"

    def _synthesize_chunk(self, marked_text: str, voice: str) -> np.ndarray:
        cache_path = self._cache_path(marked_text, voice)
        if cache_path.exists():
            audio, _ = sf.read(cache_path, dtype="float32")
            return np.asarray(audio, dtype=np.float32).reshape(-1)

        audio = self.model.generate_speech(marked_text, voice=voice)
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        sf.write(cache_path, audio, SAMPLE_RATE, subtype="PCM_16")
        return audio

    def synthesize(
        self,
        text: str,
        voice: str,
        out_path: str | Path | None = None,
    ) -> Path:
        """Synthesize ``text`` and return the path to a mono 44.1 kHz WAV."""
        chunks = split_sentences(text)
        if not chunks:
            raise ValueError("Nothing to synthesize: text is empty")

        pieces: list[np.ndarray] = []
        pause = np.zeros(int(SAMPLE_RATE * DEFAULT_PAUSE_SEC), dtype=np.float32)
        for index, chunk in enumerate(chunks):
            marked = self.mark_text(chunk)
            audio = self._synthesize_chunk(marked, voice)
            if index:
                pieces.append(pause)
            pieces.append(audio)

        result = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
        out_path = Path(out_path) if out_path is not None else (
            self.cache_dir / "last.wav"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(out_path, result, SAMPLE_RATE, subtype="PCM_16")
        return out_path
