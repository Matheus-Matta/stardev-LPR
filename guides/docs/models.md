# Modelos de IA

Modelos YOLO/OCR devem ficar fora do Git:

- Volume Docker.
- Bucket S3 ou equivalente.
- DVC quando houver fluxo de treinamento.

## Registrar modelo

```bash
python manage.py register_model --kind yolo --model-version lpr-v1.pt --uri /models/lpr-v1.pt --promote
python manage.py register_model --kind ocr --model-version easyocr-1.7.1 --uri builtin://easyocr-1.7.1 --promote
```

Se `--uri` apontar para arquivo local, o SHA-256 e calculado automaticamente.

## API

```text
GET/POST /api/ops/models/
POST     /api/ops/models/{id}/promote/
```

Ao promover uma versao, as outras versoes do mesmo tipo deixam de estar ativas.

Cada evento salva em `pipeline_metadata`:

- Versao ativa do YOLO.
- Hash do YOLO.
- Versao ativa do OCR.
- Hash do OCR.
- Tempos de execucao.
- Worker que processou.

## Rollback

Promova novamente a versao anterior:

```bash
python manage.py register_model --kind yolo --model-version lpr-v1.pt --uri /models/lpr-v1.pt --promote
```

Registrar mudancas de modelo no `CHANGELOG.md` usando commit `model:`.
