# Videos para simulação de câmera

Coloque aqui arquivos `.mp4` para usar com o simulador de câmera.

## Nome padrão

O comando `run_camera_simulator` procura por `videos/carros.mp4` por padrão.
Você pode usar outro arquivo com `--video caminho/do/arquivo.mp4`.

## Como usar o simulador

```bash
# 1. Suba o MediaMTX
python manage.py run_media_server

# 2. Em outro terminal — seleciona câmera RTMP_PUSH ativa automaticamente
python manage.py run_camera_simulator --video videos/carros.mp4

# 3. Especificando a câmera pelo key
python manage.py run_camera_simulator --camera-key a1b2c3d4 --video videos/carros.mp4

# 4. Ver câmeras disponíveis
python manage.py run_camera_simulator --list-cameras
```

## Onde obter vídeos de teste

- https://www.pexels.com/search/videos/traffic/
- https://pixabay.com/videos/search/traffic/
- Qualquer vídeo .mp4 com veículos passando funciona para testar o pipeline.

> **Atenção LGPD**: não use vídeos com placas reais de pessoas reais em ambientes de
> desenvolvimento/teste, a menos que você tenha base legal para isso.
