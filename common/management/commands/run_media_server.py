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
    python manage.py run_media_server --watch-interval 5   # poll a cada 5s

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

        # ── Signal handling ──────────────────────────────────────────────────
        def _shutdown(signum, frame):
            self.stdout.write("\nEncerrando...")
            watcher.stop()
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            watcher.join()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        proc.wait()
        watcher.stop()
        watcher.join()
        sys.exit(proc.returncode)

    # ── helpers de output ────────────────────────────────────────────────────

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
        self.stdout.write(f"  HLS  : http://0.0.0.0:{hls_port}/<camera_key>")
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
