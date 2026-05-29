"""Factory de engine LPR — seleciona engine via LPR_ENGINE no .env."""

from __future__ import annotations

import logging
import os

from plates.engines.base import BaseLprEngine

logger = logging.getLogger(__name__)

_engine: BaseLprEngine | None = None


def get_lpr_engine() -> BaseLprEngine:
    """
    Retorna a engine LPR configurada via LPR_ENGINE (singleton).

    Valores aceitos:
        mock        — simulado, apenas DEV
        fast_alpr   — ONNX Runtime CPU/GPU (padrão)
        deepstream  — NVIDIA DeepStream (stub, Sprint 5)

    Regras de segurança:
        - APP_ENV=prod + LPR_ENGINE=mock   → RuntimeError
        - APP_ENV=prod + OCR stub ativo    → RuntimeError
        - LPR_ENGINE=deepstream            → NotImplementedError (Sprint 5)
    """
    global _engine
    if _engine is not None:
        return _engine

    engine_name = os.environ.get("LPR_ENGINE", "fast_alpr").strip().lower()
    app_env     = os.environ.get("APP_ENV", "dev").strip().lower()
    ocr_version = os.environ.get("OCR_ENGINE_VERSION", "").lower()

    # ── Guardrails de produção ────────────────────────────────────────────────
    if app_env == "prod":
        if engine_name == "mock":
            raise RuntimeError(
                "[CRITICAL] LPR_ENGINE=mock não é permitido em APP_ENV=prod. "
                "Use fast_alpr ou deepstream."
            )
        if "stub" in ocr_version:
            raise RuntimeError(
                f"[CRITICAL] OCR_ENGINE_VERSION={ocr_version!r} contém 'stub' "
                "e não é permitido em APP_ENV=prod."
            )

    # ── Seleção de engine ────────────────────────────────────────────────────
    if engine_name == "mock":
        from plates.engines.mock import MockLprEngine
        _engine = MockLprEngine()

    elif engine_name == "fast_alpr":
        from plates.engines.fast_alpr_engine import get_fast_alpr_engine
        _engine = get_fast_alpr_engine()

    elif engine_name == "deepstream":
        from plates.engines.deepstream import DeepStreamLprEngine
        _engine = DeepStreamLprEngine()

    else:
        raise RuntimeError(
            f"LPR_ENGINE={engine_name!r} inválida. "
            "Valores aceitos: mock | fast_alpr | deepstream"
        )

    logger.info(
        "[lpr-factory] engine=%s  app_env=%s  ocr=%s",
        engine_name, app_env, ocr_version or "—",
    )
    _engine.start()
    return _engine


def reset_engine() -> None:
    """Reseta o singleton (útil em testes)."""
    global _engine
    if _engine:
        try:
            _engine.stop()
        except Exception:
            pass
    _engine = None
