# Servidor de Midia (MediaMTX)

## O que e

MediaMTX e um servidor de streams de video open-source que funciona como roteador de midia entre as cameras fisicas e o sistema LPR. Em vez do Django precisar falar com cada protocolo de camera diretamente, todas as cameras se conectam ao MediaMTX de formas diferentes e o sistema sempre le pelo mesmo endereco RTSP padronizado.

Repositorio oficial: https://github.com/bluenviron/mediamtx

---

## Por que usamos

Cameras IP nao falam o mesmo protocolo:

- Cameras de seguranca profissionais (Hikvision, Dahua, Intelbras) expoe RTSP — o servidor precisa fazer pull.
- Cameras de acao, doorbells e IoT (Reolink, algumas Wyze, gateways embedded) fazem push RTMP — precisam de um servidor ouvindo.
- Gateways locais (Raspberry Pi, NUC com cameras USB) gerenciam cameras sem IP e fazem push para o servidor central.

Sem o MediaMTX, o Django teria que:
- Manter conexoes TCP abertas para cada camera RTSP (problema com 50+ cameras).
- Implementar servidor RTMP para receber push.
- Reautenticar em queda de rede.
- Tratar reconexao de cada camera individualmente.

Com o MediaMTX, o Django sempre le `rtsp://mediamtx:8554/live/<camera_key>` e nao sabe nem precisa saber qual protocolo a camera usa. O MediaMTX cuida de tudo.

Bonus: o mesmo servidor serve HLS para preview no browser e WebRTC para streaming ao vivo no dashboard — sem codigo adicional.

---

## O que e necessario para funcionar

### Binario do MediaMTX

Baixe em: https://github.com/bluenviron/mediamtx/releases

Windows (instalacao manual):
```powershell
# Cria pasta e baixa
New-Item -ItemType Directory -Force "C:\Users\<seu-usuario>\AppData\Local\mediamtx"
# Baixe o zip da versao mais recente (windows_amd64) e extraia nessa pasta
```

Linux/macOS:
```bash
curl -L https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_v1.18.2_linux_amd64.tar.gz | tar xz
sudo mv mediamtx /usr/local/bin/
```

Docker (sem instalar nada): o `Dockerfile` do projeto ja copia o binario de `bluenviron/mediamtx:latest` na build.

### Dependencias Python (requirements.txt)

```
pyyaml>=6.0    # gera o mediamtx.yml dinamicamente
requests>=2.32  # watcher usa API REST do MediaMTX
```

### ffmpeg (para captura de frames)

O worker de captura usa `ffmpeg` para ler um frame via RTSP.

Linux/macOS:
```bash
sudo apt install ffmpeg   # Debian/Ubuntu
brew install ffmpeg        # macOS
```

Windows (para dev local):
```powershell
winget install Gyan.FFmpeg
# ou baixe de https://ffmpeg.org/download.html e adicione ao PATH
```

Docker: o `Dockerfile` ja instala via `apt-get install ffmpeg`.

---

## Arquitetura completa

```
CAMERAS FISICAS                 MEDIAMTX                  SISTEMA LPR
                                (porta :1935 RTMP)
[Camera RTMP]  --push RTMP-->   recebe stream
[Gateway]      --push RTMP-->   recebe stream
                                                    
[Camera RTSP]  <--pull RTSP--   busca stream
                                
                                (porta :8554 RTSP)  --> [Worker capture] --> ffmpeg
                                                    --> [Dashboard preview]
                                
                                (porta :8888 HLS)   --> [Browser/player]
                                
                                (porta :9997 API)   <-> [CameraWatcher]
                                                        (sincroniza paths
                                                         com o banco)

[Camera HTTP]  --POST /ingest/cameras/<key>/events/--> [Django API] (sem MediaMTX)
```

### Fluxo de captura automatica (RTSP/RTMP -> placa detectada)

```
run_capture_loop (a cada 2s por camera)
  |
  v
capture_camera_frame.delay(camera_id)           [fila Celery: capture]
  |
  v
ffmpeg -i rtsp://mediamtx:8554/live/<camera_key>
  |
  v
create_access_event(camera, image=frame_png)
  |
  +-- PlateEvent criado (status: pending)
  |
  v
process_plate_event.delay(plate_event_id)       [fila Celery: ocr]
  |
  v
run_ocr_pipeline(event)
  |
  v
finalize_access_event()
  |
  +-- classify_plate()  -> whitelist / blacklist / unknown
  +-- create_alerts_for_event()
  +-- dispatch_webhooks("access.event")
  |
  v
AccessEvent salvo no banco
```

### Hot-reload de cameras (sem reiniciar o servidor)

```
Banco de dados (Camera.is_active muda)
  |
  v  poll a cada 10s
CameraWatcher._sync()
  |
  +-- camera nova     -> POST  http://127.0.0.1:9997/v3/config/paths/add/<key>
  +-- camera editada  -> PATCH http://127.0.0.1:9997/v3/config/paths/patch/<key>
  +-- camera inativa  -> DELETE http://127.0.0.1:9997/v3/config/paths/remove/<key>
  
Streams existentes nao sao interrompidos.
```

---

## Modos de conexao de camera

| connection_mode | Quem conecta em quem | Porta usada | Quando usar |
|---|---|---|---|
| `direct_rtsp` | MediaMTX faz pull da camera | 8554 (saida) | Camera com IP proprio e RTSP nativo |
| `rtmp_push` | Camera envia push para MediaMTX | 1935 (entrada) | Camera que so faz push RTMP |
| `gateway` | Gateway local envia push | 1935 (entrada) | Camera sem IP, gerenciada por gateway |
| `push` | Camera envia HTTP para Django | nenhuma | Camera com SDK proprio, sem streaming |

O `camera_key` (UUID hex gerado no cadastro) e o identificador unico em toda a cadeia:
- Path no MediaMTX: `live/<camera_key>`
- URL de leitura: `rtsp://mediamtx:8554/live/<camera_key>`
- Endpoint de ingest: `/api/v1/ingest/cameras/<camera_key>/events/`

---

## Como ativar — passo a passo

### Passo 1: instalar o binario

Siga a secao "O que e necessario para funcionar" acima. No `.env`, aponte o caminho:

```env
MEDIAMTX_BINARY=mediamtx                         # se estiver no PATH
MEDIAMTX_BINARY=C:\...\mediamtx.exe              # caminho absoluto no Windows
MEDIAMTX_BINARY=/usr/local/bin/mediamtx          # caminho absoluto no Linux
```

### Passo 2: configurar as variaveis de ambiente

```env
# Portas (padroes funcionam na maioria dos casos)
MEDIAMTX_RTSP_PORT=8554
MEDIAMTX_RTMP_PORT=1935
MEDIAMTX_HLS_PORT=8888
MEDIAMTX_API_PORT=9997

# Host onde o MediaMTX esta rodando
# dev local: localhost
# docker compose: mediamtx (nome do servico)
MEDIAMTX_HOST=localhost

# Com que frequencia o watcher verifica novas cameras no banco
MEDIAMTX_WATCH_INTERVAL=10

# Com que frequencia o capture loop captura frames de cada camera
CAPTURE_INTERVAL_SECONDS=2
```

### Passo 3: cadastrar uma camera no banco

Pelo admin Django (`/admin/`) ou pela API:

```http
POST /api/v1/cameras/
Authorization: Bearer <token>
Content-Type: application/json

{
  "tenant": 1,
  "name": "Portaria Entrada",
  "connection_mode": "direct_rtsp",
  "host": "192.168.1.50",
  "port": 554,
  "rtsp_path": "/stream1",
  "username": "admin",
  "password": "senha123",
  "direction_default": "entry",
  "is_active": true
}
```

Para camera RTMP Push:

```http
{
  "tenant": 1,
  "name": "Camera Reolink",
  "connection_mode": "rtmp_push",
  "direction_default": "entry",
  "is_active": true
}
```

### Passo 4: subir o servidor de midia

```powershell
python manage.py run_media_server
```

Saida esperada:

```
Cameras no banco: 2
[OK] Config gerado: C:\tmp\mediamtx.yml
--------------------------------------------------------
  RTSP : rtsp://0.0.0.0:8554/live/<camera_key>
  RTMP : rtmp://0.0.0.0:1935/live/<camera_key>
  HLS  : http://0.0.0.0:8888/<camera_key>
  2 camera(s) RTSP Pull - MediaMTX busca da camera
--------------------------------------------------------

Iniciando MediaMTX (mediamtx.exe)...
[watcher] aguardando API do MediaMTX...
INF [RTSP] listener opened on :8554 (TCP/RTSP)
INF [RTMP] listener opened on :1935 (TCP/RTMP)
INF [API]  listener opened on 127.0.0.1:9997 (TCP/HTTP)
[watcher] API do MediaMTX disponivel - hot-reload ativo
[watcher] bootstrap: 2 path(s) ja configurado(s) no MediaMTX
```

### Passo 5: subir o loop de captura (em outro terminal)

```powershell
python manage.py run_capture_loop
```

### Passo 6: subir os workers Celery (em outro terminal)

```powershell
# worker de captura (le tasks do loop)
celery -A config worker -Q capture -c 4 --loglevel=info

# worker de OCR (processa os frames capturados)
celery -A config worker -Q ocr -c 2 --loglevel=info
```

Em modo dev com `CELERY_DEV_EAGER=true` os workers nao sao necessarios — as tasks rodam inline no `run_capture_loop`.

---

## Casos de uso reais

### Caso 1: condominio com cameras IP (RTSP)

Cenario: 4 cameras Hikvision na rede local com IP fixo.

Configuracao de cada camera no banco:
```json
{
  "connection_mode": "direct_rtsp",
  "host": "192.168.1.51",
  "port": 554,
  "rtsp_path": "/Streaming/Channels/101",
  "username": "admin",
  "password": "senha"
}
```

O MediaMTX faz pull das 4 cameras. Os workers capturam frames a cada 2 segundos de cada camera. Cada frame passa pelo OCR, gera um AccessEvent e o dashboard exibe a placa detectada em tempo real.

Verificar se o stream esta chegando:
```bash
# Lista paths ativos com streams conectados
curl http://127.0.0.1:9997/v3/paths/list
```

### Caso 2: camera de acao fazendo push RTMP

Cenario: camera Reolink ou Wyze sem suporte a pull RTSP, so faz push.

1. Cadastra a camera com `connection_mode: rtmp_push`.
2. O `camera_key` gerado e, por exemplo, `a1b2c3d4e5f6`.
3. Configure na camera o destino de stream RTMP:
   ```
   rtmp://<ip-do-servidor>:1935/live/a1b2c3d4e5f6
   ```
4. Quando a camera ligar e comecar a transmitir, o MediaMTX recebe o push.
5. O worker de captura le o stream em `rtsp://localhost:8554/live/a1b2c3d4e5f6`.

### Caso 3: gateway local com camera USB

Cenario: Raspberry Pi com camera USB na portaria de uma fabrica, sem IP proprio para a camera.

O gateway captura frames localmente e envia para o servidor via API HTTP:

```http
POST /api/v1/ingest/gateways/{gateway_key}/events/
X-Gateway-Token: token_do_gateway

{
  "plate": "ABC1D23",
  "confidence": 0.95,
  "direction": "entry",
  "camera_external_id": "portaria_norte"
}
```

Nesse caso, o MediaMTX nao e usado para a captura — o gateway faz o trabalho de leitura. Mas o gateway pode opcionalmente fazer push de video para o MediaMTX para preview no dashboard:
```
rtmp://<servidor>:1935/live/<camera_key>
```

### Caso 4: adicionar camera sem parar o servidor

1. Cadastra a camera nova no admin Django ou via API.
2. Em ate 10 segundos (MEDIAMTX_WATCH_INTERVAL), o log mostra:
   ```
   [watcher] sync  +1 nova(s)  ~0 atualizada(s)  -0 removida(s)
   ```
3. O path `live/<camera_key>` ja esta disponivel no MediaMTX.
4. O loop de captura comeca a capturar frames na proxima iteracao.

Nenhum servico foi reiniciado. Streams das outras cameras continuam ativos.

### Caso 5: desativar camera temporariamente

1. No admin, muda `Camera.is_active = False`.
2. Em ate 10 segundos:
   ```
   [watcher] sync  +0 nova(s)  ~0 atualizada(s)  -1 removida(s)
   ```
3. O path e removido do MediaMTX. Se a camera for DIRECT_RTSP, a conexao com ela e encerrada.
4. O loop de captura para de despachar tasks para essa camera na proxima iteracao.

---

## Verificando o status

### Listar cameras com stream ativo

```bash
curl http://127.0.0.1:9997/v3/paths/list
```

Retorna JSON com cada path, se tem readers (quem esta lendo), se tem source (de onde vem o stream) e estatisticas de bytes.

### Ver paths configurados (incluindo sem stream ativo)

```bash
curl http://127.0.0.1:9997/v3/config/paths/list
```

### Testar stream RTSP manualmente

```bash
# ffplay (parte do ffmpeg)
ffplay rtsp://localhost:8554/live/<camera_key>

# VLC
vlc rtsp://localhost:8554/live/<camera_key>
```

### Testar stream HLS no browser

```
http://localhost:8888/live/<camera_key>/index.m3u8
```

---

## Docker Compose

Para subir tudo junto:

```bash
docker compose up --build
```

Servicos relevantes:

| Servico | O que faz | Portas |
|---|---|---|
| `mediamtx` | Servidor de midia com hot-reload | 8554, 1935, 8888 |
| `capture-loop` | Loop que despacha tasks de captura | - |
| `worker-capture` | Processa tasks de captura (ffmpeg) | - |
| `worker-ocr` | Processa OCR nas imagens capturadas | - |

No compose, a variavel `MEDIAMTX_HOST=mediamtx` e sobrescrita automaticamente no servico `capture-loop` para que os workers saibam onde o MediaMTX esta.

---

## Variaveis de ambiente completas

| Variavel | Padrao | Descricao |
|---|---|---|
| `MEDIAMTX_BINARY` | `mediamtx` | Caminho do binario |
| `MEDIAMTX_CONFIG` | `mediamtx.yml` | Onde gravar o YAML gerado |
| `MEDIAMTX_HOST` | `localhost` | Host para leitura dos streams (dev: localhost, docker: mediamtx) |
| `MEDIAMTX_RTSP_PORT` | `8554` | Porta RTSP de saida |
| `MEDIAMTX_RTMP_PORT` | `1935` | Porta RTMP de entrada (cameras push) |
| `MEDIAMTX_HLS_PORT` | `8888` | Porta HLS para browser |
| `MEDIAMTX_API_PORT` | `9997` | API REST interna (loopback) |
| `MEDIAMTX_LOG_LEVEL` | `info` | debug / info / warn / error |
| `MEDIAMTX_WATCH_INTERVAL` | `10` | Segundos entre verificacoes de novas cameras |
| `CAPTURE_INTERVAL_SECONDS` | `2` | Segundos entre capturas de frame por camera |

---

## Arquivos envolvidos

| Arquivo | Funcao |
|---|---|
| `common/management/commands/run_media_server.py` | Gera config, inicia MediaMTX, roda CameraWatcher |
| `common/management/commands/run_capture_loop.py` | Loop que despacha tasks de captura |
| `cameras/tasks.py` | Task Celery: captura frame via ffmpeg, cria AccessEvent |
| `cameras/models.py` | `Camera.capture_rtsp_url` - URL de leitura via MediaMTX |
| `plates/access.py` | `create_access_event()` - recebe frame e inicia pipeline OCR |
| `plates/tasks.py` | `process_plate_event()` - executa OCR e finaliza evento |
| `plates/services.py` | `run_ocr_pipeline()` - motor de deteccao (stub em dev) |

---

## Problemas comuns

### "Binario nao encontrado"

```
Binario 'mediamtx' nao encontrado.
```

Solucao: instalar o binario e apontar `MEDIAMTX_BINARY` no `.env`.

### "API nao ficou disponivel em 60s"

O watcher nao conseguiu falar com a API do MediaMTX. Causas:

1. Outro processo usando a porta 1935, 8554 ou 8000 (UDP).
   ```powershell
   netstat -an | Select-String "8554|1935|9997"
   ```
2. Instancia anterior do mediamtx.exe ainda ativa.
   ```powershell
   Get-Process mediamtx | Stop-Process -Force
   ```

### "ERR listen udp :8000 bind"

Porta UDP 8000 em conflito. O projeto desabilita UDP por padrao (`rtspTransports: ["tcp"]`). Se isso aparecer, uma instancia antiga do MediaMTX sem essa configuracao ainda esta rodando. Mata o processo e reinicia.

### Frame capturado vazio ou erro de ffmpeg

- Verifique se o stream esta chegando no MediaMTX:
  ```bash
  curl http://127.0.0.1:9997/v3/paths/list
  ```
- Se for camera RTSP, verifique se credenciais e IP estao corretos no cadastro da camera.
- Se for camera RTMP, verifique se a URL configurada na camera esta certa:
  ```
  rtmp://<ip-do-servidor>:1935/live/<camera_key>
  ```
- Teste o stream manualmente com `ffplay` antes de depurar o worker.
