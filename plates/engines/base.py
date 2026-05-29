"""Interface comum para todas as engines LPR."""

from __future__ import annotations

import numpy as np


class BaseLprEngine:
    """
    Contrato que todas as engines LPR devem implementar.

    process_frame(frame) deve retornar lista de dicts:
    [
        {
            "plate":      str,
            "confidence": float,   # 0.0 – 1.0
            "bbox":       tuple,   # (x1, y1, x2, y2) pixels
            "engine":     str,
        }
    ]
    """

    name: str = "base"

    def start(self) -> None:
        """Inicializa a engine (carrega modelos, abre recursos)."""

    def stop(self) -> None:
        """Libera recursos."""

    def predict(self, frame: np.ndarray) -> list:
        """
        Roda detecção + OCR em um frame.
        Retorna objetos compatíveis com fast_alpr (`.ocr.text`, `.ocr.confidence`,
        `.detection.bounding_box`) OU lista de dicts padronizados.
        """
        raise NotImplementedError

    def healthcheck(self) -> dict:
        return {"status": "ok", "engine": self.name}
