# LPR APP

Backend inicial para um sistema LPR/ALPR com Django, DRF, Celery, Postgres e Redis.

## Stack

- Django + Django REST Framework
- Django Unfold no admin, com UI baseada em Tailwind
- Multi-tenant com `Business`, `Tenant` e `tenant_id` nos dados operacionais
- Admin do `Business` pode ver todos os tenants da conta e gerar acessos por tenant
- Celery com filas separadas: `capture`, `ocr`, `reports`, `dead`
- Postgres
- Redis
- Upload seguro com validacao por magic bytes, limite de tamanho e remocao de EXIF
- Health check com verificacao de banco e Redis

## Guia completo

O guia principal de uso, arquitetura, exemplos reais de requisicao, casos de uso e metodologia esta em:

[guides/guide.md](guides/guide.md)

## Rodando localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Em `DEBUG=true`, o modo dev nao precisa de Redis para testar fluxos assincronos:

- `CELERY_DEV_EAGER=true` faz `.delay()` executar dentro do proprio `runserver`.
- `USE_POSTGRES_IN_DEBUG=false` usa SQLite local mesmo sem Postgres.
- O cache usa memoria local quando `USE_REDIS_IN_DEBUG=false`.
- Para ver a mensagem do modo dev, rode:

```powershell
python manage.py runserver_dev
```

Health check:

```text
GET http://localhost:8000/health/
```

Upload:

```text
POST http://localhost:8000/api/plates/upload/
Authorization: Bearer <access-token>
multipart/form-data: camera_id, event_type, image
```

Endpoints administrativos:

```text
GET/POST   /api/cameras/
GET/PATCH  /api/cameras/{id}/
GET        /api/ops/dead-letter/
POST       /api/ops/dead-letter/{id}/reprocess/
GET/POST   /api/ops/webhooks/
GET        /api/ops/webhook-deliveries/
GET/POST   /api/ops/models/
POST       /api/ops/models/{id}/promote/
GET        /api/ops/lgpd/ropt/
GET        /api/ops/lgpd/requests/
GET        /api/ops/lgpd/incidents/
GET        /api/ops/monitoring/
GET/POST   /api/v1/plates/registry/
GET        /api/v1/plates/access-events/
GET        /api/v1/plates/vehicle-presence/current-inside/
GET        /api/v1/plates/alerts/
```

Ingestão pública:

```text
POST /api/v1/ingest/cameras/{camera_key}/events/
POST /api/v1/ingest/gateways/{gateway_key}/events/
POST /api/v1/ingest/gateways/{gateway_key}/heartbeat/
```

Painel operacional:

```text
GET /dashboard/access-events/
```

Eventos de webhook assinados:

- `plate.read`
- `plate.error`
- `task.dead_letter`

Modelos:

```powershell
python manage.py register_model --kind yolo --model-version lpr-v1.pt --uri C:\models\lpr-v1.pt --promote
python manage.py register_model --kind ocr --model-version easyocr-1.7.1 --uri builtin://easyocr-1.7.1 --promote
```

Retencao LGPD:

```powershell
python manage.py purge_old_events --dry-run
python manage.py purge_old_events
```

Gateway local:

```powershell
python -m edge_gateway.gateway --server-url http://localhost:8000 --gateway-key <key> --gateway-token <token>
```

## Docker

```powershell
copy .env.example .env
docker compose up --build
```

Migrations em producao devem ser executadas como passo explicito de deploy, nunca no startup do container.
