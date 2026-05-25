# Deploy

## Migracoes

Em producao, nao execute `python manage.py migrate` no startup do container.

Fluxo recomendado:

```bash
pg_dump -U lpr_user lpr_db > backup_pre_migration.sql
docker compose run --rm web python manage.py migrate --plan
docker compose run --rm web python manage.py migrate
docker compose up -d --no-deps web worker-ocr worker-capture worker-reports worker-dead
```

Toda migration em tabelas grandes deve ser validada antes em staging com volume de dados proximo ao real.

## Zero downtime

- Evitar alteracoes destrutivas em uma unica migration.
- Separar deploys em fases: adicionar coluna nullable, preencher dados em background, depois tornar obrigatoria.
- Avaliar `django-pg-zero-downtime-migrations` antes de alteracoes em tabelas grandes.
- Documentar rollback de cada migration no pull request.
- Fazer squash periodico de migrations antigas depois de releases estaveis.
