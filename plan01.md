# ТЗ plan01: переход рыночных данных с CoinGecko на FreeCryptoAPI

**Версия:** 1.0  
**Область:** price / market cap / volume (замена `CoinGecko /market_chart` на прямой API FreeCryptoAPI).

---

## 1. Цель

Перестроить источник рыночных данных:

| Было | Станет |
|------|--------|
| CoinGecko `/market_chart` | FreeCryptoAPI: **price**, **market cap**, **volume** напрямую |

---

## 2. Область изменений

Затрагиваются:

- модуль загрузки данных (**data source / loader**);
- формат хранения данных;
- расчёт ончейн-прокси (MVRV, NUPL, SOPR), если они опираются на те же ряды;
- кэширование и история.

---

## 3. Новый источник данных

### 3.1. Контракт ответа (логика)

FreeCryptoAPI возвращает структуру вида:

```json
{
  "symbol": "BTC",
  "price": 67000,
  "market_cap": 1300000000000,
  "volume_24h": 25000000000,
  "timestamp": 1710000000
}
```

### 3.2. Модуль загрузчика

Создать модуль (путь в репозитории согласовать с текущей структурой пакета; ориентир ниже):

`data_sources/freecrypto.py` (или `bit_trend/data/freecrypto.py` — единообразно с остальными источниками).

```python
class FreeCryptoDataSource:
    def get_current(self, symbol: str) -> dict:
        ...

    def get_history(self, symbol: str, days: int) -> pd.DataFrame:
        ...
```

**Обязательно:** `get_history` возвращает колонки, совместимые с потребителями (timestamp, price, market_cap, volume минимум).

---

## 4. Исторические данные (ключевой риск)

**Проблема:** FreeCryptoAPI может **не** давать полноценную историю как CoinGecko, а только **current** и/или **ограниченную** историю.

### 4.1. Гибридная стратегия

| Вариант | Условие | Действие |
|---------|---------|----------|
| **A** | Есть history API у провайдера | Использовать напрямую в `get_history` |
| **B** | Нет полноценной истории | Локальное накопление снимков |

**Вариант B — ежедневный (или чаще) сбор:**

```python
def collect_daily_snapshot():
    data = api.get_current("BTC")
    save_to_db(data)
```

**Расписание:** cron / планировщик — минимум **1 раз в день** (при необходимости чаще для TTL/UI).

---

## 5. Формат хранения (обновить)

Нормализованная таблица для истории рынка:

```sql
CREATE TABLE market_data (
    timestamp TEXT PRIMARY KEY,
    symbol TEXT,
    price REAL,
    market_cap REAL,
    volume REAL,
    source TEXT
);
```

- `timestamp` — UTC, в коде зафиксировано форматирование **ISO 8601 UTC** (`bit_trend/data/storage.py`: `_normalize_market_timestamp`; входящий Unix `int` приводится к тому же виду).
- `source` — `freecrypto`, `binance`, `coingecko` и т.д. для отладки и сверки.

**Реализация:** создание таблицы и миграция со схемы `PRIMARY KEY (timestamp, symbol)` на ключ только по `timestamp` выполняются в `init_db()` → `_migrate_market_data_to_plan01` (при совпадении `timestamp` оставляется строка с большим `rowid`).

---

## 6. Маппинг полей

| FreeCryptoAPI | В системе / БД |
|---------------|----------------|
| `price` | `price` |
| `market_cap` | `market_cap` |
| `volume_24h` | `volume` |

Дополнительно сохранять `symbol` и метку `source`.

**Реализовано:** константа `FREECRYPTO_FIELD_MAP` и разбор в `bit_trend/data/freecrypto.py` (`_normalize_current_row`, история — `volume_24h` / `volume` в `_history_json_to_df`).

---

## 7. Влияние на метрики

### 7.1. Без изменений логики (ожидаемо)

- **MVRV**, **NUPL**, **SOPR** (если считаются как прокси от тех же входных рядов) — **алгоритм не менять**, меняется только источник цены/капа/объёма при условии эквивалентности семантики полей.

**Реализовано:** зафиксировано в модуле `bit_trend/data/onchain.py` (докстринг).

### 7.2. Sanity-check после загрузки

```python
assert price > 0
assert market_cap > 0
assert volume >= 0
```

При нарушении — логирование, fallback (см. §9), не писать битую строку в `market_data` без пометки.

**Реализовано:** `sanity_check_market_row` в `bit_trend/data/market_source.py` (цепочка `get_market_current_with_fallback`); `save_market_snapshot` в `storage.py` повторно отсекает невалидные строки (кап необязателен только для `source=binance`).

---

## 8. Абстракция источников (обязательно)

Чтобы смена провайдера не требовала переписывания pipeline:

```python
from abc import ABC, abstractmethod

class MarketDataSource(ABC):
    @abstractmethod
    def get_current(self, symbol: str):
        ...

    @abstractmethod
    def get_history(self, symbol: str, days: int):
        ...
```

**Реализации:**

| Класс | Назначение |
|-------|------------|
| `CoinGeckoDataSource` | legacy / сверка |
| `FreeCryptoDataSource` | основной |
| `BinanceDataSource` | fallback (цена/объём по возможности; кап — уточнить в реализации) |

Фабрика или DI по конфигу выбирает primary + fallback chain.

**Реализовано:** `MarketDataSource` и `get_current` / `get_history` в `bit_trend/data/market_source.py`; реализации `FreeCryptoDataSource`, `CoinGeckoMarketDataSource` (**alias** `CoinGeckoDataSource`), `BinanceMarketDataSource` (**alias** `BinanceDataSource`); реестр и порядок — `_source_cls_map()` + env (`MARKET_DATA_PRIMARY`, `MARKET_DATA_FALLBACK`); фабрика цепочки экземпляров — `get_market_source_chain()`; потребление в пайплайне — `get_market_current_with_fallback`, `build_market_history`, `collect_daily_snapshot`.

---

## 9. Fallback-логика

Если FreeCryptoAPI недоступен (ошибка сети, 5xx, невалидный JSON):

```python
try:
    data = freecrypto.get_current("BTC")
except Exception:
    data = binance.get_current("BTC")
```

Дополнительно: **retry** с backoff, circuit breaker по желанию (согласовать с `upgrade_plan` E1).

**Реализовано:** `get_market_current_with_fallback` в `bit_trend/data/market_source.py` — цепочка источников; на каждый источник до `MARKET_SOURCE_MAX_ATTEMPTS` попыток при **транзиентных** ошибках (сеть, HTTP 5xx, `requests` exceptions), backoff `MARKET_SOURCE_RETRY_BASE_SEC`; опционально `MARKET_CIRCUIT_BREAKER=true`, порог `MARKET_CB_FAILURE_THRESHOLD`, окно `MARKET_CB_OPEN_SEC`. Ретраи HTTP уже в `http_client.py` (E1).

---

## 10. Производительность

| Требование | Целевое значение |
|------------|------------------|
| Латентность ответа пользователю / пайплайну | **< 500 ms** (горячий путь с кэшем) |
| TTL кэша | **5–15 минут** (например 600 с) |

Пример декоратора/обёртки:

```python
@cache(ttl=600)
def get_data():
    ...
```

Ключ кэша: `(symbol, granularity, endpoint_kind)`.

**Реализовано:** в памяти процесса, ключ `(symbol.upper(), granularity, endpoint_kind)`, TTL `MARKET_CURRENT_CACHE_TTL_SEC` (по умолчанию 600, зажат в диапазоне 300–900 с). `collect_daily_snapshot` вызывает `get_market_current_with_fallback(..., use_cache=False)`, чтобы снимки в БД не дублировали закэшированное значение. Сброс: `clear_market_current_cache()`.

---

## 11. Тестирование

**Выполнено:** `tests/test_market_sources.py` (unit: JSON/маппинг/sanity, fallback 503→binance, roundtrip БД), `tests/test_market_plan01_integration.py` + маркер `integration` в `pytest.ini` (сверка с CoinGecko при `COINGECKO_VERIFY=1`).

### 11.1. Unit

- парсинг JSON;
- маппинг полей в dict / DataFrame / строку БД;
- sanity-check (отрицательные и нулевые кейсы).

### 11.2. Integration

- периодическая **сверка с CoinGecko** (пока legacy доступен): отклонение **< 2–3%** по price (и по cap/volume, если сравнимо);
- тест fallback: мок недоступности FreeCryptoAPI → выбор Binance.

---

## 12. Конфигурация

**Выполнено:** переменные в `.env.example` (блок plan01 §12 + `COINGECKO_VERIFY`); справочный YAML `bit_trend/config/market_data.example.yaml` (рантайм по-прежнему из env).

Пример (YAML или `.env` + парсер):

```yaml
data_source:
  primary: freecrypto
  fallback: binance
```

Переменные: базовый URL, API key (если появится), TTL, флаг `COINGECKO_VERIFY=1` для сверки.

---

## 13. Риски и меры

| Риск | Мера | Реализация / контроль |
|------|------|----------------------|
| Нестабильность FreeCryptoAPI (5xx, таймауты, сеть) | Цепочка источников primary→fallback; повторы с backoff; опциональный circuit breaker | `get_market_current_with_fallback`, `MARKET_DATA_PRIMARY` / `MARKET_DATA_FALLBACK`, `MARKET_SOURCE_MAX_ATTEMPTS`, `MARKET_SOURCE_RETRY_BASE_SEC`, `MARKET_CIRCUIT_BREAKER` — `bit_trend/data/market_source.py`; транзиентные HTTP — `http_client.py` |
| Отсутствие или смена контракта JSON у провайдера | Нормализация полей, sanity-check перед записью; не писать битые строки | `normalize_freecrypto_dict`, `_history_json_to_df` — `freecrypto.py`; `sanity_check_market_row`, `save_market_snapshot` — `market_source.py`, `storage.py` |
| Нет глубокой истории (как у CoinGecko) | Гибрид §4.1: история с API + локальные снимки в SQLite | `build_market_history` + `collect_daily_snapshot` — `market_source.py`; таблица и миграция — `storage.py` (`_migrate_market_data_to_plan01`) |
| Расхождение цен/кап/объёма с эталоном | Периодическая сверка; допуск; опциональная проверка в CI | `tests/test_market_plan01_integration.py` + `COINGECKO_VERIFY=1`; порог ~3 % по цене |
| Утечка или отсутствие API-токена | Документированные env; явный fallback при отсутствии токена | `.env.example`, `FREECRYPTO_API_TOKEN`; тест fallback без токена — `test_market_sources.py` |
| Устаревание кэша в UI / двойные снимки | TTL в допустимых пределах; снимки без кэша текущей котировки | `MARKET_CURRENT_CACHE_TTL_SEC` (300–900 с); `collect_daily_snapshot(..., use_cache=False)` |
| Непрозрачная методология агрегации у внешнего API | Логировать `source`; при спорных метриках опираться на сверку и историю в БД | колонка `source` в `market_data`; цепочка fallback пишет различимый `source` |

---

## 14. Этапы внедрения

**Статус:** этапы 1–3 по plan01 выполнены в кодовой базе; дальнейшее — эксплуатация (мониторинг, расписание снимков, при необходимости смена env в production).

### Этап 1 — источник FreeCryptoAPI

- [x] Реализован `FreeCryptoDataSource` (`get_current`, `get_history`, маппинг полей) — `bit_trend/data/freecrypto.py`.
- [x] Unit-покрытие парсинга и нормализации — `tests/test_market_sources.py`.
- [x] Ручной smoke: запрос к API при наличии `FREECRYPTO_API_TOKEN`.

### Этап 2 — интеграция в pipeline

- [x] Все вызовы price/cap/volume идут через `MarketDataSource` и фабрику цепочки — `bit_trend/data/market_source.py`.
- [x] Сверка с CoinGecko при включённом флаге — `tests/test_market_plan01_integration.py`, маркер `integration` в `pytest.ini`.
- [x] Таблица `market_data`, миграция ключа, гибрид истории и `collect_daily_snapshot` — `bit_trend/data/storage.py`, `market_source.py`.

### Этап 3 — production-режим

- [x] По умолчанию primary — `freecrypto` (`MARKET_DATA_PRIMARY`), CoinGecko в цепочке как fallback/сверка, не как обязательный primary — см. значения по умолчанию в `market_source.py` и `.env.example`.
- [x] Fallback chain и TTL кэша текущих котировок настраиваются env (§10, §12).

**Рекомендуемые пост-внедренческие действия (вне кода):**

- Задать расписание вызова `collect_daily_snapshot` (Планировщик заданий Windows / cron на сервере) — не реже 1 раза в сутки для варианта B.
- Включить периодический прогон integration-тестов или мониторинг отклонений, если критична близость к CoinGecko.

---

## 15. Критерии приёмки

- Abstract `MarketDataSource` используется всеми новыми вызовами price/cap/volume.
- Данные пишутся в `market_data` с корректным маппингом и `source`.
- При падении primary срабатывает fallback без необработанного исключения в UI.
- Тесты из §11 проходят в CI.

**Статус проверки (код):**

| Критерий | Реализация |
|----------|------------|
| Цепочка `MarketDataSource` для price/cap/volume | `get_market_current_with_fallback`, `build_market_history`, `collect_daily_snapshot`; **UI:** быстрый блок `DataFetcher.fetch_all` берёт котировку через `get_market_current_with_fallback`, при полном провале цепочки — тикер Binance (`_btc_quote_for_fetcher_fast` в `bit_trend/data/fetcher.py`). В ответ добавлены `btc_market_cap`, `btc_24h_volume`, `btc_quote_source`. Прокси §8.10 (`coingecko_onchain`) — отдельный контур по plan.md. |
| `market_data` + `source` | `save_market_snapshot` / миграции — `storage.py`. |
| Fallback без необработанных исключений в UI | Цепочка и запасной тикер обёрнуты в try/except в `fetch_all`; `get_market_current_with_fallback` логирует и возвращает `None`. |
| Тесты §11 | `tests/test_market_sources.py`; integration — `tests/test_market_plan01_integration.py` (маркер `integration`, опционально `COINGECKO_VERIFY=1`). Команда: `python -m pytest tests/test_market_sources.py -q`. |

---

*Связанные документы: `plan.md`, `upgrade_plan.md` (кэш, ретраи, документация ключей).*
