# ПИФ России — открытые данные Банка России

Пайплайн данных и интерактивный дэшборд по паевым инвестиционным фондам (ПИФ)
России. Проект скачивает два открытых набора Банка России, нормализует их в
CSV и строит витрины для дэшборда: динамика рынка, потоки средств, структура
активов, комиссии и доходность фондов для неквалифицированных инвесторов.

> Данные: Банк России (открытые источники). Материал носит информационный
> характер и **не является инвестиционной рекомендацией**. Витрина фондов для
> неквалифицированных инвесторов публикуется ЦБ в тестовом формате.

## Источники

| Файл | Содержимое | Периодичность |
|---|---|---|
| [`opd_PIF_2026.XLSX`](https://cbr.ru/Collection/Collection/File/60830/opd_PIF_2026.XLSX) | Основные показатели деятельности ПИФ: СЧА, активы, обязательства, потоки за месяц | помесячно |
| [`mutual_fund_data.xlsx`](https://cbr.ru/Content/Document/File/193443/%20mutual_fund_data.xlsx) | Витрина ПИФ для неквалифицированных инвесторов: стратегии, комиссии, надбавки/скидки, доходность | помесячно |

URL источников заданы в `config.yaml` и меняются там же (числовой ID в ссылке
ЦБ меняется для новых наборов).

## Быстрый старт

```bash
make install     # venv + зависимости
make download    # скачать XLSX с cbr.ru
make convert     # XLSX → нормализованные CSV
make build       # витрины-агрегаты для дэшборда
make validate    # контроль качества (exit 1 при проблеме)
make run         # дэшборд на http://localhost:8501
```

Обновление данных одной командой (скачивание → конвертация → витрины →
валидация → commit → push; после push облако передеплоит дэшборд):

```bash
make update
```

Тесты: `make test` (парсер комиссий, сборка витрин, smoke-тест всех страниц
дэшборда через Streamlit AppTest).

## Структура

```
config.yaml           URL источников, пути, пороги валидации
schema.json           схема колонок (сопоставление по тексту шапки XLSX)
src/download.py       скачивание (retry, проверка формата)
src/convert.py        XLSX → data/processed/*.csv (+ --make-schema)
src/validate.py       валидация + data/quality/report.md
src/build_datasets.py витрины data/dashboard/*.csv
app/dashboard.py      Streamlit: обзор / потоки / активы / фонды / данные
data/                 processed + dashboard CSV хранятся в репозитории
```

Ключевые витрины: `nav_by_type.csv`, `flows.csv` (притоки/оттоки),
`asset_structure.csv`, `fees_agg.csv` (взвешенные по СЧА комиссии),
`returns_agg.csv`, `funds_merged_latest.csv` (фонды целиком),
`fund_timeseries.csv`.

## Деплой на Streamlit Community Cloud (публичная ссылка)

1. Создайте репозиторий на GitHub и запушьте проект:
   ```bash
   git remote add origin git@github.com:<user>/<repo>.git
   git push -u origin main
   ```
2. Зайдите на [share.streamlit.io](https://share.streamlit.io) → **New app** →
   выберите репозиторий, ветку `main`, файл `app/dashboard.py` → **Deploy**.
3. Готово: постоянная публичная ссылка вида `https://<app>.streamlit.app`.
   Каждый push в `main` автоматически передеплоит приложение.

Дополнительно: GitHub Actions обновляет данные 12-го числа каждого месяца
(`.github/workflows/monthly-update.yml`) и гоняет тесты на каждый push
(`ci.yml`).

## Лицензия

MIT (см. LICENSE). Данные — Банк России, открытые данные.
