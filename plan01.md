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

| Риск | Мера |
|------|------|
| Нестабильность FreeCryptoAPI | fallback, retry, мониторинг статус-кодов |
| Нет глубокой истории | локальная БД + `collect_daily_snapshot` |
| Неизвестная методология агрегации | периодическая сверка с CoinGecko; логирование `source` |

---

## 14. Этапы внедрения

### Этап 1

- Реализовать `FreeCryptoDataSource`.
- Протестировать `get_current` (unit + ручной smoke).

### Этап 2

- Внедрить в pipeline за абстракцией `MarketDataSource`.
- Сравнить ряды с CoinGecko (integration, допуск 2–3%).
- Включить таблицу `market_data` и при необходимости сбор снимков (вариант B).

### Этап 3

- Отключить CoinGecko как primary для рыночных рядов (оставить опционально для сверки).
- Включить production fallback chain и финальные TTL.

---

## 15. Критерии приёмки

- Abstract `MarketDataSource` используется всеми новыми вызовами price/cap/volume.
- Данные пишутся в `market_data` с корректным маппингом и `source`.
- При падении primary срабатывает fallback без необработанного исключения в UI.
- Тесты из §11 проходят в CI.

---

*Связанные документы: `plan.md`, `upgrade_plan.md` (кэш, ретраи, документация ключей).*
