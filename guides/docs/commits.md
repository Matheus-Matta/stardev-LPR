# Commits e changelog

Usar Conventional Commits:

- `feat:` nova funcionalidade.
- `fix:` correcao de bug.
- `chore:` manutencao sem impacto funcional.
- `perf:` melhoria de performance.
- `model:` atualizacao de modelo de IA.
- `docs:` documentacao.
- `test:` testes.

Atualizar `CHANGELOG.md` a cada release com:

- Versao.
- Data.
- Mudancas de operador.
- Mudancas de modelo.
- Impacto esperado em acuracia.

Geracao automatica sugerida:

```bash
git cliff --output CHANGELOG.md
```

