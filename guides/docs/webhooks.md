# Webhooks

Webhooks sao cadastrados em:

```text
POST /api/ops/webhooks/
```

Payload de exemplo:

```json
{
  "url": "https://integrador.example.com/lpr",
  "event_type": "plate.read",
  "secret": "trocar-em-producao",
  "is_active": true
}
```

Eventos disponiveis:

- `plate.read`
- `plate.error`
- `task.dead_letter`

Cada entrega envia:

- `X-LPR-Event`: tipo do evento.
- `X-LPR-Signature`: HMAC-SHA256 do corpo no formato `sha256=<digest>`.

O historico fica em:

```text
GET /api/ops/webhook-deliveries/
```

Tambem existe `DEAD_LETTER_WEBHOOK_URL` como alerta simples legado para DLQ.
