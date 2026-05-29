"""Engine FastALPR — ONNX Runtime (CPU ou GPU)."""

from __future__ import annotations

import logging
import os
import threading

import numpy as np

from plates.engines.base import BaseLprEngine

logger = logging.getLogger(__name__)

_instance = None
_lock = threading.Lock()


class FastAlprEngine(BaseLprEngine):
    """
    Wrapper thread-safe do fast_alpr.ALPR.

    Configuração via env:
        ONNX_PROVIDERS  — ex: CUDAExecutionProvider,CPUExecutionProvider
        LPR_DETECTOR_MODEL — caminho do modelo YOLO (opcional)
        LPR_OCR_MODEL       — caminho do modelo OCR (opcional)
    """

    name = "fast_alpr"

    def __init__(self) -> None:
        self._alpr = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._load()

    def _load(self):
        if self._alpr is not None:
            return
        with self._lock:
            if self._alpr is not None:
                return
            from fast_alpr import ALPR

            providers_env = os.environ.get("ONNX_PROVIDERS", "")
            providers = [p.strip() for p in providers_env.split(",") if p.strip()] or None

            kwargs = {}
            if providers:
                kwargs["providers"] = providers

            detector_model = os.environ.get("LPR_DETECTOR_MODEL", "")
            ocr_model = os.environ.get("LPR_OCR_MODEL", "")
            if detector_model:
                kwargs["detector_model"] = detector_model
            if ocr_model:
                kwargs["ocr_model"] = ocr_model

            logger.info("[engine:fast_alpr] carregando modelos  providers=%s", providers or "default")
            self._alpr = ALPR(**kwargs)
            logger.info("[engine:fast_alpr] modelos prontos")

    def predict(self, frame: np.ndarray) -> list:
        self._load()
        return self._alpr.predict(frame)

    def stop(self) -> None:
        self._alpr = None

    def healthcheck(self) -> dict:
        providers_env = os.environ.get("ONNX_PROVIDERS", "CPUExecutionProvider")
        return {
            "status": "ok" if self._alpr else "not_loaded",
            "engine": self.name,
            "providers": providers_env,
            "model_loaded": self._alpr is not None,
        }


def get_fast_alpr_engine() -> FastAlprEngine:
    """Singleton thread-safe da FastAlprEngine."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = FastAlprEngine()
    return _instance
