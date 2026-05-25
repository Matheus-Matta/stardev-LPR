# Gateway local

O gateway local atende cameras sem IP publico. Ele roda na rede do cliente, armazena eventos em SQLite e reenvia quando a internet volta.

## Enfileirar evento

```bash
python -m edge_gateway.enqueue_event --payload '{"plate":"ABC1D23","direction":"entry","camera_external_id":"portaria_entrada_01"}'
```

## Sincronizar com servidor

```bash
python -m edge_gateway.gateway \
  --server-url https://lpr.seudominio.com.br \
  --gateway-key <gateway_key> \
  --gateway-token <gateway_token> \
  --queue-db gateway_queue.sqlite3
```

O gateway envia:

- Eventos pendentes para `/api/v1/ingest/gateways/{gateway_key}/events/`.
- Heartbeat para `/api/v1/ingest/gateways/{gateway_key}/heartbeat/`.
- `Idempotency-Key` para evitar duplicidade.
- `pending_events` no heartbeat.

