# Staging

Staging deve ser permanente e separado de producao.

## Regras

- Usar `.env.staging`, nunca `.env` de producao.
- Usar dados sinteticos ou anonimizados.
- Testar toda migration em staging antes de producao.
- Validar troca de modelo em staging antes de promover em producao.
- Produção só recebe deploy depois de staging estar validado.

## Execucao

```bash
cp .env.staging.example .env.staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.staging.yml run --rm web python manage.py migrate --plan
docker compose -f docker-compose.yml -f docker-compose.staging.yml run --rm web python manage.py migrate
```

