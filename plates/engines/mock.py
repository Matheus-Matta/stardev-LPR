"""Engine Mock — retorna placas simuladas sem IA real.

Uso exclusivo em DEV para testar fluxo de eventos, alertas e UI
sem precisar de câmera ou modelo real.

Configuração via env:
    MOCK_DEFAULT_PLATE  — placa padrão (padrão: ABC1D23)
    MOCK_CONFIDENCE     — confiança padrão (padrão: 0.95)
    MOCK_SOURCE         — "fixed" | "sidecar_json" (padrão: fixed)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from plates.engines.base import BaseLprEngine

logger = logging.getLogger(__name__)


@dataclass
class _MockBbox:
    x1: int = 0
    y1: int = 0
    x2: int = 100
    y2: int = 50

    def __getitem__(self, idx):
        return (self.x1, self.y1, self.x2, self.y2)[idx]

    def __len__(self):
        return 4


@dataclass
class _MockDetection:
    bounding_box: _MockBbox = field(default_factory=_MockBbox)


@dataclass
class _MockOcr:
    text: str = "ABC1D23"
    confidence: float = 0.95


@dataclass
class _MockResult:
    ocr: _MockOcr = field(default_factory=_MockOcr)
    detection: _MockDetection = field(default_factory=_MockDetection)


class MockLprEngine(BaseLprEngine):
    name = "mock"

    def __init__(self) -> None:
        self._plate = os.environ.get("MOCK_DEFAULT_PLATE", "ABC1D23").upper()
        self._confidence = float(os.environ.get("MOCK_CONFIDENCE", "0.95"))
        logger.warning(
            "[engine:mock] ATIVO — retornando placa simulada '%s' com conf=%.2f. "
            "Nunca use em produção.",
            self._plate, self._confidence,
        )

    def start(self) -> None:
        logger.warning("[engine:mock] iniciado — modo SIMULADO")

    def predict(self, frame: np.ndarray) -> list:
        return [_MockResult(
            ocr=_MockOcr(text=self._plate, confidence=self._confidence),
            detection=_MockDetection(
                bounding_box=_MockBbox(0, 0, frame.shape[1] // 4, frame.shape[0] // 6)
            ),
        )]

    def healthcheck(self) -> dict:
        return {
            "status": "mock",
            "engine": self.name,
            "plate": self._plate,
            "confidence": self._confidence,
            "warning": "mock engine ativo — não usar em produção",
        }
