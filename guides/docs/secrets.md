# Secrets

## Politica inicial

- Nunca versionar `.env` de producao.
- Rotacionar `SECRET_KEY`, senha do banco, senha do Redis e credenciais de cameras a cada 90 dias ou quando houver suspeita de vazamento.
- Em producao, preferir variaveis de ambiente do orquestrador ou um cofre de secrets.
- URLs RTSP completas nao devem ser registradas em logs.
- Senhas de cameras ficam criptografadas em repouso no campo `password_encrypted`.
- Logs passam pelo filtro `SecretMaskingFilter`.
- Em Sentry ou ferramenta equivalente, configurar `before_send` para aplicar a mesma regra de mascaramento antes do envio.

## Rotacao

1. Criar novo secret no cofre ou orquestrador.
2. Fazer deploy em staging e validar `/health/`.
3. Fazer deploy em producao sem gravar o secret em arquivo versionado.
4. Revogar o secret antigo apos confirmar que os workers reiniciaram.
5. Registrar a troca no log operacional.

## Variaveis sensiveis

- `SECRET_KEY`
- `POSTGRES_PASSWORD`
- `REDIS_URL`, quando autenticado
- `FIELD_ENCRYPTION_KEY`
- Credenciais RTSP das cameras
- Credenciais de email ou webhook externo
