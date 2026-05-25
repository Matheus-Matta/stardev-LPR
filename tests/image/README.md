# tests/image/

Imagens de placa usadas nos testes automatizados (pytest).

## Formato e nomenclatura

```
plate_<PLACA>.<ext>
```

| Campo   | Detalhe                                                    |
|---------|------------------------------------------------------------|
| `PLACA` | Número da placa em maiúsculas, sem traço (ex.: `ABC1234`) |
| `<ext>` | `png` ou `jpg` — PNG preferido (sem artefatos de compressão) |

Exemplos válidos:

```
plate_ABC1234.png
plate_KNI4F64.png
plate_KWX2979.jpg
```

## Como os testes usam essas imagens

Os testes de OCR/ingest (`test_image_plate_reading.py`, `test_ingest_api.py`) carregam
o arquivo, inferem a placa esperada pelo nome e verificam se o pipeline retorna o
mesmo valor.

```python
# exemplo de uso nos testes
image_path = Path("tests/image/plate_ABC1234.png")
expected_plate = "ABC1234"   # extraído do nome do arquivo
```

## Por que nao estao no git

Arquivos de imagem com placas reais podem conter dados pessoais (LGPD).
Eles ficam fora do repositório e devem ser gerados ou obtidos localmente.

Para criar uma imagem de teste sem placa real, use qualquer ferramenta de
edição de imagem ou gere programaticamente com Pillow:

```python
from PIL import Image, ImageDraw, ImageFont
img = Image.new("RGB", (520, 110), color=(255, 255, 255))
draw = ImageDraw.Draw(img)
draw.text((20, 20), "ABC-1234", fill=(0, 0, 0))
img.save("tests/image/plate_ABC1234.png")
```
