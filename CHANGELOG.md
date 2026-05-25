# Changelog

Todas as mudancas relevantes para operadores e manutencao devem ser registradas aqui.

## 0.1.0 - 2026-05-23

- Criada base inicial Django/DRF/Celery.
- Adicionados modelos centrais de camera, evento LPR e falhas em dead-letter.
- Adicionado upload seguro com limite de tamanho, magic bytes e remocao de EXIF.
- Adicionado health check para banco e Redis.
- Adicionadas filas Celery separadas e retry com backoff para OCR.
- Adicionada API administrativa de cameras com senha RTSP criptografada.
- Adicionados webhooks assinados por HMAC e historico de entregas.
- Adicionado endpoint de reprocessamento de dead-letter.
- Adicionado log de auditoria para uploads aceitos, invalidos e limitados por throttle.
- Adicionada ingestao publica por camera e gateway com token individual.
- Adicionados whitelist, blacklist, desconhecidos, eventos de acesso, presenca e alertas.
- Adicionado gateway local com fila SQLite e heartbeat.
- Adicionado Django Unfold no admin, incluindo User, Group e todas as models do projeto.
