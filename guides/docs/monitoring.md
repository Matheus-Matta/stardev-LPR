# Monitoramento

## Alertas minimos

| Metrica | Limiar | Severidade |
|---|---:|---|
| Fila OCR pendente | > 50 tarefas | alerta |
| CPU | > 85% por 5 minutos | alerta |
| Disco | > 80% | alerta |
| Worker offline | > 2 minutos | critico |
| Erro de OCR | > 20% na ultima hora | alerta |
| Health check | `/health/` sem 200 | critico |

## Filas

Monitorar separadamente:

- `capture`
- `ocr`
- `reports`
- `dead`

O dashboard deve separar metricas de OCR das metricas de infraestrutura.

Resumo operacional:

```text
GET /api/ops/monitoring/
```
