# LGPD

## ROPT

O Registro de Operacoes de Tratamento fica em:

```text
GET/POST /api/ops/lgpd/ropt/
```

Campos principais:

- Finalidade do tratamento.
- Base legal.
- Categorias de dados.
- Prazo de retencao.
- Compartilhamento com terceiros.
- Responsavel interno.

## Solicitacoes de titulares

```text
GET/POST /api/ops/lgpd/requests/
```

Registrar pedidos de acesso, correcao, exclusao e oposicao.

## Incidentes

```text
GET/POST /api/ops/lgpd/incidents/
```

Incidentes devem registrar deteccao, dados afetados, mitigacao e prazo de notificacao.

Processo recomendado:

1. Abrir incidente assim que houver ciencia.
2. Avaliar risco aos titulares.
3. Preparar notificacao a ANPD quando aplicavel.
4. Registrar `anpd_notified_at`.
5. Fechar o incidente com notas de mitigacao.

## Retencao

Eventos antigos podem ser removidos com:

```bash
python manage.py purge_old_events --dry-run
python manage.py purge_old_events
```

O prazo padrao e `EVENT_RETENTION_DAYS=90`.
