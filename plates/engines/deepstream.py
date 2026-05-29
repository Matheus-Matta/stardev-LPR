"""Engine NVIDIA DeepStream — pipeline GPU profissional para alta escala.

Status: STUB — implementação completa no Sprint 5.

Requer:
    - Host com GPU NVIDIA
    - NVIDIA DeepStream SDK instalado
    - Docker runtime nvidia
    - Container baseado em nvcr.io/nvidia/deepstream

Referências:
    https://docs.nvidia.com/metropolis/deepstream/dev-guide/
    https://github.com/NVIDIA-AI-IOT/deepstream_lpr_app
"""

from __future__ import annotations

import logging

import numpy as np

from plates.engines.base import BaseLprEngine

logger = logging.getLogger(__name__)


class DeepStreamLprEngine(BaseLprEngine):
    """
    Placeholder para integração com NVIDIA DeepStream.

    Quando implementado, consumirá RTSP diretamente do MediaMTX via pipeline
    GStreamer/DeepStream, processando batches de câmeras em GPU.
    """

    name = "deepstream"

    def start(self) -> None:
        raise NotImplementedError(
            "DeepStreamLprEngine não implementado — Sprint 5. "
            "Use LPR_ENGINE=fast_alpr enquanto aguarda."
        )

    def predict(self, frame: np.ndarray) -> list:
        raise NotImplementedError("DeepStream não suporta predict() por frame avulso.")

    def healthcheck(self) -> dict:
        return {"status": "not_implemented", "engine": self.name}
