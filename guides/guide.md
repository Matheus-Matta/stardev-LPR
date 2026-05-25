# Guia Completo do Sistema LPR/ALPR

Este guia resume como o sistema funciona, como testar localmente e como usar as APIs principais.

Para fluxos praticos por model, com diagramas de estado e exemplos de codigo, veja:

[Guia Pratico por Model](model_workflows.md)

## 1. Visao Geral

O sistema recebe eventos de cameras ou gateways, registra a imagem/evento, executa leitura OCR/LPR quando necessario, classifica a placa e atualiza o estado operacional.

Fluxo principal:

```text
Camera/gateway envia evento
-> sistema valida token
-> salva AccessEvent
-> se vier imagem sem placa, cria PlateEvent
-> Celery processa OCR/LPR
-> sistema classifica whitelist/blacklist/unknown
-> atualiza VehiclePresence
-> gera Alert quando necessario
-> publica webhooks e dados para admin/API/painel
```

## 2. Hierarquia Multi-Tenant

```text
superadmin
  -> ve tudo

Business
  -> conta da administradora/empresa
  -> possui varios Tenants

Tenant
  -> condominio, cliente final, unidade, fabrica ou estacionamento
  -> possui cameras, placas, eventos, alertas e configuracoes
```

Regras de acesso:

- `is_superuser`: ve todos os businesses, tenants e dados.
- `UserProfile.is_admin=true` com `business`: ve todos os dados do business.
- `is_staff=true` com `UserTenantAccess`: acessa o admin, mas so ve tenants vinculados.

Todo dado operacional deve ter `tenant_id`: cameras, gateways, placas, eventos, presenca, alertas, webhooks, auditoria, LGPD e modelos IA.

## 3. Rodar Local Sem Redis/Postgres

O modo local usa SQLite, cache em memoria e Celery eager.

`.env` recomendado:

```env
ENVIRONMENT=development
DEBUG=true
DATABASE_URL=sqlite:///db.sqlite3
USE_POSTGRES_IN_DEBUG=false
USE_REDIS_IN_DEBUG=false
REDIS_REQUIRED=false
CELERY_DEV_EAGER=true
```

Comandos:

```powershell
cd C:\Users\matheus\OneDrive\projetos\LPR_APP
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver_dev
```

Nesse modo, chamadas `.delay()` do Celery rodam dentro do proprio `runserver`, sem worker e sem Redis.

## 4. URLs Principais

```text
Admin:     http://127.0.0.1:8000/admin/
Health:    http://127.0.0.1:8000/health/
Painel:    http://127.0.0.1:8000/dashboard/access-events/
```

Health em modo dev deve retornar Redis como OK simulado e indicar modos:

```json
{
  "status": "ok",
  "checks": {
    "database": true,
    "redis": true,
    "celery": true
  },
  "modes": {
    "cache": "locmem",
    "celery": "eager"
  }
}
```

## 5. Autenticacao

Obter JWT:

```http
POST /api/token/
Content-Type: application/json

{
  "username": "admin",
  "password": "sua_senha"
}
```

Usar token:

```http
Authorization: Bearer eyJ...
```

Logout:

```http
POST /api/token/logout/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "refresh": "eyJ..."
}
```

## 6. Business, Tenant e Acessos

Endpoints:

```http
GET  /api/v1/tenancy/my-businesses/
GET  /api/v1/tenancy/my-tenants/
GET  /api/v1/tenancy/managed-accesses/
POST /api/v1/tenancy/grant-access/
```

Gerar acesso para um cliente de um condominio:

```http
POST /api/v1/tenancy/grant-access/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "business": 1,
  "tenant": 10,
  "role": "viewer",
  "email": "cliente@condominio.com.br"
}
```

Resposta:

```json
{
  "id": 25,
  "username": "cliente@condominio.com.br",
  "email": "cliente@condominio.com.br",
  "business": 1,
  "tenant": 10,
  "role": "viewer",
  "is_active": true,
  "generated_password": "senha_temporaria"
}
```

Para dar acesso a todos os tenants do business, use `tenant: null` com role adequada.

## 7. Cameras

Cadastrar camera:

```http
POST /api/v1/cameras/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "name": "Portaria Entrada 01",
  "connection_mode": "push",
  "direction_default": "entry",
  "location": "Portaria Norte",
  "timezone": "America/Sao_Paulo",
  "is_active": true,
  "rotate_token": true
}
```

Rotacionar token:

```http
POST /api/v1/cameras/1/rotate-token/
Authorization: Bearer eyJ...
```

Resposta:

```json
{
  "camera_key": "abc123",
  "token": "token_visivel_uma_unica_vez"
}
```

## 8. Gateways

Cadastrar gateway:

```http
POST /api/v1/gateways/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "name": "Gateway Portaria",
  "location": "Rede local portaria",
  "is_active": true,
  "rotate_token": true
}
```

Heartbeat:

```http
POST /api/v1/ingest/gateways/{gateway_key}/heartbeat/
X-Gateway-Token: token_do_gateway
Content-Type: application/json

{
  "version": "edge-gateway-0.1",
  "pending_events": 12,
  "cameras_online": 4,
  "cameras_offline": 1
}
```

## 9. Ingestao Direta da Camera

Evento com placa ja lida:

```http
POST /api/v1/ingest/cameras/{camera_key}/events/
X-Camera-Token: token_da_camera
Idempotency-Key: camera-evento-0001
Content-Type: application/json

{
  "event_type": "plate_detected",
  "plate": "ABC1D23",
  "confidence": 0.94,
  "direction": "entry",
  "captured_at": "2026-05-23T10:40:00-03:00"
}
```

Evento com imagem base64:

```http
POST /api/v1/ingest/cameras/{camera_key}/events/
X-Camera-Token: token_da_camera
Idempotency-Key: camera-evento-0002
Content-Type: application/json

{
  "event_type": "plate_detected",
  "direction": "entry",
  "captured_at": "2026-05-23T10:41:00-03:00",
  "image_base64": "/9j/4AAQSkZJRgABAQ..."
}
```

Evento multipart:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/ingest/cameras/{camera_key}/events/" \
  -H "X-Camera-Token: token_da_camera" \
  -H "Idempotency-Key: camera-evento-0003" \
  -F "direction=entry" \
  -F "captured_at=2026-05-23T10:42:00-03:00" \
  -F "image=@placa.jpg"
```

## 10. Placas

Cadastrar whitelist:

```http
POST /api/v1/plates/registry/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "plate": "ABC1D23",
  "list_type": "whitelist",
  "owner_name": "Joao Silva",
  "owner_document": "12345678900",
  "valid_until": "2026-12-31T23:59:59-03:00"
}
```

Cadastrar blacklist:

```http
POST /api/v1/plates/registry/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "plate": "ZZZ9Z99",
  "list_type": "blacklist",
  "block_reason": "Veiculo com restricao interna",
  "risk_level": "high"
}
```

Consultar:

```http
GET /api/v1/plates/registry/?tenant_id=1&list_type=whitelist
Authorization: Bearer eyJ...
```

## 11. Eventos de Acesso

Listar:

```http
GET /api/v1/plates/access-events/?tenant_id=1
Authorization: Bearer eyJ...
```

Filtros:

```http
GET /api/v1/plates/access-events/?plate=ABC1D23
GET /api/v1/plates/access-events/?decision=blocked
GET /api/v1/plates/access-events/?movement_type=entry
GET /api/v1/plates/access-events/?camera=1
```

Corrigir placa:

```http
POST /api/v1/plates/access-events/15/correct-plate/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "plate": "ABC1D23",
  "reason": "Correcao manual apos revisar imagem"
}
```

Alterar decisao:

```http
POST /api/v1/plates/access-events/15/change-decision/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "decision": "allowed",
  "reason": "Liberacao autorizada pela seguranca"
}
```

## 12. Presenca e Alertas

Veiculos dentro:

```http
GET /api/v1/plates/vehicle-presence/current-inside/
Authorization: Bearer eyJ...
```

Alertas:

```http
GET /api/v1/plates/alerts/?tenant_id=1&status=open
Authorization: Bearer eyJ...
```

Resolver alerta:

```http
POST /api/v1/plates/alerts/3/resolve/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "notes": "Seguranca acionada e ocorrencia encerrada"
}
```

## 13. Admin com Unfold

```text
GET /admin/
```

O admin usa Django Unfold. Todas as telas respeitam escopo:

- superadmin ve tudo;
- admin do business ve todos os dados do business;
- staff ve apenas tenants vinculados.

## 14. Webhooks e DLQ

Webhooks:

```http
POST /api/ops/webhooks/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "url": "https://integrador.example.com/lpr",
  "event_type": "access.event",
  "secret": "segredo-do-integrador",
  "is_active": true
}
```

Dead letter:

```http
GET  /api/ops/dead-letter/
POST /api/ops/dead-letter/1/reprocess/
```

## 15. Metodo de Projeto

Principios:

- API first.
- Multi-tenant por padrao.
- Seguranca por padrao: tokens com hash, JWT curto, refresh blacklist e logs mascarados.
- Rastreabilidade: auditoria, idempotencia e DLQ.
- Operacao realista: admin, dashboard, alertas, webhooks e monitoramento.
- LGPD by design: retencao, ROPT, incidentes e solicitacoes.

Validacao antes de finalizar:

```bash
ruff check .
python manage.py check
python manage.py makemigrations --dry-run --check
pytest --tb=short
```

## 16. Guia de Uso por Model

Esta secao mostra para que serve cada model, quando usar, campos importantes e exemplos reais.

### Business

Representa a conta principal do cliente do sistema. Exemplo: uma administradora, empresa de seguranca ou operador SaaS.

Campos principais:

- `name`: nome comercial.
- `legal_name`: razao social.
- `document`: CNPJ/CPF/documento.
- `is_active`: controla se a conta esta ativa.

Uso:

```http
POST /api/v1/tenancy/businesses/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "name": "Portarias Inteligentes LTDA",
  "legal_name": "Portarias Inteligentes LTDA",
  "document": "12345678000199",
  "is_active": true
}
```

No admin, o superadmin gerencia todos os businesses. Um admin de business visualiza apenas o proprio business.

### Tenant

Representa o cliente/unidade dentro de um business. Exemplo: cada condominio, fabrica, estacionamento ou unidade operacional.

Campos principais:

- `business`: business dono do tenant.
- `name`: nome do tenant.
- `slug`: identificador unico.
- `document`: documento do cliente/unidade.
- `location`: endereco/local.
- `timezone`: fuso local.
- `is_active`: controla operacao.

Uso:

```http
POST /api/v1/tenancy/tenants/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "business": 1,
  "name": "Condominio Jardim Azul",
  "slug": "condominio-jardim-azul",
  "location": "Rua A, 100",
  "timezone": "America/Sao_Paulo",
  "is_active": true
}
```

Use `X-Tenant-ID` ou `tenant_id` nos endpoints operacionais para selecionar o tenant.

### UserProfile

Extensao do usuario Django para definir admin de business.

Campos principais:

- `user`: usuario Django.
- `business`: business administrado.
- `is_admin`: quando `true`, usuario ve todos os tenants do business.

Uso:

```text
Admin Django -> Usuarios -> abrir usuario -> User profile
```

Exemplo real: o usuario da administradora `ana@admin.com` recebe `UserProfile.is_admin=true` e `business=Portarias Inteligentes LTDA`. Ela enxerga todos os condominios desse business e pode gerar acesso para usuarios de cada tenant.

### UserTenantAccess

Controla quais usuarios acessam quais tenants ou um business inteiro.

Campos principais:

- `user`: usuario autorizado.
- `business`: business do acesso.
- `tenant`: tenant especifico; `null` significa todos os tenants do business.
- `role`: `owner`, `admin`, `operator`, `viewer`.
- `is_active`: ativa/desativa o acesso.

Uso para usuario de um condominio:

```http
POST /api/v1/tenancy/grant-access/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "business": 1,
  "tenant": 10,
  "role": "viewer",
  "email": "cliente@condominio.com.br"
}
```

Uso para admin do business por acesso:

```json
{
  "business": 1,
  "tenant": null,
  "role": "admin",
  "email": "gestor@administradora.com.br"
}
```

### Camera

Representa uma camera fisica ou origem de eventos.

Campos principais:

- `tenant`: tenant dono da camera.
- `name`: nome da camera.
- `camera_key`: identificador publico usado na ingestao.
- `connection_mode`: `direct_rtsp`, `push` ou `gateway`.
- `direction_default`: `entry`, `exit` ou `unknown`.
- `gateway`: gateway vinculado, quando aplicavel.
- `host`, `port`, `rtsp_path`, `username`, `password_encrypted`: dados RTSP.
- `ingest_token_hash`: hash do token de ingestao.
- `timezone`: fuso local.

Uso:

```http
POST /api/v1/cameras/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "name": "Portaria Entrada",
  "connection_mode": "push",
  "direction_default": "entry",
  "location": "Entrada principal",
  "timezone": "America/Sao_Paulo",
  "rotate_token": true
}
```

Depois configure a camera para enviar para:

```text
POST /api/v1/ingest/cameras/{camera_key}/events/
Header: X-Camera-Token
```

### Gateway

Representa o coletor local instalado na rede do cliente.

Campos principais:

- `tenant`: tenant dono do gateway.
- `gateway_key`: identificador publico.
- `token_hash`: hash do token.
- `status`: `unknown`, `online`, `offline`.
- `pending_events`: quantidade de eventos locais pendentes.
- `cameras_online`, `cameras_offline`: saude local.
- `version`: versao do agente.

Uso:

```http
POST /api/v1/gateways/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "name": "Gateway Portaria",
  "location": "Rede local da portaria",
  "rotate_token": true
}
```

Heartbeat:

```http
POST /api/v1/ingest/gateways/{gateway_key}/heartbeat/
X-Gateway-Token: token_do_gateway
Content-Type: application/json

{
  "version": "edge-gateway-0.1",
  "pending_events": 0,
  "cameras_online": 4,
  "cameras_offline": 0
}
```

### PlateEvent

Evento bruto de leitura de placa/imagem. Normalmente e criado quando chega imagem sem placa lida.

Campos principais:

- `camera`: camera origem.
- `tenant`: tenant do evento.
- `event_type`: `entry`, `exit`, `unknown`.
- `image`: imagem enviada.
- `captured_at`: horario de captura.
- `plate_text`: placa lida.
- `confidence`: confianca da leitura.
- `status`: `pending`, `processing`, `completed`, `error`.
- `raw_payload`: payload original.
- `pipeline_metadata`: metadados do processamento.

Uso:

```http
GET /api/v1/plates/events/?tenant_id=1
Authorization: Bearer eyJ...
```

Em dev/test, imagens com nome `plate_KNI4F64.png` sao lidas como `KNI4F64` pelo stub deterministico. Em producao, essa model deve receber resultado do motor LPR/OCR real.

### PlateRegistry

Cadastro de placas do tenant.

Campos principais:

- `tenant`: tenant dono da placa.
- `plate`: texto informado.
- `normalized_plate`: placa normalizada.
- `list_type`: `whitelist`, `blacklist`, `unknown`.
- `status`: `active`, `inactive`, `ignored`.
- `owner_name`, `owner_document`: dados do dono.
- `valid_from`, `valid_until`: janela de validade.
- `block_reason`, `risk_level`: usados em blacklist.

Uso whitelist:

```http
POST /api/v1/plates/registry/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "plate": "ABC1D23",
  "list_type": "whitelist",
  "owner_name": "Joao Silva",
  "valid_until": "2026-12-31T23:59:59-03:00"
}
```

Uso blacklist:

```http
POST /api/v1/plates/registry/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "plate": "ZZZ9Z99",
  "list_type": "blacklist",
  "block_reason": "Restricao interna",
  "risk_level": "high"
}
```

### AccessEvent

Evento operacional de acesso. E a model central para entrada/saida, decisao e auditoria da passagem.

Campos principais:

- `event_uuid`: identificador unico.
- `tenant`: tenant.
- `camera`, `gateway`: origem.
- `plate_event`: leitura bruta associada, quando houve imagem/OCR.
- `plate_registry`: cadastro usado na decisao.
- `normalized_plate`: placa normalizada.
- `decision`: `allowed`, `blocked`, `unknown`, `manual_review`, `error`.
- `movement_type`: `entry`, `exit`, `unknown`.
- `captured_at`, `received_at`, `processed_at`: horarios.
- `idempotency_key`: evita duplicidade.

Uso:

```http
GET /api/v1/plates/access-events/?tenant_id=1&plate=ABC1D23
Authorization: Bearer eyJ...
```

Correcao manual:

```http
POST /api/v1/plates/access-events/15/correct-plate/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "plate": "ABC1D23",
  "reason": "Correcao visual da imagem"
}
```

### VehiclePresence

Estado atual de cada veiculo no tenant.

Campos principais:

- `tenant`: tenant.
- `normalized_plate`: placa.
- `current_status`: `inside`, `outside`, `inconsistent`, `unknown`.
- `last_entry_event`, `last_exit_event`: ultimos eventos.
- `entered_at`, `exited_at`, `last_seen_at`: horarios.
- `location`: local da ultima leitura.
- `inconsistency_reason`: motivo de inconsistencias.

Uso:

```http
GET /api/v1/plates/vehicle-presence/current-inside/?tenant_id=1
Authorization: Bearer eyJ...
```

Correcao manual:

```http
POST /api/v1/plates/vehicle-presence/8/manual-correction/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "current_status": "outside",
  "reason": "Saida confirmada pela portaria"
}
```

### Alert

Alerta operacional gerado por eventos importantes.

Campos principais:

- `tenant`: tenant.
- `alert_type`: `blacklist_detected`, `unknown_plate_detected`, `manual_review_required`, `gateway_offline`, `camera_offline`, `duplicate_entry`, `exit_without_entry`.
- `severity`: `info`, `warning`, `critical`.
- `status`: `open`, `resolved`.
- `access_event`, `camera`, `gateway`: contexto.
- `plate`: placa relacionada.
- `message`, `notes`: texto operacional.
- `resolved_by`, `resolved_at`: fechamento.

Uso:

```http
GET /api/v1/plates/alerts/?tenant_id=1&status=open
Authorization: Bearer eyJ...
```

Resolver:

```http
POST /api/v1/plates/alerts/3/resolve/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "notes": "Ocorrencia encerrada pela seguranca"
}
```

### DeadLetterTask

Registra falhas definitivas de tarefas assíncronas, como OCR que excedeu tentativas.

Campos principais:

- `tenant`: tenant relacionado, quando houver.
- `task_name`, `task_id`: tarefa Celery.
- `queue`: fila.
- `payload`: dados para reprocessamento.
- `exception_class`, `exception_message`, `traceback`: erro.
- `retries`: tentativas.
- `status`: `pending`, `reprocessed`, `ignored`.

Uso:

```http
GET /api/ops/dead-letter/?tenant_id=1
Authorization: Bearer eyJ...
```

Reprocessar:

```http
POST /api/ops/dead-letter/1/reprocess/
Authorization: Bearer eyJ...
```

### AuditLog

Registro de auditoria de acoes importantes.

Campos principais:

- `tenant`: tenant.
- `action`: nome da acao.
- `user`: usuario.
- `ip_address`, `path`: origem.
- `entity_type`, `entity_id`: entidade afetada.
- `old_value`, `new_value`: antes/depois.
- `reason`, `metadata`: contexto.

Uso:

```text
Criado automaticamente por operacoes como rotacao de token, upload invalido,
correcao de placa, mudanca de decisao e inativacao de cadastro.
```

No admin, use filtros por tenant, action e data para investigacao.

### WebhookSubscription

Configura para onde enviar eventos externos.

Campos principais:

- `tenant`: tenant.
- `url`: destino.
- `event_type`: `plate.read`, `plate.error`, `access.event`, `task.dead_letter`.
- `secret_encrypted`: segredo para assinatura.
- `is_active`: ativa/desativa.

Uso:

```http
POST /api/ops/webhooks/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "url": "https://integrador.example.com/lpr",
  "event_type": "access.event",
  "secret": "segredo-do-integrador",
  "is_active": true
}
```

### WebhookDelivery

Historico de tentativas de entrega de webhooks.

Campos principais:

- `subscription`: webhook configurado.
- `tenant`: tenant.
- `event_type`: tipo do evento.
- `payload`: payload enviado.
- `status`: `pending`, `success`, `failed`.
- `response_status_code`, `response_body`, `error_message`: resposta do destino.
- `attempts`: tentativas.
- `delivered_at`: entrega.

Uso:

```http
GET /api/ops/webhook-deliveries/?tenant_id=1
Authorization: Bearer eyJ...
```

Use para diagnosticar integracoes externas fora do ar ou retornando erro.

### AIModelArtifact

Controle de modelos de IA registrados no sistema.

Campos principais:

- `tenant`: tenant, quando modelo for especifico.
- `kind`: `yolo` ou `ocr`.
- `version`: versao.
- `storage_uri`: caminho/local do artefato.
- `file_sha256`: hash.
- `baseline_metrics`: metricas.
- `is_active`: modelo promovido.
- `promoted_at`: data da promocao.

Uso via comando:

```powershell
python manage.py register_model --kind yolo --model-version lpr-v1.pt --uri /models/lpr-v1.pt --promote
python manage.py register_model --kind ocr --model-version easyocr-1.7.1 --uri builtin://easyocr-1.7.1 --promote
```

Uso via API:

```http
POST /api/ops/models/1/promote/
Authorization: Bearer eyJ...
```

### DataProcessingRecord

ROPT/LGPD: registro das atividades de tratamento de dados.

Campos principais:

- `tenant`: tenant.
- `name`: nome do processo.
- `purpose`: finalidade.
- `legal_basis`: base legal.
- `data_categories`: categorias de dados.
- `retention_days`: retencao.
- `third_party_sharing`: compartilhamento.
- `owner`: responsavel.
- `is_active`: ativo.

Uso:

```http
POST /api/ops/lgpd/ropt/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "name": "Controle de acesso por placa",
  "purpose": "Controle de entrada e saida do condominio",
  "legal_basis": "Legitimo interesse e seguranca",
  "data_categories": ["placa", "imagem", "horario", "local"],
  "retention_days": 90,
  "owner": "Administracao"
}
```

### DataSubjectRequest

Solicitacao de titular LGPD.

Campos principais:

- `tenant`: tenant.
- `request_type`: `access`, `correction`, `deletion`, `objection`.
- `requester_name`, `requester_contact`: titular.
- `plate_text`: placa relacionada.
- `status`: `open`, `in_progress`, `completed`, `rejected`.
- `response_notes`: resposta.
- `due_at`, `completed_at`: prazos.

Uso:

```http
POST /api/ops/lgpd/requests/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "request_type": "access",
  "requester_name": "Joao Silva",
  "requester_contact": "joao@example.com",
  "plate_text": "ABC1D23",
  "status": "open"
}
```

### SecurityIncident

Incidente de seguranca/LGPD.

Campos principais:

- `tenant`: tenant.
- `title`: titulo.
- `description`: descricao.
- `status`: `open`, `investigating`, `notified`, `closed`.
- `detected_at`: deteccao.
- `anpd_due_at`, `anpd_notified_at`: prazos ANPD.
- `affected_data`: dados afetados.
- `mitigation_notes`: medidas.

Uso:

```http
POST /api/ops/lgpd/incidents/
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "tenant": 1,
  "title": "Exposicao indevida de imagens",
  "description": "Link externo acessivel sem autenticacao",
  "status": "open",
  "detected_at": "2026-05-23T14:00:00-03:00",
  "affected_data": ["imagem", "placa", "horario"]
}
```

Use esta model para acompanhar investigacao, notificacao e encerramento.
