"""
Management command: run_analytics_lpr

Inicia o worker de analytics LPR independente do MediaMTX.

Ao separar este processo do run_media_server:
  - Reiniciar o analytics não derruba o live stream
  - MediaMTX fica leve e focado em mídia
  - Analytics pode escalar horizontalmente

Uso:
    python manage.py run_analytics_lpr
    python manage.py run_analytics_lpr --plate-log placas.log
    python manage.py run_analytics_lpr --workers 10

Variáveis de ambiente:
    LPR_ENGINE          engine de leitura (fast_alpr | mock | deepstream)
    CAPTURE_ANALYZE_PCT % de frames analisados (padrão: 0.10)
    CAPTURE_WORKERS     workers paralelos de captura  (padrão: 50)
"""

import logging
import os
import queue
import signal
import sys
import threading
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


class Command(BaseCommand):
    help = "Inicia o worker de analytics LPR independente do media server"

    def add_arguments(self, parser):
        parser.add_argument(
            "--plate-log",
            metavar="ARQUIVO",
            default="",
            help="Salva detecções em arquivo de log (ex: placas.log)",
        )

    def handle(self, *args, **options):
        engine  = _env("LPR_ENGINE",  "fast_alpr")
        app_env = _env("APP_ENV",     "dev")
        device  = _env("LPR_DEVICE",  "cpu")
        pct     = _env("CAPTURE_ANALYZE_PCT", "0.10")

        self.stdout.write(self.style.HTTP_INFO("=" * 56))
        self.stdout.write(self.style.HTTP_INFO("  Analytics LPR Worker"))
        self.stdout.write(f"  Engine   : {engine}  [{app_env.upper()}]")
        self.stdout.write(f"  Device   : {device}")
        self.stdout.write(f"  Analise  : {pct} dos frames")
        self.stdout.write(f"  Workers  : 1 por câmera ativa (auto)")
        self.stdout.write(self.style.HTTP_INFO("=" * 56))

        if options["plate_log"]:
            self._enable_plate_log(options["plate_log"])
            self.stdout.write(self.style.SUCCESS(
                f"[capture] plate-log → {options['plate_log']}"
            ))

        from common.management.commands.run_media_server import CaptureLoopThread

        capture = CaptureLoopThread(interval=0.0, workers=0)
        capture.start()
        self.stdout.write(self.style.SUCCESS(
            "[analytics] workers iniciados — 1 por câmera ativa, detecta novas a cada 5s"
        ))

        def _shutdown(signum, frame):
            self.stdout.write("\n[analytics] Encerrando workers...")
            capture.stop()
            capture.join()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            _shutdown(None, None)

    def _enable_plate_log(self, path: str) -> None:
        import logging as _logging
        fh = _logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(_logging.DEBUG)
        fh.setFormatter(_logging.Formatter("%(message)s"))
        det = _logging.getLogger("lpr.detections")
        det.addHandler(fh)
        det.setLevel(_logging.DEBUG)
