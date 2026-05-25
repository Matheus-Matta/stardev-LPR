# Ingestao de eventos

## Camera direta

```http
POST /api/v1/ingest/cameras/{camera_key}/events/
X-Camera-Token: <token>
Idempotency-Key: <id-unico>
```

Payload JSON:

```json
{
  "event_type": "plate_detected",
  "plate": "ABC1D23",
  "confidence": 0.94,
  "direction": "entry",
  "captured_at": "2026-05-23T10:40:00-03:00",
  "camera_external_id": "portaria_entrada_01"
}
```

Tambem aceita:

- `image_base64` em JSON.
- `image` em `multipart/form-data`.

Se a placa nao vier no payload e houver imagem, o evento e enviado para OCR.

## Gateway

```http
POST /api/v1/ingest/gateways/{gateway_key}/events/
X-Gateway-Token: <token>
Idempotency-Key: <id-unico>
```

Heartbeat:

```http
POST /api/v1/ingest/gateways/{gateway_key}/heartbeat/
X-Gateway-Token: <token>
```

```json
{
  "version": "edge-gateway-0.1",
  "pending_events": 12,
  "cameras_online": 4,
  "cameras_offline": 1
}
```

## Tokens

Tokens sao retornados uma unica vez na criacao/rotacao.

```http
POST /api/v1/cameras/{id}/rotate-token/
POST /api/v1/gateways/{id}/rotate-token/
```

O banco guarda apenas hash HMAC do token.

