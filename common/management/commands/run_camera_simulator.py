"""
Management command: run_camera_simulator

Simula uma camera RTMP_PUSH transmitindo um arquivo .mp4 para o MediaMTX.
Util para testes locais sem camera fisica.

Fluxo:
    video.mp4 -> ffmpeg -> rtmp://<host>:1935/live/<camera_key>
                        -> MediaMTX
                        -> rtsp://<host>:8554/live/<camera_key>
                        -> run_capture_loop -> OCR -> AccessEvent

Uso:
    python manage.py run_camera_simulator --video videos/carros.mp4
    python manage.py run_camera_simulator --camera-key a1b2c3 --video carros.mp4
    python manage.py run_camera_simulator --camera "Entrada" --video carros.mp4 --no-loop
    python manage.py run_camera_simulator --list-cameras

Variaveis de ambiente usadas:
    MEDIAMTX_HOST       host do MediaMTX  (padrao: localhost)
    MEDIAMTX_RTMP_PORT  porta RTMP        (padrao: 1935)
    MEDIAMTX_RTSP_PORT  porta RTSP        (padrao: 8554)
    MEDIAMTX_HLS_PORT   porta HLS         (padrao: 8888)
"""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from cameras.models import Camera


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _setting_int(name: str, default: int) -> int:
    return int(getattr(settings, name, _env(name.upper(), str(default))))


class Command(BaseCommand):
    help = "Simula uma camera RTMP enviando um video .mp4 para o MediaMTX"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--camera-key",
            metavar="KEY",
            help="camera_key da camera no banco",
        )
        group.add_argument(
            "--camera",
            metavar="NOME_OU_ID",
            help="Nome (parcial, case-insensitive) ou ID numerico da camera",
        )
        group.add_argument(
            "--list-cameras",
            action="store_true",
            help="Lista cameras disponiveis e sai",
        )
        parser.add_argument(
            "--video",
            metavar="ARQUIVO",
            default="videos/carros.mp4",
            help="Caminho do arquivo de video (padrao: videos/carros.mp4)",
        )
        parser.add_argument(
            "--no-loop",
            action="store_true",
            help="Transmite o video uma unica vez (padrao: loop infinito)",
        )
        parser.add_argument(
            "--fps",
            type=int,
            default=25,
            help="FPS de saida (padrao: 25)",
        )
        parser.add_argument(
            "--width",
            type=int,
            default=1280,
            help="Largura do video de saida em pixels (padrao: 1280)",
        )
        parser.add_argument(
            "--host",
            default=_env("MEDIAMTX_HOST", getattr(settings, "MEDIAMTX_HOST", "localhost")),
            help="Host do MediaMTX (padrao: MEDIAMTX_HOST)",
        )
        parser.add_argument(
            "--rtmp-port",
            type=int,
            default=_setting_int("MEDIAMTX_RTMP_PORT", 1935),
            help="Porta RTMP do MediaMTX (padrao: 1935)",
        )

    # ── handle ────────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        if options["list_cameras"]:
            self._list_cameras()
            return

        camera = self._resolve_camera(options)
        if camera is None:
            sys.exit(1)

        video_path = self._resolve_video(options["video"])
        if video_path is None:
            sys.exit(1)

        if not shutil.which("ffmpeg"):
            self.stderr.write(self.style.ERROR(
                "\nffmpeg nao encontrado no PATH.\n"
                "  Windows : winget install --id Gyan.FFmpeg\n"
                "  Ubuntu  : sudo apt install ffmpeg\n"
                "  macOS   : brew install ffmpeg\n"
            ))
            sys.exit(1)

        host = options["host"]
        rtmp_port = options["rtmp_port"]
        rtmp_url = f"rtmp://{host}:{rtmp_port}/live/{camera.camera_key}"

        self._print_header(camera, video_path, rtmp_url, host, options)

        cmd = self._build_cmd(video_path, rtmp_url, options)
        self.stdout.write(self.style.HTTP_INFO(
            "$ " + " ".join(str(c) for c in cmd) + "\n"
        ))

        proc = subprocess.Popen(cmd)

        def _shutdown(signum, frame):
            self.stdout.write("\nEncerrando simulador...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        proc.wait()
        if proc.returncode not in (0, 255):
            self.stderr.write(self.style.ERROR(
                f"ffmpeg encerrou com codigo {proc.returncode}"
            ))
            sys.exit(proc.returncode)

    # ── resolvers ─────────────────────────────────────────────────────────────

    def _resolve_camera(self, options) -> Camera | None:
        camera_key = options.get("camera_key")
        camera_arg = options.get("camera")

        if camera_key:
            try:
                return Camera.objects.get(camera_key=camera_key)
            except Camera.DoesNotExist:
                self.stderr.write(self.style.ERROR(
                    f"Camera nao encontrada: camera_key={camera_key}"
                ))
                self._list_cameras()
                return None

        if camera_arg:
            if camera_arg.isdigit():
                try:
                    return Camera.objects.get(id=int(camera_arg))
                except Camera.DoesNotExist:
                    pass
            qs = Camera.objects.filter(name__icontains=camera_arg)
            if qs.count() == 1:
                return qs.first()
            if qs.count() > 1:
                self.stderr.write(self.style.WARNING(
                    f"Multiplas cameras encontradas para '{camera_arg}':"
                ))
                for cam in qs:
                    self.stdout.write(
                        f"  [{cam.id}] {cam.name}  key={cam.camera_key}"
                    )
                self.stderr.write("Use --camera-key para especificar.\n")
                return None
            self.stderr.write(self.style.ERROR(
                f"Camera nao encontrada: '{camera_arg}'"
            ))
            self._list_cameras()
            return None

        # Sem argumento: tenta selecionar automaticamente
        qs = Camera.objects.filter(
            is_active=True,
            connection_mode=Camera.ConnectionMode.RTMP_PUSH,
        )
        if qs.count() == 1:
            cam = qs.first()
            self.stdout.write(self.style.HTTP_INFO(
                f"[auto] Camera selecionada: {cam.name} (key={cam.camera_key})"
            ))
            return cam
        if qs.count() > 1:
            self.stderr.write(self.style.WARNING(
                "Multiplas cameras RTMP_PUSH ativas. Use --camera-key ou --camera:\n"
            ))
            for cam in qs:
                self.stdout.write(
                    f"  [{cam.id}] {cam.name}  key={cam.camera_key}"
                )
            return None

        self.stderr.write(self.style.ERROR(
            "\nNenhuma camera RTMP_PUSH ativa encontrada.\n"
            "Crie uma camera com connection_mode=rtmp_push e is_active=True,\n"
            "depois use --camera-key <key> ou --camera <nome>.\n"
        ))
        self._list_cameras()
        return None

    def _resolve_video(self, video_arg: str) -> Path | None:
        path = Path(video_arg)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        if path.exists():
            return path
        self.stderr.write(self.style.ERROR(
            f"\nArquivo de video nao encontrado: {path}\n"
            "\nComo obter um video de teste:\n"
            "  1. Coloque qualquer .mp4 com carros em videos/carros.mp4\n"
            "  2. Ou passe o caminho: --video C:\\Videos\\teste.mp4\n"
            "  3. Download de exemplo (sem placas):\n"
            "     https://www.pexels.com/search/videos/traffic/\n"
        ))
        return None

    # ── ffmpeg ────────────────────────────────────────────────────────────────

    def _build_cmd(self, video_path: Path, rtmp_url: str, options: dict) -> list:
        loop_flags = [] if options["no_loop"] else ["-stream_loop", "-1"]
        return [
            "ffmpeg",
            "-re",                          # velocidade real (simula camera ao vivo)
            *loop_flags,
            "-i", str(video_path),
            "-vf", f"scale={options['width']}:-2,fps={options['fps']}",
            "-an",                          # sem audio (cameras LPR nao precisam)
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-f", "flv",
            rtmp_url,
        ]

    # ── output ────────────────────────────────────────────────────────────────

    def _print_header(
        self,
        camera: Camera,
        video_path: Path,
        rtmp_url: str,
        host: str,
        options: dict,
    ) -> None:
        rtsp_port = _setting_int("MEDIAMTX_RTSP_PORT", 8554)
        hls_port  = _setting_int("MEDIAMTX_HLS_PORT", 8888)
        loop_msg  = "loop infinito" if not options["no_loop"] else "uma vez"
        key       = camera.camera_key

        self.stdout.write(self.style.HTTP_INFO("-" * 62))
        self.stdout.write(f"  Camera  : {camera.name}")
        self.stdout.write(f"  Key     : {key}")
        self.stdout.write(f"  Video   : {video_path.name}  ({loop_msg})")
        self.stdout.write(f"  Push -> : {rtmp_url}")
        self.stdout.write(f"  RTSP <- : rtsp://{host}:{rtsp_port}/live/{key}")
        self.stdout.write(f"  HLS  <- : http://{host}:{hls_port}/live/{key}/index.m3u8")
        self.stdout.write(self.style.HTTP_INFO("-" * 62))
        self.stdout.write(
            "Pressione Ctrl+C para encerrar o simulador.\n"
        )

    def _list_cameras(self) -> None:
        cameras = Camera.objects.order_by("name")
        if not cameras.exists():
            self.stdout.write(self.style.WARNING("Nenhuma camera cadastrada no banco."))
            return
        self.stdout.write(self.style.HTTP_INFO(f"\nCameras cadastradas ({cameras.count()}):"))
        for cam in cameras:
            active = "[ativa]  " if cam.is_active else "[inativa]"
            self.stdout.write(
                f"  [{cam.id:>3}] {active}  "
                f"{cam.get_connection_mode_display():<12}  "
                f"key={cam.camera_key}  {cam.name}"
            )
        self.stdout.write("")
