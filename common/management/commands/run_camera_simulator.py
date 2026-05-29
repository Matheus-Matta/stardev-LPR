"""
Management command: run_camera_simulator

Simula câmeras RTMP_PUSH de alto padrão (estilo Intelbras VIP 5550 Z / VIP 7220)
transmitindo um .mp4 para o MediaMTX.

Características do perfil Intelbras simulado:
  - Resolução   : 1920×1080 (Full HD)
  - Codec       : H.264 Main Profile, Level 4.1
  - Bitrate     : 2 Mbps CBR (ajustável)
  - GOP         : I-frame a cada 2 s (proporcional ao fps)
  - B-frames    : desativados (low-latency, padrão câmeras de segurança)
  - OSD         : timestamp + nome da câmera (como câmeras reais)
  - Áudio       : desativado (câmeras LPR)

Fluxo:
    video.mp4 → ffmpeg (perfil Intelbras) → rtmp://<host>:1935/live/<camera_key>
                                          → MediaMTX
                                          → rtsp://<host>:8554/live/<camera_key>
                                          → _CameraWorker → OCR → AccessEvent

Uso:
    python manage.py run_camera_simulator --video videos/carros.mp4
    python manage.py run_camera_simulator --all-cameras --video carros.mp4
    python manage.py run_camera_simulator --camera "Entrada" --fps 5 --bitrate 4M
    python manage.py run_camera_simulator --camera-key a1b2c3 --no-loop --no-osd
    python manage.py run_camera_simulator --list-cameras

Variáveis de ambiente:
    MEDIAMTX_HOST       host do MediaMTX  (padrão: localhost)
    MEDIAMTX_RTMP_PORT  porta RTMP        (padrão: 1935)
    MEDIAMTX_RTSP_PORT  porta RTSP        (padrão: 8554)
    MEDIAMTX_HLS_PORT   porta HLS         (padrão: 8888)
"""

import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from cameras.models import Camera

# ── OSD / font ───────────────────────────────────────────────────────────────
# Intelbras câmeras usam fonte monoespaçada para o timestamp no OSD.
# Detectamos o caminho da fonte por plataforma; se não existir, OSD é desativado.

_FONT_CANDIDATES = {
    "Windows": [
        "C:/Windows/Fonts/cour.ttf",    # Courier New (monospace)
        "C:/Windows/Fonts/arial.ttf",
    ],
    "Linux": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    ],
    "Darwin": [
        "/System/Library/Fonts/Courier.ttc",
        "/Library/Fonts/Arial.ttf",
    ],
}


def _detect_font() -> str | None:
    system = platform.system()
    for candidate in _FONT_CANDIDATES.get(system, []):
        if Path(candidate).exists():
            return candidate
    return None


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip()


def _setting_int(name: str, default: int) -> int:
    return int(getattr(settings, name, _env(name.upper(), str(default))))


class Command(BaseCommand):
    help = "Simula câmeras Intelbras (RTMP) enviando vídeo .mp4 para o MediaMTX"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--camera-key",
            metavar="KEY",
            help="camera_key da câmera no banco",
        )
        group.add_argument(
            "--camera",
            metavar="NOME_OU_ID",
            help="Nome (parcial, case-insensitive) ou ID numérico da câmera",
        )
        group.add_argument(
            "--all-cameras",
            action="store_true",
            help="Simula todas as câmeras RTMP_PUSH ativas em paralelo",
        )
        group.add_argument(
            "--list-cameras",
            action="store_true",
            help="Lista câmeras disponíveis e sai",
        )

        # Vídeo
        parser.add_argument(
            "--video",
            metavar="ARQUIVO",
            default="tests/videos/carros.mp4",
            help="Caminho do arquivo de vídeo (padrão: tests/videos/carros.mp4)",
        )
        parser.add_argument(
            "--no-loop",
            action="store_true",
            help="Transmite o vídeo uma única vez (padrão: loop infinito)",
        )

        # Perfil de câmera (estilo Intelbras)
        parser.add_argument(
            "--fps",
            type=float,
            default=30.0,
            help="FPS de saída (padrão: 30 — resolução nativa Full HD Intelbras)",
        )
        parser.add_argument(
            "--width",
            type=int,
            default=1920,
            help="Largura do vídeo (padrão: 1920 — Full HD Intelbras)",
        )
        parser.add_argument(
            "--height",
            type=int,
            default=1080,
            help="Altura do vídeo (padrão: 1080 — Full HD Intelbras)",
        )
        parser.add_argument(
            "--bitrate",
            default="2M",
            help="Bitrate CBR de saída (padrão: 2M — 2 Mbps Intelbras 1080p)",
        )
        parser.add_argument(
            "--profile",
            default="main",
            choices=["baseline", "main", "high"],
            help="H.264 profile (padrão: main — padrão Intelbras)",
        )
        parser.add_argument(
            "--no-osd",
            action="store_true",
            help="Desativa overlay de timestamp e nome (OSD)",
        )

        # Rede
        parser.add_argument(
            "--host",
            default=_env("MEDIAMTX_HOST", getattr(settings, "MEDIAMTX_HOST", "localhost")),
            help="Host do MediaMTX (padrão: MEDIAMTX_HOST)",
        )
        parser.add_argument(
            "--rtmp-port",
            type=int,
            default=_setting_int("MEDIAMTX_RTMP_PORT", 1935),
            help="Porta RTMP do MediaMTX (padrão: 1935)",
        )
        parser.add_argument(
            "--ngrok",
            action="store_true",
            help=(
                "Usa MEDIAMTX_RTMP_PUBLIC_URL do .env como destino RTMP "
                "(túnel ngrok para testes externos)"
            ),
        )

        # Debug
        parser.add_argument(
            "--ffmpeg-log",
            action="store_true",
            help="Exibe saída completa do ffmpeg no terminal (padrão: silenciada)",
        )

    # ── handle ────────────────────────────────────────────────────────────────

    def _rtmp_base(self, options: dict) -> str:
        """Retorna a base RTMP (sem /live/<key>) a usar nesta sessão."""
        if options.get("ngrok"):
            url = getattr(settings, "MEDIAMTX_RTMP_PUBLIC_URL", "").strip().rstrip("/")
            if not url:
                self.stderr.write(self.style.ERROR(
                    "MEDIAMTX_RTMP_PUBLIC_URL não definida no .env.\n"
                    "Configure o ngrok e adicione a URL ao .env antes de usar --ngrok."
                ))
                sys.exit(1)
            # Garante esquema rtmp:// (o valor no .env pode omitir)
            if not url.startswith("rtmp://"):
                url = "rtmp://" + url.lstrip("/")
            return url
        host      = options["host"]
        rtmp_port = options["rtmp_port"]
        return f"rtmp://{host}:{rtmp_port}"

    def handle(self, *args, **options):
        if options["list_cameras"]:
            self._list_cameras()
            return

        if not shutil.which("ffmpeg"):
            self.stderr.write(self.style.ERROR(
                "\nffmpeg não encontrado no PATH.\n"
                "  Windows : winget install --id Gyan.FFmpeg\n"
                "  Ubuntu  : sudo apt install ffmpeg\n"
                "  macOS   : brew install ffmpeg\n"
            ))
            sys.exit(1)

        video_path = self._resolve_video(options["video"])
        if video_path is None:
            sys.exit(1)

        # Detecta fonte para OSD
        font = None if options["no_osd"] else _detect_font()
        if not options["no_osd"] and font is None:
            self.stdout.write(self.style.WARNING(
                "[osd] Fonte não encontrada — OSD desativado. "
                "Use --no-osd para suprimir este aviso."
            ))
        options["_font"] = font

        if options["all_cameras"]:
            self._simulate_all(video_path, options)
        else:
            camera = self._resolve_camera(options)
            if camera is None:
                sys.exit(1)
            self._simulate_one(camera, video_path, options, show_header=True)

    # ── simulação única ───────────────────────────────────────────────────────

    def _simulate_one(
        self,
        camera: Camera,
        video_path: Path,
        options: dict,
        show_header: bool = False,
    ) -> None:
        host = options["host"]
        rtmp_url = f"{self._rtmp_base(options)}/live/{camera.camera_key}"

        if show_header:
            self._print_header(camera, video_path, rtmp_url, host, options)

        cmd = self._build_cmd(video_path, rtmp_url, camera.name, options)
        self.stdout.write(self.style.HTTP_INFO(
            "$ " + " ".join(str(c) for c in cmd) + "\n"
        ))

        sink = None if options["ffmpeg_log"] else subprocess.DEVNULL
        proc = subprocess.Popen(cmd, stdout=sink, stderr=sink)

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
                f"ffmpeg encerrou com código {proc.returncode}"
            ))
            sys.exit(proc.returncode)

    # ── simulação paralela (todas câmeras) ────────────────────────────────────

    def _simulate_all(self, video_path: Path, options: dict) -> None:
        cameras = list(
            Camera.objects.filter(
                is_active=True,
                connection_mode=Camera.ConnectionMode.RTMP_PUSH,
            ).order_by("name")
        )

        if not cameras:
            self.stderr.write(self.style.ERROR(
                "Nenhuma câmera RTMP_PUSH ativa encontrada.\n"
                "Crie câmeras com connection_mode=rtmp_push e is_active=True."
            ))
            sys.exit(1)

        rtmp_base = self._rtmp_base(options)
        fps       = options["fps"]
        bitrate   = options["bitrate"]
        sink      = None if options["ffmpeg_log"] else subprocess.DEVNULL

        self.stdout.write(self.style.HTTP_INFO(
            f"\nPerfil Intelbras VIP  fps={fps}  res={options['width']}×{options['height']}"
            f"  bitrate={bitrate}  profile={options['profile']}"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"Iniciando {len(cameras)} simuladores  vídeo={video_path.name}"
        ))
        self.stdout.write(self.style.HTTP_INFO("-" * 64))

        procs: list[tuple[Camera, subprocess.Popen]] = []
        for cam in cameras:
            rtmp_url = f"{rtmp_base}/live/{cam.camera_key}"
            cmd = self._build_cmd(video_path, rtmp_url, cam.name, options)
            proc = subprocess.Popen(cmd, stdout=sink, stderr=sink)
            procs.append((cam, proc))
            self.stdout.write(
                f"  [{cam.id:>3}] {cam.name:<30}  → {rtmp_url}"
            )

        self.stdout.write(self.style.HTTP_INFO("-" * 64))
        self.stdout.write(self.style.SUCCESS(
            f"{len(procs)} simuladores ativos. Ctrl+C para encerrar.\n"
        ))

        def _shutdown(signum, frame):
            self.stdout.write("\nEncerrando todos os simuladores...")
            for _, proc in procs:
                proc.terminate()
            for _, proc in procs:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        # Monitor com auto-restart
        while True:
            for i, (cam, proc) in enumerate(procs):
                if proc.poll() is not None:
                    if options["no_loop"]:
                        continue
                    self.stdout.write(self.style.WARNING(
                        f"[{cam.name}] ffmpeg encerrou (código={proc.returncode}), reiniciando..."
                    ))
                    rtmp_url = f"{rtmp_base}/live/{cam.camera_key}"
                    cmd = self._build_cmd(video_path, rtmp_url, cam.name, options)
                    procs[i] = (cam, subprocess.Popen(cmd, stdout=sink, stderr=sink))
            time.sleep(2.0)

    # ── ffmpeg (perfil Intelbras) ─────────────────────────────────────────────

    def _build_cmd(
        self,
        video_path: Path,
        rtmp_url: str,
        camera_name: str,
        options: dict,
    ) -> list:
        fps     = options["fps"]
        width   = options["width"]
        height  = options["height"]
        bitrate = options["bitrate"]
        profile = options["profile"]
        font    = options.get("_font")

        # GOP = I-frame a cada 2 s (padrão Intelbras)
        gop = max(1, int(fps * 2))

        # bufsize = 2× bitrate (CBR buffer Intelbras)
        try:
            bval = float(bitrate.upper().rstrip("MK"))
            bunit = "M" if "M" in bitrate.upper() else "K"
            bufsize = f"{int(bval * 2)}{bunit}"
        except ValueError:
            bufsize = "4M"

        loop_flags = [] if options["no_loop"] else ["-stream_loop", "-1"]

        # Filtros de vídeo
        vf = self._build_vf(width, height, fps, camera_name, font)

        return [
            "ffmpeg",
            "-loglevel", "error",           # suprime avisos internos do ffmpeg
            "-re",                          # velocidade real (simula câmera ao vivo)
            *loop_flags,
            "-i", str(video_path),

            # Vídeo
            "-vf", vf,
            "-r", str(fps),
            "-c:v", "libx264",
            "-profile:v", profile,          # main = padrão Intelbras
            "-level:v", "4.1",              # compatível com todos os players NVR
            "-preset", "veryfast",
            "-tune", "zerolatency",         # baixíssima latência (câmera ao vivo)
            "-b:v", bitrate,                # CBR
            "-maxrate", bitrate,
            "-bufsize", bufsize,
            "-g", str(gop),                 # intervalo de I-frame
            "-keyint_min", str(gop),
            "-sc_threshold", "0",           # sem detecção de cena (CBR estável)
            "-bf", "0",                     # sem B-frames (low-latency, padrão Intelbras)
            "-pix_fmt", "yuv420p",

            # Sem áudio (câmeras LPR)
            "-an",

            # Saída RTMP
            "-f", "flv",
            rtmp_url,
        ]

    def _build_vf(
        self,
        width: int,
        height: int,
        fps: float,
        camera_name: str,
        font: str | None,
    ) -> str:
        """
        Monta a cadeia de filtros de vídeo:
          scale → pad → fps → OSD (se fonte disponível)
        """
        # Scale mantendo aspect ratio + pad para resolução exata (letterbox)
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        )

        parts = [scale, f"fps={fps}"]

        if font:
            # OSD estilo Intelbras: timestamp no canto superior esquerdo,
            # nome da câmera logo abaixo.
            #
            # No Windows, caminhos absolutos com drive letter (C:/) contêm ':',
            # que o parser de filtros do ffmpeg interpreta como separador de opção.
            # Usando caminho relativo (sem drive letter) o problema some.
            # O timestamp usa '.' como separador (HH.MM.SS) para evitar ter que
            # escapar ':' dentro do %{localtime}, que varia entre builds.
            safe_name = camera_name.replace("'", "\\'").replace(":", "\\:")
            font_rel  = os.path.relpath(font).replace("\\", "/")

            ts = (
                f"drawtext=fontfile={font_rel}:"
                r"text='%{localtime\:%Y-%m-%d %H.%M.%S}':"
                "fontsize=24:fontcolor=white:"
                "borderw=2:bordercolor=black:"
                "x=10:y=10"
            )
            name = (
                f"drawtext=fontfile={font_rel}:"
                f"text='{safe_name}':"
                "fontsize=22:fontcolor=white:"
                "borderw=2:bordercolor=black:"
                "x=10:y=42"
            )
            parts += [ts, name]

        return ",".join(parts)

    # ── resolvers ─────────────────────────────────────────────────────────────

    def _resolve_camera(self, options) -> Camera | None:
        camera_key = options.get("camera_key")
        camera_arg = options.get("camera")

        if camera_key:
            try:
                return Camera.objects.get(camera_key=camera_key)
            except Camera.DoesNotExist:
                self.stderr.write(self.style.ERROR(
                    f"Câmera não encontrada: camera_key={camera_key}"
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
                    f"Múltiplas câmeras encontradas para '{camera_arg}':"
                ))
                for cam in qs:
                    self.stdout.write(f"  [{cam.id}] {cam.name}  key={cam.camera_key}")
                self.stderr.write("Use --camera-key para especificar.\n")
                return None
            self.stderr.write(self.style.ERROR(f"Câmera não encontrada: '{camera_arg}'"))
            self._list_cameras()
            return None

        # Auto-seleção: única RTMP_PUSH ativa
        qs = Camera.objects.filter(
            is_active=True,
            connection_mode=Camera.ConnectionMode.RTMP_PUSH,
        )
        if qs.count() == 1:
            cam = qs.first()
            self.stdout.write(self.style.HTTP_INFO(
                f"[auto] Câmera selecionada: {cam.name} (key={cam.camera_key})"
            ))
            return cam
        if qs.count() > 1:
            self.stderr.write(self.style.WARNING(
                "Múltiplas câmeras RTMP_PUSH ativas. "
                "Use --camera-key, --camera ou --all-cameras:\n"
            ))
            for cam in qs:
                self.stdout.write(f"  [{cam.id}] {cam.name}  key={cam.camera_key}")
            return None

        self.stderr.write(self.style.ERROR(
            "\nNenhuma câmera RTMP_PUSH ativa encontrada.\n"
            "Crie uma câmera com connection_mode=rtmp_push e is_active=True.\n"
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
            f"\nArquivo de vídeo não encontrado: {path}\n"
            "\nComo obter um vídeo de teste:\n"
            "  1. Coloque qualquer .mp4 com carros em tests/videos/carros.mp4\n"
            "  2. Ou passe o caminho: --video C:\\Videos\\teste.mp4\n"
            "  3. Download: https://www.pexels.com/search/videos/traffic/\n"
        ))
        return None

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
        key       = camera.camera_key
        font      = options.get("_font")
        osd_status = f"ativo ({Path(font).name})" if font else "desativado (fonte não encontrada)"

        self.stdout.write(self.style.HTTP_INFO("-" * 64))
        self.stdout.write(f"  Câmera  : {camera.name}")
        self.stdout.write(f"  Key     : {key}")
        self.stdout.write(f"  Vídeo   : {video_path.name}  ({'loop' if not options['no_loop'] else '1x'})")
        self.stdout.write(f"  Perfil  : Intelbras VIP — H.264 {options['profile'].upper()} L4.1")
        self.stdout.write(f"  Res     : {options['width']}×{options['height']}  {options['fps']} fps")
        self.stdout.write(f"  Bitrate : {options['bitrate']} CBR  bf=0  gop={max(1,int(options['fps']*2))}")
        self.stdout.write(f"  OSD     : {osd_status}")
        self.stdout.write(f"  Push  → : {rtmp_url}")
        self.stdout.write(f"  RTSP  ← : rtsp://{host}:{rtsp_port}/live/{key}")
        self.stdout.write(f"  HLS   ← : http://{host}:{hls_port}/live/{key}/index.m3u8")
        self.stdout.write(self.style.HTTP_INFO("-" * 64))
        self.stdout.write("Pressione Ctrl+C para encerrar.\n")

    def _list_cameras(self) -> None:
        cameras = Camera.objects.order_by("name")
        if not cameras.exists():
            self.stdout.write(self.style.WARNING("Nenhuma câmera cadastrada no banco."))
            return
        self.stdout.write(self.style.HTTP_INFO(f"\nCâmeras cadastradas ({cameras.count()}):"))
        for cam in cameras:
            active = "[ativa]  " if cam.is_active else "[inativa]"
            self.stdout.write(
                f"  [{cam.id:>3}] {active}  "
                f"{cam.get_connection_mode_display():<14}  "
                f"key={cam.camera_key}  {cam.name}"
            )
        self.stdout.write("")
