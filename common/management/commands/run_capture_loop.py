"""
Management command: run_capture_loop

Loop contínuo que despacha tarefas Celery de captura de frame para todas as
câmeras ativas que usam o MediaMTX (DIRECT_RTSP, RTMP_PUSH, GATEWAY).

Cada disparo chama cameras.tasks.capture_camera_frame, que:
  1. Lê um frame do stream RTSP via ffmpeg (rtsp://mediamtx:8554/live/<camera_key>)
  2. Cria um PlateEvent com a imagem
  3. Enfileira process_plate_event → OCR → AccessEvent → alertas → webhooks

Uso:
    python manage.py run_capture_loop
    python manage.py run_capture_loop --interval 1     # 1 captura/segundo por câmera
    python manage.py run_capture_loop --once           # uma rodada e encerra (debug)
    python manage.py run_capture_loop --camera-key abc # só uma câmera específica
    python manage.py run_capture_loop --plate-log placas.log  # salva detecções em arquivo

Variáveis de ambiente:
    CAPTURE_INTERVAL_SECONDS   segundos entre ciclos   (padrão: 2)
"""

import logging
import os
import signal
import sys
import time

from django.core.management.base import BaseCommand

from cameras.models import Camera
from cameras.tasks import capture_camera_frame

logger = logging.getLogger(__name__)

PLATE_DETECTION_LOGGER = "lpr.detections"


def _enable_plate_log(path: str) -> None:
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(message)s"))
    det = logging.getLogger(PLATE_DETECTION_LOGGER)
    det.addHandler(fh)
    det.setLevel(logging.DEBUG)
    det.propagate = True  # também aparece no terminal


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class Command(BaseCommand):
    help = "Loop de captura de frames das câmeras via MediaMTX → Celery → OCR"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=_env_int("CAPTURE_INTERVAL_SECONDS", 2),
            help="Segundos entre cada ciclo de captura (padrão: 2)",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Captura uma vez e encerra (útil para debug)",
        )
        parser.add_argument(
            "--camera-key",
            default="",
            help="Limita a captura a uma câmera específica pelo camera_key",
        )
        parser.add_argument(
            "--plate-log",
            metavar="ARQUIVO",
            default="",
            help="Salva detecções de placa em arquivo .log (ex: --plate-log placas.log)",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        once = options["once"]
        camera_key_filter = options["camera_key"]

        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        if options["plate_log"]:
            _enable_plate_log(options["plate_log"])
            self.stdout.write(self.style.SUCCESS(
                f"[plate-log] salvando detecções em: {options['plate_log']}"
            ))

        self.stdout.write(
            self.style.HTTP_INFO(
                f"Capture loop iniciado  intervalo={interval}s"
                + (f"  câmera={camera_key_filter}" if camera_key_filter else "")
            )
        )

        while self._running:
            qs = (
                Camera.objects
                .filter(is_active=True)
                .exclude(connection_mode=Camera.ConnectionMode.PUSH)
            )
            if camera_key_filter:
                qs = qs.filter(camera_key=camera_key_filter)

            camera_ids = list(qs.values_list("id", flat=True))

            if not camera_ids:
                self.stdout.write("Nenhuma câmera ativa encontrada. Aguardando...")
            else:
                self.stdout.write(
                    f"Despachando captura para {len(camera_ids)} câmera(s)"
                )
                for cam_id in camera_ids:
                    logger.debug("[capture] dispatching camera_id=%s", cam_id)
                    try:
                        capture_camera_frame.delay(cam_id)
                    except Exception as exc:
                        logger.warning("[capture] camera_id=%s falhou: %s", cam_id, exc)

            if once:
                break

            time.sleep(interval)

        self.stdout.write("Capture loop encerrado.")

    def _shutdown(self, signum, frame):
        self._running = False
        self.stdout.write("\nEncerrando capture loop...")
        sys.exit(0)
