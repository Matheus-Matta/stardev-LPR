"""
Management command: run_media_server

Inicia o MediaMTX e mantém os paths sincronizados automaticamente com o banco
de dados — sem necessidade de reiniciar quando câmeras são adicionadas,
removidas ou modificadas.

Arquitetura:
  processo principal  →  inicia mediamtx como subprocess e aguarda
  thread CameraWatcher → poll no banco a cada N segundos, usa a API REST do
                          MediaMTX para adicionar / atualizar / remover paths
                          em runtime, sem interromper streams existentes

Modos de câmera:
  RTMP_PUSH   → câmera faz push para rtmp://<host>:1935/live/<camera_key>
  DIRECT_RTSP → MediaMTX faz pull do RTSP da câmera
  GATEWAY     → gateway local faz push (RTMP ou RTSP) para o MediaMTX
  PUSH        → ingestão HTTP frame-a-frame direto no Django; não usa MediaMTX

Uso:
    python manage.py run_media_server
    python manage.py run_media_server --config-only
    python manage.py run_media_server --watch-interval 5          # poll a cada 5s
    python manage.py run_media_server --plate-log placas.log      # captura + OCR + log

Variáveis de ambiente:
    MEDIAMTX_BINARY          caminho do binário     (padrão: mediamtx)
    MEDIAMTX_CONFIG          caminho do YAML gerado (padrão: mediamtx.yml)
    MEDIAMTX_RTSP_PORT       porta RTSP             (padrão: 8554)
    MEDIAMTX_RTMP_PORT       porta RTMP             (padrão: 1935)
    MEDIAMTX_HLS_PORT        porta HLS              (padrão: 8888)
    MEDIAMTX_API_PORT        porta API interna      (padrão: 9997)
    MEDIAMTX_LOG_LEVEL       debug/info/warn/error  (padrão: info)
    MEDIAMTX_WATCH_INTERVAL  segundos entre polls   (padrão: 10)
"""

import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests
import yaml
from django.core.management.base import BaseCommand

from cameras.models import Camera

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _path_config(cam: Camera) -> dict:
    """Retorna o dict de configuração de um path para o MediaMTX."""
    if cam.connection_mode == Camera.ConnectionMode.DIRECT_RTSP:
        return {
            "source": cam.rtsp_url,
            "sourceOnDemand": True,
        }
    # RTMP_PUSH e GATEWAY: a câmera/gateway faz push — MediaMTX só aguarda
    return {"source": "publisher"}


def _base_config(rtsp_port: int, rtmp_port: int, hls_port: int,
                 api_port: int, log_level: str) -> dict:
    return {
        "logLevel":        log_level,
        "logDestinations": ["stdout"],
        # Buffer grande por leitor — absorve picos de latência sem descartar frames.
        # Padrão do MediaMTX: 512. Com OCR em Python (5-6 s no primeiro frame),
        # um buffer maior evita o aviso "reader is too slow".
        "readBufferCount": 4096,
        "rtsp":            True,
        "rtspAddress":     f":{rtsp_port}",
        "rtspTransports":  ["tcp"],
        "rtmp":            True,
        "rtmpAddress":     f":{rtmp_port}",
        "hls":             True,
        "hlsAddress":      f":{hls_port}",
        "hlsAlwaysRemux":  False,
        "api":             True,
        "apiAddress":      f"127.0.0.1:{api_port}",
        "paths":           {},
    }


def _load_cameras(all_cameras: bool = False) -> list[Camera]:
    qs = Camera.objects.exclude(connection_mode=Camera.ConnectionMode.PUSH)
    if not all_cameras:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("name"))


# ── CameraWatcher ─────────────────────────────────────────────────────────────

class CameraWatcher:
    """
    Thread que mantém os paths do MediaMTX sincronizados com o banco.

    Usa a API REST do MediaMTX (porta 9997) para adicionar, atualizar e
    remover paths em runtime — sem reiniciar o processo nem interromper
    streams existentes.
    """

    def __init__(
        self,
        api_port: int,
        poll_interval: int,
        stdout,
        style,
    ) -> None:
        self._base_url = f"http://127.0.0.1:{api_port}/v3"
        self._poll_interval = poll_interval
        self._stdout = stdout
        self._style = style

        # path_key → config dict do que foi aplicado com sucesso
        self._known: dict[str, dict] = {}
        self._initialized = False
        self._running = True

        self._thread = threading.Thread(
            target=self._loop,
            name="camera-watcher",
            daemon=True,
        )

    # ── API pública ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def join(self, timeout: float = 3.0) -> None:
        self._thread.join(timeout=timeout)

    # ── loop interno ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        try:
            self._wait_for_api()
        except RuntimeError as exc:
            self._warn(str(exc))
            return

        while self._running:
            try:
                self._sync()
            except Exception as exc:
                self._warn(f"erro no ciclo de sync: {exc}")
            time.sleep(self._poll_interval)

    def _wait_for_api(self, retries: int = 60) -> None:
        self._info("aguardando API do MediaMTX...")
        for _ in range(retries):
            try:
                # Qualquer resposta HTTP (mesmo 4xx) indica que a API está de pé.
                # Só requests.RequestException (timeout, refused) significa que não.
                requests.get(f"{self._base_url}/paths/list", timeout=2)
                self._ok("API do MediaMTX disponivel - hot-reload ativo")
                return
            except requests.RequestException:
                pass
            time.sleep(1)
        raise RuntimeError(
            f"API do MediaMTX nao ficou disponivel em {retries}s"
        )

    # ── sync ──────────────────────────────────────────────────────────────────

    def _sync(self) -> None:
        desired = self._desired_paths()

        # Na primeira execução, inicializa _known com o que o MediaMTX já tem
        # configurado (paths carregados do YAML inicial), para não re-adicionar
        # caminhos que já existem.
        if not self._initialized:
            self._bootstrap_known(desired)
            self._initialized = True

        current = dict(self._known)
        added = updated = removed = 0

        # Adicionar ou atualizar
        for key, config in desired.items():
            if key not in current:
                if self._api("POST", f"config/paths/add/{_encode(key)}", config):
                    current[key] = config
                    added += 1
            elif current[key] != config:
                old_is_publisher = current[key].get("source") == "publisher"
                new_is_publisher = config.get("source") == "publisher"
                if old_is_publisher != new_is_publisher:
                    # Mudança de tipo de source (RTSP pull ↔ RTMP push): PATCH faz
                    # merge e deixa campos incompatíveis (ex.: sourceOnDemand+publisher).
                    # Solução: DELETE + POST para recriar o path limpo.
                    if self._api("DELETE", f"config/paths/remove/{_encode(key)}"):
                        if self._api("POST", f"config/paths/add/{_encode(key)}", config):
                            current[key] = config
                            updated += 1
                else:
                    if self._api("PATCH", f"config/paths/patch/{_encode(key)}", config):
                        current[key] = config
                        updated += 1

        # Remover paths que saíram do banco
        for key in list(current.keys()):
            if key not in desired:
                if self._api("DELETE", f"config/paths/remove/{_encode(key)}"):
                    del current[key]
                    removed += 1

        self._known = current

        if added or updated or removed:
            self._ok(
                f"sync  +{added} nova(s)  ~{updated} atualizada(s)"
                f"  -{removed} removida(s)"
            )

    def _bootstrap_known(self, desired: dict[str, dict]) -> None:
        """Popula _known com paths já presentes no MediaMTX (do YAML inicial)."""
        try:
            r = requests.get(
                f"{self._base_url}/config/paths/list", timeout=5
            )
            r.raise_for_status()
            existing_keys = {
                item["name"] for item in r.json().get("items", [])
            }
            for key in existing_keys:
                if key in desired:
                    self._known[key] = desired[key]
            self._info(
                f"bootstrap: {len(self._known)} path(s) já configurado(s) no MediaMTX"
            )
        except Exception as exc:
            self._warn(f"bootstrap falhou, iniciando do zero: {exc}")

    # ── HTTP helper ───────────────────────────────────────────────────────────

    def _api(
        self,
        method: str,
        path: str,
        data: dict | None = None,
    ) -> bool:
        url = f"{self._base_url}/{path}"
        try:
            kwargs: dict = {"timeout": 5}
            if data is not None:
                kwargs["json"] = data
            r = requests.request(method, url, **kwargs)
            r.raise_for_status()
            return True
        except requests.HTTPError as exc:
            self._warn(
                f"{method} {path} → HTTP {exc.response.status_code} "
                f"{exc.response.text[:120]}"
            )
        except requests.RequestException as exc:
            self._warn(f"{method} {path} → {exc}")
        return False

    # ── DB query ──────────────────────────────────────────────────────────────

    @staticmethod
    def _desired_paths() -> dict[str, dict]:
        cameras = list(
            Camera.objects.filter(is_active=True)
            .exclude(connection_mode=Camera.ConnectionMode.PUSH)
        )
        return {f"live/{cam.camera_key}": _path_config(cam) for cam in cameras}

    # ── log helpers ───────────────────────────────────────────────────────────

    def _info(self, msg: str) -> None:
        self._stdout.write(self._style.HTTP_INFO(f"[watcher] {msg}"))

    def _ok(self, msg: str) -> None:
        self._stdout.write(self._style.SUCCESS(f"[watcher] {msg}"))

    def _warn(self, msg: str) -> None:
        self._stdout.write(self._style.WARNING(f"[watcher] {msg}"))
        logger.warning("[watcher] %s", msg)


def _encode(path_key: str) -> str:
    """URL-encoda a chave do path (ex.: 'live/abc' → 'live%2Fabc')."""
    return quote(path_key, safe="")


# ── CaptureLoopThread ─────────────────────────────────────────────────────────

class _CameraWorker:
    """
    Dois threads por câmera com fila de tamanho 1:

      reader  →  cap.read() bloqueante  →  queue  →  ocr → salva

    O reader nunca bloqueia no OCR. Se o OCR ainda estiver processando
    quando o próximo frame chegar, o frame antigo é descartado e o novo
    ocupa a fila — garantindo que o OCR sempre analise o frame mais recente.
    """

    def __init__(self, camera_id: int) -> None:
        self._id = camera_id
        self._running = True
        self._queue: queue.Queue = queue.Queue(maxsize=1)

        self._reader = threading.Thread(
            target=self._reader_loop,
            name=f"cam-{camera_id}-r",
            daemon=True,
        )
        self._ocr = threading.Thread(
            target=self._ocr_loop,
            name=f"cam-{camera_id}-ocr",
            daemon=True,
        )

    def start(self) -> None:
        self._reader.start()
        self._ocr.start()

    def stop(self) -> None:
        self._running = False

    def join(self, timeout: float = 3.0) -> None:
        self._reader.join(timeout=timeout)
        self._ocr.join(timeout=timeout)

    # ── reader ────────────────────────────────────────────────────────────────

    # Porcentagem dos frames que serão decodificados e enviados ao OCR.
    # Controlado por CAPTURE_ANALYZE_PCT no .env (padrão: 5%).
    #
    # Intervalo resultante por FPS (5%):
    #   30 fps → 1 frame a cada 0,67 s  ← ideal para placas paradas 3-5 s
    #   25 fps → 1 frame a cada 0,80 s
    #   15 fps → 1 frame a cada 1,33 s
    # Limites: mínimo 0,5 s · máximo 5 s
    _ANALYZE_PCT    = float(os.environ.get("CAPTURE_ANALYZE_PCT", "0.05"))
    _INTERVAL_MIN_S = 0.5    # nunca mais rápido que isso
    _INTERVAL_MAX_S = 5.0    # nunca mais lento que isso

    @classmethod
    def _calc_interval(cls, fps: float) -> float:
        """Intervalo de enqueue em segundos para a taxa configurada."""
        fps = max(1.0, fps)
        raw = 1.0 / (fps * max(0.001, cls._ANALYZE_PCT))
        return max(cls._INTERVAL_MIN_S, min(cls._INTERVAL_MAX_S, raw))

    def _reader_loop(self) -> None:
        from cameras.models import Camera
        from cameras.tasks import _get_cap, _release_cap

        _CAP_PROP_FPS = 5   # cv2.CAP_PROP_FPS — constante numérica evita import

        try:
            camera = Camera.objects.get(id=self._id)
        except Exception as exc:
            logger.warning("[cam-%s] câmera não encontrada: %s", self._id, exc)
            return

        if camera.connection_mode == camera.ConnectionMode.PUSH:
            return  # câmeras PUSH não usam RTSP pull

        url = camera.capture_rtsp_url
        last_enqueue   = 0.0
        enqueue_interval = self._INTERVAL_MAX_S   # conservador até FPS conhecido
        fps_detected   = False

        while self._running:
            try:
                cap = _get_cap(url)

                # ── Detecta FPS uma vez por conexão ──────────────────────────
                if not fps_detected:
                    raw_fps = cap.get(_CAP_PROP_FPS) or 30.0
                    stream_fps = max(1.0, float(raw_fps))
                    enqueue_interval = self._calc_interval(stream_fps)
                    logger.info(
                        "[cam-%s] stream FPS=%s  analisando %s%% → 1 frame/%ss",
                        self._id, round(stream_fps, 1),
                        round(self._ANALYZE_PCT * 100), round(enqueue_interval, 2),
                    )
                    fps_detected = True

                # grab() consome o pacote H.264 sem decodificar — drena o stream
                # na velocidade nativa sem "reader is too slow" no MediaMTX.
                ret = cap.grab()
                if not ret:
                    _release_cap(url)
                    fps_detected = False          # reset ao reconectar
                    time.sleep(2.0)
                    continue

                # Decodifica e enfileira apenas quando o intervalo expirou
                now = time.monotonic()
                if now - last_enqueue >= enqueue_interval:
                    ret, frame = cap.retrieve()
                    if ret and frame is not None:
                        if self._queue.full():
                            try:
                                self._queue.get_nowait()
                            except queue.Empty:
                                pass
                        self._queue.put_nowait(frame)
                        last_enqueue = now

            except Exception as exc:
                msg = str(exc)
                if "unavailable" in msg or "404" in msg or "400 Bad" in msg:
                    time.sleep(2.0)
                else:
                    logger.warning("[cam-%s] reader erro: %s", self._id, exc)
                    time.sleep(1.0)
                fps_detected = False              # reset ao reconectar por erro

    # ── ocr ───────────────────────────────────────────────────────────────────

    def _ocr_loop(self) -> None:
        from plates.lpr_pipeline import LPRPipeline
        from cameras.tasks import _save_plate_event
        from cameras.models import Camera as _Camera

        roi = None
        try:
            cam = _Camera.objects.get(id=self._id)
            raw = cam.lpr_roi
            if raw and len(raw) == 4:
                roi = tuple(int(v) for v in raw)
        except Exception:
            pass

        pipeline = LPRPipeline(camera_id=self._id, roi=roi)
        logger.info("[cam-%s] LPR pipeline iniciado  roi=%s", self._id, roi)

        frames_analyzed = 0
        total_ocr_ms    = 0.0
        _LOG_EVERY      = 50   # loga métricas a cada 50 frames analisados

        while self._running:
            try:
                frame = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                t0 = time.monotonic()
                events = pipeline.process_frame(frame)
                ocr_ms = (time.monotonic() - t0) * 1000

                frames_analyzed += 1
                total_ocr_ms    += ocr_ms

                if frames_analyzed % _LOG_EVERY == 0:
                    avg_ms = total_ocr_ms / frames_analyzed
                    logger.info(
                        "[cam-%s] métricas  frames=%s  ocr_avg=%s ms",
                        self._id, frames_analyzed, round(avg_ms, 1),
                    )

                for event in events:
                    try:
                        _save_plate_event(event, frame)
                    except Exception as exc:
                        logger.warning("[cam-%s] save_plate_event erro: %s", self._id, exc)
            except Exception as exc:
                logger.warning("[cam-%s] ocr erro: %s", self._id, exc)


class CaptureLoopThread:
    """
    Gerencia um _CameraWorker por câmera ativa.

    Cada câmera roda seu próprio thread grab→OCR em loop contínuo,
    sem coordenação central nem overhead do Celery eager mode.
    Detecta câmeras adicionadas/removidas a cada 5 segundos.
    """

    def __init__(self, interval: float, workers: int) -> None:
        self._running = True
        self._workers: dict[int, _CameraWorker] = {}
        self._thread = threading.Thread(
            target=self._manage_loop,
            name="capture-manager",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        for w in list(self._workers.values()):
            w.stop()

    def join(self, timeout: float = 5.0) -> None:
        for w in list(self._workers.values()):
            w.join(timeout=1.0)
        self._thread.join(timeout=timeout)

    def _manage_loop(self) -> None:
        from cameras.models import Camera
        while self._running:
            try:
                active = set(
                    Camera.objects
                    .filter(is_active=True)
                    .exclude(connection_mode=Camera.ConnectionMode.PUSH)
                    .values_list("id", flat=True)
                )
                for cid in active - set(self._workers):
                    w = _CameraWorker(cid)
                    self._workers[cid] = w
                    w.start()
                    logger.info("[capture] worker iniciado  camera_id=%s", cid)
                for cid in set(self._workers) - active:
                    self._workers.pop(cid).stop()
                    logger.info("[capture] worker parado  camera_id=%s", cid)
            except Exception as exc:
                logger.warning("[capture] manager erro: %s", exc)
            time.sleep(5.0)


def _enable_plate_log(path: str) -> None:
    import logging as _logging
    fh = _logging.FileHandler(path, encoding="utf-8")
    fh.setLevel(_logging.DEBUG)
    fh.setFormatter(_logging.Formatter("%(message)s"))
    det = _logging.getLogger("lpr.detections")
    det.addHandler(fh)
    det.setLevel(_logging.DEBUG)
    det.propagate = True


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = (
        "Inicia o MediaMTX com hot-reload automático de câmeras via API REST"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--binary",
            default=_env("MEDIAMTX_BINARY", "mediamtx"),
            help="Caminho do binário mediamtx (padrão: mediamtx)",
        )
        parser.add_argument(
            "--config",
            default=_env("MEDIAMTX_CONFIG", "mediamtx.yml"),
            help="Onde gravar o YAML gerado (padrão: mediamtx.yml)",
        )
        parser.add_argument(
            "--rtsp-port",
            type=int,
            default=int(_env("MEDIAMTX_RTSP_PORT", "8554")),
        )
        parser.add_argument(
            "--rtmp-port",
            type=int,
            default=int(_env("MEDIAMTX_RTMP_PORT", "1935")),
        )
        parser.add_argument(
            "--hls-port",
            type=int,
            default=int(_env("MEDIAMTX_HLS_PORT", "8888")),
        )
        parser.add_argument(
            "--api-port",
            type=int,
            default=int(_env("MEDIAMTX_API_PORT", "9997")),
        )
        parser.add_argument(
            "--log-level",
            default=_env("MEDIAMTX_LOG_LEVEL", "info"),
            choices=["debug", "info", "warn", "error"],
        )
        parser.add_argument(
            "--watch-interval",
            type=int,
            default=int(_env("MEDIAMTX_WATCH_INTERVAL", "10")),
            help="Segundos entre verificações de novas câmeras (padrão: 10)",
        )
        parser.add_argument(
            "--config-only",
            action="store_true",
            help="Apenas gera o YAML; não inicia o processo",
        )
        parser.add_argument(
            "--all-cameras",
            action="store_true",
            help="Inclui câmeras inativas (padrão: só ativas)",
        )
        parser.add_argument(
            "--plate-log",
            metavar="ARQUIVO",
            default="",
            help="Ativa capture loop + OCR e salva detecções em arquivo (ex: placas.log)",
        )
        parser.add_argument(
            "--capture-interval",
            type=float,
            default=0.0,
            help="Segundos de espera entre ciclos de captura (padrão: 0 = máximo possível)",
        )
        parser.add_argument(
            "--capture-workers",
            type=int,
            default=int(_env("CAPTURE_WORKERS", "50")),
            help="Threads paralelas de captura (padrão: 50)",
        )

    def handle(self, *args, **options):
        binary         = options["binary"]
        config_path    = Path(options["config"])
        rtsp_port      = options["rtsp_port"]
        rtmp_port      = options["rtmp_port"]
        hls_port       = options["hls_port"]
        api_port       = options["api_port"]
        log_level      = options["log_level"]
        watch_interval = options["watch_interval"]
        config_only    = options["config_only"]
        all_cameras    = options["all_cameras"]

        # ── Gerar config inicial ──────────────────────────────────────────────
        cameras = _load_cameras(all_cameras)
        self._print_camera_list(cameras)

        config = _base_config(rtsp_port, rtmp_port, hls_port, api_port, log_level)
        config["paths"] = {
            f"live/{cam.camera_key}": _path_config(cam) for cam in cameras
        }
        config_path.write_text(yaml.dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"[OK] Config gerado: {config_path.resolve()}"))
        self._print_lpr_profile()
        self._print_endpoints(cameras, rtsp_port, rtmp_port, hls_port)

        if config_only:
            return

        # ── Verificar binário ────────────────────────────────────────────────
        if not shutil.which(binary) and not Path(binary).is_file():
            self.stderr.write(self.style.ERROR(
                f"\nBinário '{binary}' não encontrado.\n"
                "  https://github.com/bluenviron/mediamtx/releases\n"
            ))
            sys.exit(1)

        # ── Iniciar MediaMTX ─────────────────────────────────────────────────
        self.stdout.write(
            self.style.HTTP_INFO(f"\nIniciando MediaMTX ({binary})...")
        )
        proc = subprocess.Popen(
            [binary, str(config_path)],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        # ── Iniciar watcher ──────────────────────────────────────────────────
        watcher = CameraWatcher(
            api_port=api_port,
            poll_interval=watch_interval,
            stdout=self.stdout,
            style=self.style,
        )
        watcher.start()
        self.stdout.write(
            self.style.HTTP_INFO(
                f"[watcher] ativo (poll a cada {watch_interval}s)"
                " - novas cameras detectadas automaticamente"
            )
        )

        # ── Capture loop (sempre ativo) + plate log opcional ─────────────────
        if options["plate_log"]:
            _enable_plate_log(options["plate_log"])
            self.stdout.write(self.style.SUCCESS(
                f"[capture] plate-log → {options['plate_log']}"
            ))

        capture_thread = CaptureLoopThread(
            interval=options["capture_interval"],
            workers=options["capture_workers"],
        )
        capture_thread.start()
        self.stdout.write(self.style.SUCCESS(
            f"[capture] OCR workers iniciados  "
            f"max_workers={options['capture_workers']}  "
            f"taxa_analise={_CameraWorker._ANALYZE_PCT * 100:.0f}%_dos_frames  "
            f"intervalo={_CameraWorker._INTERVAL_MIN_S}–{_CameraWorker._INTERVAL_MAX_S}s"
        ))

        # ── Signal handling ──────────────────────────────────────────────────
        def _shutdown(signum, frame):
            self.stdout.write("\nEncerrando...")
            if capture_thread:
                capture_thread.stop()
            watcher.stop()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            if capture_thread:
                capture_thread.join()
            watcher.join()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        proc.wait()
        if capture_thread:
            capture_thread.stop()
            capture_thread.join()
        watcher.stop()
        watcher.join()
        sys.exit(proc.returncode)

    # ── helpers de output ────────────────────────────────────────────────────

    def _print_lpr_profile(self) -> None:
        profile  = _env("ENV_PROFILE_LPR", "—")
        engine   = _env("LPR_ENGINE",  "fast_alpr")
        app_env  = _env("APP_ENV",     "dev")
        device   = _env("LPR_DEVICE",  "cpu")
        provider = _env("ONNX_PROVIDERS", "CPUExecutionProvider").split(",")[0]
        pct      = _env("CAPTURE_ANALYZE_PCT", "0.10")

        self.stdout.write(self.style.HTTP_INFO("-" * 56))
        self.stdout.write(self.style.HTTP_INFO("  LPR Engine"))
        self.stdout.write(f"  Perfil   : {profile}")
        self.stdout.write(f"  Engine   : {engine}  [{app_env.upper()}]")
        self.stdout.write(f"  Device   : {device}  provider={provider}")
        self.stdout.write(f"  Analise  : {pct} dos frames (~{round(1/(max(0.001,float(pct))*30),2)}s entre frames a 30fps)")
        self.stdout.write(self.style.HTTP_INFO("-" * 56))

    def _print_camera_list(self, cameras: list[Camera]) -> None:
        self.stdout.write(
            self.style.HTTP_INFO(f"Cameras no banco: {len(cameras)}")
        )
        for cam in cameras:
            self.stdout.write(
                f"  - {cam.name} [{cam.get_connection_mode_display()}]"
                f"  key={cam.camera_key}"
            )

    def _print_endpoints(
        self,
        cameras: list[Camera],
        rtsp_port: int,
        rtmp_port: int,
        hls_port: int,
    ) -> None:
        rtmp_cams = [c for c in cameras if c.connection_mode == Camera.ConnectionMode.RTMP_PUSH]
        rtsp_cams = [c for c in cameras if c.connection_mode == Camera.ConnectionMode.DIRECT_RTSP]

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("-" * 56))
        self.stdout.write(f"  RTSP : rtsp://0.0.0.0:{rtsp_port}/live/<camera_key>")
        self.stdout.write(f"  RTMP : rtmp://0.0.0.0:{rtmp_port}/live/<camera_key>")
        self.stdout.write(f"  HLS  : http://0.0.0.0:{hls_port}/live/<camera_key>/index.m3u8")
        self.stdout.write("")
        if rtmp_cams:
            self.stdout.write(
                f"  {len(rtmp_cams)} camera(s) RTMP Push"
                f" - configure stream para rtmp://<servidor>:{rtmp_port}/live/<camera_key>"
            )
        if rtsp_cams:
            self.stdout.write(
                f"  {len(rtsp_cams)} camera(s) RTSP Pull - MediaMTX busca da camera"
            )
        self.stdout.write(self.style.HTTP_INFO("-" * 56))
        self.stdout.write("")
