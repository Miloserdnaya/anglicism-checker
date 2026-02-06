# Проверка англицизмов

Скрипт и **веб-сервис** для автоматической проверки слов на англицизмы через Викисловарь и официальные PDF-словари РФ.

## Веб-сервис (рекомендуется)

Сервис скачивает PDF-словари с ruslang.ru и индексирует их локально.

### Запуск локально

```bash
pip install -r requirements.txt
python app.py
```

Откройте http://localhost:8000

### Первый запуск

1. Откройте страницу.
2. Нажмите **«Загрузить и проиндексировать словари»**.
3. Сервис скачает 5 PDF-файлов (~50–150 МБ) с ruslang.ru в папку `data/pdf/`.
4. Построит поисковый индекс — после этого проверка будет учитывать официальные словари.

### API

| Метод | URL | Описание |
|-------|-----|----------|
| GET | / | Веб-интерфейс |
| GET | /api/status | Статус словарей |
| POST | /api/init | Скачать PDF и построить индекс |
| POST | /api/check | `{"words": ["креатив", "скилл"]}` |
| POST | /api/check-url | `{"url": "https://example.ru"}` |

---

## CLI (командная строка)

### 1. Список слов вручную
```bash
python check_anglicisms.py креатив скилл лайв трек ментор
```

### 2. Слова из файла
Создайте файл `words.txt` (по одному слову на строку):
```
креатив
скилл
лайв
индустрия
```

```bash
python check_anglicisms.py -f words.txt
```

### 3. Автоизвлечение с сайта
Скрипт загрузит страницу и найдёт типичные англицизмы:
```bash
python check_anglicisms.py -u https://thecreativity.ru/
```

### 4. Поиск в PDF-словарях (опционально)
Скачайте PDF-словари с [ruslang.ru](https://gramota.ru/biblioteka/spravochniki/ofitsialno-o-russkom-yazyke/normativnye-slovari) в папку `slovari/` и установите PyMuPDF:

```bash
pip install PyMuPDF
python check_anglicisms.py креатив скилл -p slovari/ -o report.md
```

### 5. Сохранить отчёт
```bash
python check_anglicisms.py -f words.txt -o otchet.md
python check_anglicisms.py креатив скилл --csv -o otchet.csv
```

## Источники

- **Викисловарь** — этимология, заимствования (автоматически)
- **Официальные словари** — для финальной проверки вручную или через PDF:
  - [Орфографический](https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/orfograficheskij_slovar.pdf)
  - [Орфоэпический](https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/orfoepicheskij_slovar.pdf)
  - [Словарь иностранных слов](https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/slovar_inostr_slov.pdf)
  - [Толковый](https://ruslang.ru/sites/default/files/doc/normativnyje_slovari/) (2 части)
