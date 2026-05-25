# starLPR — Central LPR (Django + Tailwind + Material Tailwind HTML)

Estrutura entregue:

```
Central LPR.html           ← protótipo navegável (preview hi-fi do dashboard)
tailwind.config.js         ← config com withMT() + design tokens
static/
├── css/tailwind.src.css   ← entry do Tailwind (compila para tailwind.css)
└── js/app.js              ← chrome (sidebar toggle, toast, ⌘K, ticker)
templates/
├── _base.html
├── includes/
│   ├── sidebar.html
│   ├── topbar.html
│   ├── _nav_link.html
│   ├── stat_card.html
│   ├── status_badge.html
│   └── alert_card.html
└── lpr/
    ├── dashboard.html       ← página principal “Central LPR”
    ├── events.html
    ├── cameras.html
    ├── gateways.html
    ├── plates.html
    ├── alerts.html
    ├── _cameras_panel.html  ← partial reutilizado no dashboard
    ├── _gateways_panel.html
    └── _plates_tabs.html
```

## Setup mínimo

```bash
npm i -D tailwindcss @material-tailwind/html
npx tailwindcss -c tailwind.config.js -i static/css/tailwind.src.css -o static/css/tailwind.css --watch
```

`settings.py` (trecho):
```python
INSTALLED_APPS = [..., "compressor"]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    "compressor.finders.CompressorFinder",
]
TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]
```

## Convenções do template

- **Slugs de menu ativo**: a view passa `active_module` (`dashboard`, `events`, `cameras`, `gateways`, `whitelist`, `blacklist`, `unknown`, `alerts`, `presence`, `companies`, `tenants`, `users`, `webhooks`, `audit`, `lgpd`, `settings`). O `_nav_link.html` destaca o item.
- **URL names esperadas**: `lpr:dashboard`, `lpr:events`, `lpr:cameras`, `lpr:gateways`, `lpr:plates`, `lpr:alerts`, `lpr:presence`, `lpr:plate-search`, `lpr:plate-detail`, `lpr:plates-import`, `lpr:event-detail`, `lpr:event-correct`, `lpr:event-review`, `lpr:alert-treat`, `lpr:alert-resolve`, `lpr:export`, `tenancy:business`, `tenancy:tenants`, `tenancy:users`, `tenancy:tenant-switch`, `webhooks:list`, `audit:log`, `lgpd:dashboard`, `core:settings`.
- **Mapeamento com os models**
  - `PlateEvent` → linhas da tabela “Eventos recentes”
  - `AccessEvent` → derivação da coluna **Decisão** (`Liberado/Bloqueado/Revisão manual/Erro`)
  - `PlateRegistry` → abas Whitelist/Blacklist/Desconhecidas/Temporárias
  - `Camera`, `Gateway` → painéis de saúde
  - `Alert` → painel lateral + `lpr/alerts.html`
  - `VehiclePresence` → bloco Presença
  - `AuditLog`, `WebhookSubscription`, `WebhookDelivery`, `DeadLetterTask`, `AIModelArtifact` → módulos plataforma
  - `DataProcessingRecord`, `DataSubjectRequest`, `SecurityIncident` → módulo LGPD
- **Decisões/classificações** padronizadas em `includes/status_badge.html` (`kind="allow"|"block"|"unknown"|"review"|"error"|"online"|"offline"|"queue"|"inactive"`).
- **Ambiente** (`environment` em `topbar.html`): `production|staging|homolog`.

## Sem React, sem Alpine

Toda a interação (sidebar colapsável, toast, atalho de busca, ticker) está em `static/js/app.js`. As listas de placa/alerta usam navegação por links querystring (`?list=…`), recarregando server-side — pronto para Django views.
