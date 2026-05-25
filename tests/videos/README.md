# tests/videos/

Arquivos de video usados pelo simulador de camera (`run_camera_simulator`).

## Nome padrao

O comando procura por `tests/videos/carros.mp4` por padrao.
Use `--video` para apontar outro arquivo.

## Como usar

```bash
# Suba o MediaMTX em um terminal
python manage.py run_media_server

# Em outro terminal — seleciona automaticamente a camera RTMP_PUSH ativa
python manage.py run_camera_simulator

# Especificando camera e video
python manage.py run_camera_simulator --camera-key a1b2c3d4 --video tests/videos/carros.mp4

# Ver cameras disponiveis
python manage.py run_camera_simulator --list-cameras
```

## Via Docker Compose

```bash
# Defina o camera_key no .env
echo "SIMULATOR_CAMERA_KEY=a1b2c3d4" >> .env

docker compose --profile simulator up camera-simulator
```

## Por que nao esta no git

Arquivos de video sao grandes e podem conter imagens de pessoas/veiculos (LGPD).
Coloque seu proprio `.mp4` com veiculos passando aqui antes de rodar o simulador.

Fontes de videos de trafego sem licenca restritiva:
- https://www.pexels.com/search/videos/traffic/
- https://pixabay.com/videos/search/traffic/
