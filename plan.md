# План создания программы BitTrend

> Основано на PLAN_BTC.md и анализе кодовой базы CryptoConsult

---

## 1. Обзор проекта

**BitTrend** — MVP-приложение для анализа BTC и ребаланса портфеля долгосрочного инвестора.

| Аспект | BitTrend |
|--------|----------|
| Стек | Python 3.10+ / Streamlit |
| БД | Опционально (JSON/CSV для MVP) |
| Запуск | `streamlit run app.py` |
| Фокус | Только BTC, ребаланс портфеля |

---

## 2. Карта переиспользования из CryptoConsult

### 2.1 Прямое использование

| Файл CryptoConsult | Путь | Действие |
|--------------------|------|----------|
| Fear & Greed | `CryptoConsult/backend/market_data/fear_greed.py` | Копировать в `bit_trend/data/fear_greed.py` без изменений |

### 2.2 Адаптация (минимальные правки)

| Файл CryptoConsult | Путь | Изменения для BitTrend |
|--------------------|------|------------------------|
| Derivatives | `CryptoConsult/backend/market_data/derivatives.py` | Убрать лишние зависимости, оставить Funding + OI |
| Macro | `CryptoConsult/backend/market_data/macro.py` | Оставить FRED (ставки, DXY, 10Y) |
| Institutions (ETF) | `CryptoConsult/backend/market_data/institutions.py` | Упростить до ETF flows; добавить fallback на парсинг Farside |
| PriceService | `CryptoConsult/backend/portfolios/services.py` | Взять `PriceCache`, `RateLimiter`, логику `get_price` / `get_historical_prices` для BTC |

### 2.3 Расширение

| Файл CryptoConsult | Путь | Изменения для BitTrend |
|--------------------|------|------------------------|
| Onchain | `CryptoConsult/backend/market_data/onchain.py` | MVRV, NUPL, SOPR: LookIntoBitcoin (парсинг) или fallback — pycoingecko + упрощённая модель (см. 8.10) |

### 2.4 Новая реализация

| Компонент | Причина |
|-----------|---------|
| `BitTrendScorer` | Другие метрики, веса, шкала -100..+100, сигналы BUY/HOLD/REDUCE/EXIT |
| Portfolio Manager | Таблица целевой аллокации по score |
| Trade Calculator | Расчёт объёма сделки и деление на 2–3 части |
| Alert Generator | Форматирование рекомендаций |
| Streamlit UI | Полностью новый интерфейс |

---

## 3. Структура проекта BitTrend

```
BitTrend/
├── bit_trend/
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py       # DataFetcher.fetch_all() — единая точка входа
│   │   ├── binance.py       # Цена, Funding, OI (из derivatives + Binance API)
│   │   ├── onchain.py       # MVRV Z-Score, NUPL, SOPR (Glassnode + LookIntoBitcoin)
│   │   ├── lookintobitcoin.py # Парсинг MVRV/NUPL/SOPR, stabilize, circuit breaker
│   │   ├── storage.py      # SQLite onchain_history, save_history, get_history
│   │   ├── normalize.py    # normalize_mvrv/nupl/sopr → 0–1
│   │   ├── types.py        # OnchainMetrics (TypedDict)
│   │   ├── macro.py        # FRED (ставки, DXY, 10Y)
│   │   ├── etf.py          # Farside / Coinglass ETF flows
│   │   └── fear_greed.py   # Alternative.me (копия из CryptoConsult)
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── calculator.py    # BitTrendScorer
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── manager.py       # Portfolio Manager
│   │   └── trade.py         # Trade Calculator
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── generator.py     # Alert Generator
│   └── __init__.py
├── app.py                   # Streamlit entry point
├── data/
│   └── bittrend.db          # SQLite (onchain_history)
├── notebooks/
│   └── test_formulas.ipynb  # Jupyter для отладки
├── requirements.txt
├── .env.example
└── plan.md
```

---

## 4. Пошаговый план реализации

### Этап 1: Data Fetcher (неделя 1)

| Шаг | Задача | Источник | Файл |
|-----|--------|----------|------|
| 1.1 | Скопировать `fear_greed.py` | CryptoConsult | `bit_trend/data/fear_greed.py` |
| 1.2 | Создать `binance.py` | Binance API + логика из `derivatives.py` | `bit_trend/data/binance.py` |
| 1.3 | Адаптировать `macro.py` | CryptoConsult | `bit_trend/data/macro.py` |
| 1.4 | Расширить `onchain.py` | CryptoConsult + MVRV Z-Score, NUPL | `bit_trend/data/onchain.py` |
| 1.5 | Создать `etf.py` | Farside (парсинг) + Coinglass (если есть ключ) | `bit_trend/data/etf.py` |
| 1.6 | Реализовать `fetcher.py` | Объединить все вызовы, кэш TTL 5–15 мин | `bit_trend/data/fetcher.py` |

**API ключи (опционально):**
- `FRED_API_KEY` — макро
- `GLASSNODE_API_KEY` — MVRV, NUPL, SOPR (не требуется при fallback через pycoingecko, см. 8.10)
- `COINGLASS_API_KEY` — ETF flows

**Бесплатные источники:**
- Binance API, Alternative.me, LookIntoBitcoin (парсинг), Farside (парсинг), pycoingecko (упрощённый MVRV/NUPL/SOPR)

---

### Этап 2: Score Calculator (неделя 2)

| Шаг | Задача | Файл |
|-----|--------|------|
| 2.1 | Реализовать `BitTrendScorer` с метриками и весами | `bit_trend/scoring/calculator.py` |
| 2.2 | Шкала -100..+100 (не -2..+2 как в CryptoConsult) | — |
| 2.3 | Сигнал: BUY / HOLD / REDUCE / EXIT по таблице | — |

**Метрики и веса:**

| Метрика | Вес (%) |
|---------|---------|
| MVRV Z-Score | 25 |
| NUPL | 15 |
| SOPR | 10 |
| MA200 | 15 |
| Funding Rate + OI | 15 |
| ETF flows | 15 |
| Macro (ставки, DXY) | 10 |
| Fear & Greed | 5 |

**Маппинг score → сигнал:**

| Score | Сигнал |
|-------|--------|
| ≥ 50 | BUY |
| 10 … 49 | HOLD (накопление) |
| -10 … 9 | HOLD (осторожность) |
| -30 … -11 | REDUCE |
| < -30 | EXIT |

---

### Этап 3: Portfolio Manager + Trade Calculator (неделя 2–3)

| Шаг | Задача | Файл |
|-----|--------|------|
| 3.1 | Таблица целевой аллокации BTC по score | `bit_trend/portfolio/manager.py` |
| 3.2 | Расчёт отклонения текущего портфеля от целевой доли | — |
| 3.3 | Расчёт объёма сделки (USDT ↔ BTC) | `bit_trend/portfolio/trade.py` |
| 3.4 | Деление сделки на 2–3 части | — |

**Целевая аллокация BTC по score:**

| Score | BTC % в портфеле |
|-------|------------------|
| 70 … 100 | 95% |
| 50 … 69 | 80% |
| 30 … 49 | 65% |
| 10 … 29 | 50% |
| -10 … 9 | 40% |
| -29 … -11 | 25% |
| -49 … -30 | 15% |
| -100 … -50 | 5% |

---

### Этап 4: Alert Generator (неделя 3)

| Шаг | Задача | Файл |
|-----|--------|------|
| 4.1 | Форматирование рекомендаций | `bit_trend/alerts/generator.py` |
| 4.2 | Пример: `SIGNAL: BUY / Action: перевести X USDT → BTC / Confidence: HIGH` | — |
| 4.3 | `generate_from_portfolio()` — единая точка входа (PM + Trade + Alert) для UI | `bit_trend/alerts/generator.py` |

---

### Этап 5: Streamlit UI (неделя 3–4)

| Шаг | Задача | Файл |
|-----|--------|------|
| 5.1 | Главная страница: цена, портфель, score, сигнал, рекомендация | `app.py` |
| 5.2 | Sidebar: ввод USDT и BTC | — |
| 5.3 | Кнопки Execute Part 1/2/3 (MVP: логирование, без реальных ордеров) | — |
| 5.4 | Кнопка Recalculate Score | — |
| 5.5 | Опционально: график MA200, история сигналов | — |

**Макет главного экрана:**
```
BTC Current Price: $70,800
Portfolio: 4000 USDT, 0.05 BTC (~3500 USDT)
Score: 55 (+/-)
Signal: BUY
Recommended Action: Convert 2500 USDT → BTC (3 parts)
Confidence: MEDIUM

[Button] Execute Part 1
[Button] Execute Part 2
[Button] Execute Part 3
[Button] Recalculate Score
```

---

### Этап 6: Jupyter для отладки (параллельно)

| Шаг | Задача | Файл |
|-----|--------|------|
| 6.1 | Тестирование формул MVRV, NUPL, SOPR | `notebooks/test_formulas.ipynb` |
| 6.2 | Валидация весов Z-score / composite, порогов сигналов | см. 8.10 🔟 |
| 6.3 | Backtest onchain-proxy (покупка при composite &lt; −1, продажа при &gt; +1), Sharpe / max DD | `notebooks/backtest_onchain_proxy.ipynb` (опционально) |

---

## 5. Зависимости (requirements.txt)

```
streamlit>=1.28.0
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
plotly>=5.18.0
python-dotenv>=1.0.0
yfinance>=0.2.0    # DXY (Yahoo Finance)
pycoingecko>=3.1.0 # Исторические цены BTC для упрощённого MVRV/NUPL/SOPR (fallback без Glassnode)
```

Опционально: `ccxt` для унификации работы с биржами, `selenium` для парсинга LookIntoBitcoin при защите.

---

## 6. Переменные окружения (.env.example)

```env
# Опционально — для расширенной аналитики
FRED_API_KEY=
GLASSNODE_API_KEY=
COINGLASS_API_KEY=

# TTL кэша (секунды)
CACHE_TTL=300
```

---

## 7. Порядок выполнения (чеклист)

- [x] **Этап 1:** Data Fetcher — все модули + `fetch_all()`
- [x] **Этап 2:** Score Calculator — BitTrendScorer
- [x] **Этап 3:** Portfolio Manager + Trade Calculator
- [x] **Этап 4:** Alert Generator
- [x] **Этап 5:** Streamlit UI
- [x] **Этап 6:** Jupyter notebook для отладки
- [x] **Этап 7:** LookIntoBitcoin 8.1 + production-grade улучшения (см. 8.9)
- [x] **Финал:** Интеграция, тестирование, README

---

## 8. Источники данных и их получение

### 8.1 MVRV Z-Score / NUPL / SOPR

**Вариант 1 (реально рабочий)** → парсинг LookIntoBitcoin

| Метрика | Страница |
|---------|----------|
| MVRV Z-Score | `/charts/mvrv-zscore/` |
| NUPL | `/charts/nupl/` |
| SOPR | `/charts/sopr/` |

**Как парсить:**

**Вариант A (лучше)** — вытащить данные из JS. На странице данные обычно лежат в `<script> ... datasets: [...] </script>`:

```python
import requests
import re
import json

html = requests.get(url).text
data = re.search(r'datasets:\s*(\[[\s\S]*?\])', html)
json_data = json.loads(data.group(1))
```

**Вариант B** — Selenium (если защита):
```python
from selenium import webdriver
```
Минусы: медленно, но надёжно.

**Совет:** обновлять 1 раз в день.

---

### 8.2 MA200 (сам считаешь)

**Источник:** Binance  
`https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=200`

**Расчёт:**
```python
import pandas as pd
df['ma200'] = df['close'].rolling(200).mean()
```
Самый надёжный кусок всей системы.

---

### 8.3 Funding Rate + Open Interest

| Биржа | Funding | Open Interest |
|-------|---------|---------------|
| Binance | `https://fapi.binance.com/fapi/v1/fundingRate` | `https://fapi.binance.com/futures/data/openInterestHist` |
| Bybit | API Bybit | API Bybit |

Делать среднее по Binance + Bybit → почти как агрегатор (надёжность).

---

### 8.4 ETF flows

**Лучший источник** → Farside Investors  
`https://farside.co.uk/btc/`

**Парсинг (устойчивый):**
```python
soup.find("table")
```
Лайфхак: парсить только таблицу, не весь сайт. Проверять изменения структуры.

**Fallback:** Twitter (X) scraping или RSS (если появится).

---

### 8.5 Macro (ставки, DXY, 10Y, S&P500)

**Лучший вариант** → FRED API (бесплатно)

| Метрика | Код FRED |
|---------|----------|
| Ставка ФРС | `FEDFUNDS` |
| 10Y | `DGS10` |
| CPI | `CPIAUCSL` |

**DXY** — в тексте плана: Yahoo Finance (`DX-Y.NYB`). **В коде BitTrend** для согласованности с `upgrade_plan.md` используется широкий индекс доллара FRED `DTWEXBGS`; CPI (`CPIAUCSL`, г/г) и **S&P 500** добавлены в `macro.py` (индекс — yfinance `^GSPC`).

```python
import yfinance as yf
dxy = yf.download("DX-Y.NYB")
```

---

### 8.6 Fear & Greed Index

**API:** Alternative.me  
`https://api.alternative.me/fng/`

---

### 8.7 Архитектура загрузки данных

```
data/
├── loaders/
│   ├── binance.py
│   ├── fred.py
│   ├── fear_greed.py
│   ├── farside_scraper.py
│   └── lookintobitcoin_scraper.py
├── cache/
│   └── sqlite.db
├── services/
│   └── metrics_calculator.py
└── scheduler.py
```

**Scheduler:**
- **Раз в день:** MVRV / NUPL / SOPR / ETF
- **Каждые 5–15 минут:** Funding / OI / price
- **Раз в час:** Macro

**Кэш (обязательно):**
```
CACHE_TTL = 300
```
Без этого: словишь блокировки, API будет тормозить.

---

### 8.8 Сводка: всё можно собрать бесплатно

| Метрика | Реально? | Источник |
|---------|----------|----------|
| MVRV | ✔ | парсинг LookIntoBitcoin или pycoingecko + упрощённая модель (8.10) |
| NUPL | ✔ | парсинг LookIntoBitcoin или pycoingecko + упрощённая модель (8.10) |
| SOPR | ✔ | парсинг LookIntoBitcoin или pycoingecko + упрощённая модель (8.10) |
| Volatility | ✔ | pycoingecko (price) → rolling std returns (8.10) |
| Drawdown | ✔ | pycoingecko (price) → rolling max, drawdown (8.10) |
| MA200 | ✔ | считаешь из Binance |
| Funding | ✔ | API Binance/Bybit |
| OI | ✔ | API Binance/Bybit |
| ETF flows | ✔ | парсинг Farside |
| Macro | ✔ | FRED + Yahoo Finance |
| Fear & Greed | ✔ | API Alternative.me |

---

### 8.9 Реализованные улучшения LookIntoBitcoin (парсинг 8.1) ✅

**Файлы:** `bit_trend/data/lookintobitcoin.py`, `storage.py`, `normalize.py`, `types.py`

#### Парсинг и fallback
- **parse_fast()** — requests + pattern extraction (regex, не `"datasets" in text`)
- **parse_selenium()** — WebDriverWait, headless Chrome, Selenium pool (переиспользование driver)
- **Цепочка:** Glassnode → parse_fast → parse_selenium → last_known_good

#### Надёжность
- **stabilize()** — защита от скачков (MVRV 2.1→9.8→2.2), max_delta по метрике
- **is_same()** — deduplication, не писать в БД одно и то же
- **Data validation** — sanity check (MVRV -5..20, NUPL -0.5..1.5, SOPR 0.5..2.0)
- **Circuit breaker** — отключение на 6 ч после 5 неудач, recovery

#### Качество данных
- **Freshness** — `is_fresh()`, старые данные → confidence × 0.5
- **source_score** — success_rate×0.5 + confidence×0.3 + freshness×0.2, ignore если < 0.4
- **Data provenance** — parser_version, method, timestamp
- **Confidence** — динамический (base × success_rate)

#### Graceful degradation
- **get_last_known_good()** — при failed возвращать последние известные значения
- **logger.error** — CRITICAL при unavailable (защита от silent failure)

#### Time-series storage
- **SQLite** — таблица `onchain_history` (timestamp, mvrv, nupl, sopr, source, confidence)
- **save_history()** — insert только при изменении (deduplication)
- **get_last_history()**, **get_history(limit)** — для графиков, backtesting

#### Drift detection
- **detect_drift(values, window, threshold)** — медленное сползание данных (возможный баг парсинга)

#### Feature flags
- **USE_LOOKINTOBITCOIN**, **USE_SELENIUM** — быстрый disable для тестов

#### Multi-source merge
- **merge_sources(a, b)** — выбор по confidence
- **merge_weighted(a, b, key)** — взвешенное среднее

#### Normalization layer
- **normalize_mvrv()**, **normalize_nupl()**, **normalize_sopr()** — все метрики в 0–1
- **normalize_all(data)** — пакетная нормализация

#### Data contract
- **OnchainMetrics** (TypedDict) — контракт для API

---

### 8.10 Практический способ получить MVRV, NUPL, SOPR и др. без Glassnode API ✅

**Контекст:** Все способы получения MVRV, NUPL и SOPR через Glassnode API не подходят. Используем CoinGecko: цены, Market Cap, Volume — и упрощённые модели.

**Стек:** Python + pandas + pycoingecko + numpy. Упрощённая модель на дневных агрегатах — не идеально, но даёт приблизительные значения, достаточные для анализа.

#### 1️⃣ Установка зависимостей

```powershell
pip install pandas pycoingecko numpy
```

#### 2️⃣ Получение данных из CoinGecko (Price, Market Cap, Volume)

```python
from pycoingecko import CoinGeckoAPI
import pandas as pd
import numpy as np

cg = CoinGeckoAPI()

# Получаем исторические данные за последние 3 года (дневные)
data = cg.get_coin_market_chart_by_id(id='bitcoin', vs_currency='usd', days=1095)

# CoinGecko возвращает: prices, market_caps, total_volumes
df = pd.DataFrame(data['prices'], columns=['timestamp', 'price'])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
df.set_index('timestamp', inplace=True)

# Добавляем Market Cap и Volume — напрямую из API
df['market_cap'] = pd.DataFrame(data['market_caps'], columns=['timestamp', 'market_cap']).set_index('timestamp')['market_cap']
df['volume'] = pd.DataFrame(data['total_volumes'], columns=['timestamp', 'volume']).set_index('timestamp')['volume']

print(df[['price', 'market_cap', 'volume']].head())
```

#### 3️⃣ Улучшенный MVRV proxy

Не 365 дней, а **комбинация окон** — ближе к реальному cost basis:
- **180d** — краткосрочное
- **365d** — среднесрочное
- **730d** — 2 года (долгосрочное)

Realized Value = средняя цена за окно × supply. Для supply используем `market_cap / price`.

```python
# Supply (приблизительно)
df['supply'] = df['market_cap'] / df['price']

# Realized Value для разных окон
df['rv_180'] = df['price'].rolling(180, min_periods=1).mean() * df['supply']
df['rv_365'] = df['price'].rolling(365, min_periods=1).mean() * df['supply']
df['rv_730'] = df['price'].rolling(730, min_periods=1).mean() * df['supply']

# MVRV proxy — основной (730d или взвешенная комбинация)
df['mvrv_730'] = df['market_cap'] / df['rv_730']
df['mvrv_365'] = df['market_cap'] / df['rv_365']
df['mvrv_180'] = df['market_cap'] / df['rv_180']

# Рекомендуемый: 730d или 0.5*730 + 0.3*365 + 0.2*180
df['mvrv_proxy'] = df['market_cap'] / (0.5*df['rv_730'] + 0.3*df['rv_365'] + 0.2*df['rv_180'])
```

#### 4️⃣ NUPL proxy

```python
df['realized_value'] = df['rv_730']  # или комбинация, как выше
df['nupl_proxy'] = (df['market_cap'] - df['realized_value']) / df['market_cap']
```

#### 5️⃣ SOPR proxy через поведение

Добавляем **volume spikes** и **price acceleration** — формула типа `(price / MA) * volume_change`:

```python
# Price acceleration: цена относительно MA
ma = df['price'].rolling(30, min_periods=1).mean()
df['price_vs_ma'] = df['price'] / ma

# Volume change (spike detection)
df['volume_ma'] = df['volume'].rolling(14, min_periods=1).mean()
df['volume_change'] = df['volume'] / df['volume_ma']

# SOPR proxy: (price / MA) * volume_change
df['sopr_proxy'] = (df['price'] / df['price'].rolling(365, min_periods=1).mean()) * df['volume_change']

# Альтернатива: только price/MA для стабильности
df['sopr_simple'] = df['price'] / df['price'].rolling(365, min_periods=1).mean()
```

#### 6️⃣ Volatility и Drawdown (обязательные метрики)

```python
# Volatility — стандартное отклонение доходности за 30 дней
df['returns'] = df['price'].pct_change()
df['volatility_30d'] = df['returns'].rolling(30).std()

# Drawdown — просадка от локального максимума
df['rolling_max'] = df['price'].rolling(730, min_periods=1).max()
df['drawdown'] = (df['price'] - df['rolling_max']) / df['rolling_max']
```

#### 7️⃣ Итог (сырые метрики)

```python
print(df[['price', 'market_cap', 'volume', 'mvrv_proxy', 'nupl_proxy', 'sopr_proxy', 'volatility_30d', 'drawdown']].tail())
```

#### 8️⃣ Z-score для всех метрик (апгрейд 1)

Формула: `(значение − rolling_mean) / rolling_std` по **скользящему окну** (например 365 дней) — метрики в разных шкалах становятся **сопоставимыми**, проще строить стратегию и пороги.

```python
def rolling_z(series, window=365, min_periods=30):
    m = series.rolling(window, min_periods=min_periods).mean()
    s = series.rolling(window, min_periods=min_periods).std()
    return (series - m) / s.replace(0, np.nan)

Z_WIN = 365  # подобрать под горизонт (180 / 365 / 730)

df['mvrv_z'] = rolling_z(df['mvrv_proxy'], Z_WIN)
df['nupl_z'] = rolling_z(df['nupl_proxy'], Z_WIN)
df['sopr_z'] = rolling_z(df['sopr_proxy'], Z_WIN)
df['drawdown_z'] = rolling_z(df['drawdown'], Z_WIN)
df['volatility_z'] = rolling_z(df['volatility_30d'], Z_WIN)
```

**Зачем:** нормализованные сигналы (относительно «нормы» последних N дней), единая логика порогов (например |z| > 2).

**Знак и интерпретация:** для `drawdown` глубокая просадка даёт отрицательный z — в composite часто используют **−drawdown_z** или отрицательный вес, чтобы «страх» на дне усиливал сигнал накопления (по желанию).

#### 9️⃣ Composite index (апгрейд 2)

Единый сигнал рынка — взвешенная сумма z-метрик:

```python
w1, w2, w3, w4 = 0.30, 0.25, 0.20, 0.25  # сумма = 1.0; подобрать под бэктест

# Пример: drawdown — контринтуитивно (глубокая просадка → выше «score накопления»)
df['composite_onchain'] = (
    w1 * df['mvrv_z'] +
    w2 * df['nupl_z'] +
    w3 * df['sopr_z'] +
    w4 * (-df['drawdown_z'])   # или +drawdown_z с отрицательным w4
)
```

**Опционально:** добавить `w5 * volatility_z` (часто с **отрицательным** весом: высокая волатильность → осторожность).

**Итог:** один ряд `composite_onchain` — удобно накладывать на график цены, задавать правила (например composite < −1 → перекупленность по совокупности proxy).

#### 🔟 Как сделать ещё сильнее (реально прокачка)

**1. Сигнальная система (обязательно)** — поверх `composite_onchain` (или `composite_smooth`, см. ниже) получаешь **готовую стратегию** в виде дискретных меток:

```python
def signal(x):
    if pd.isna(x):
        return None
    if x < -1.5:
        return "STRONG BUY"
    elif x < -0.5:
        return "BUY"
    elif x < 0.5:
        return "HOLD"
    elif x < 1.5:
        return "REDUCE"
    else:
        return "STRONG REDUCE"

df['signal'] = df['composite_onchain'].apply(signal)
# Лучше для торговых правил: df['signal'] = df['composite_smooth'].apply(signal)
```

**Согласование знака:** пороги выше предполагают, что **низкий** composite = зона накопления (как в разделе про −drawdown_z). Если после подбора весов composite «перевёрнут», инвертируй ряд или поменяй знаки порогов.

**2. Сглаживание composite** — убирает дневной шум, сигналы стабильнее:

```python
df['composite_smooth'] = df['composite_onchain'].rolling(7).mean()
```

**3. Backtest (обязательно)** — без этого остаётся «красивая идея». Минимальные правила для проверки гипотезы:

- **Покупка:** composite (или `composite_smooth`) **< −1**
- **Продажа:** **> 1**

Дальше — симуляция позиции (100% BTC / кэш), учёт комиссий, скользящее окно обучения весов, Sharpe / max drawdown сценария. Реализация: `notebooks/test_formulas.ipynb` или отдельный `notebooks/backtest_onchain_proxy.ipynb`.

**4. Визуализация (очень важно)** — один экран, чтобы глазами увидеть **дно цикла** и **пик**:

- ось 1: **цена BTC**
- ось 2: **composite** (`composite_onchain` или `composite_smooth`)

Пример (Plotly — два ряда, `secondary_y=True`; или matplotlib `twinx()`):

```python
import matplotlib.pyplot as plt

fig, ax1 = plt.subplots(figsize=(12, 5))
ax1.plot(df.index, df['price'], color='black', label='BTC price')
ax2 = ax1.twinx()
ax2.plot(df.index, df['composite_smooth'], color='tab:blue', alpha=0.85, label='composite (smooth)')
ax1.set_ylabel('Price (USD)')
ax2.set_ylabel('Composite')
fig.tight_layout()
plt.show()
```

**DataFrame содержит колонки:**

| Колонка | Описание |
|---------|----------|
| `price` | Цена BTC |
| `market_cap` | Рыночная капитализация (из CoinGecko) |
| `volume` | Объём торгов (из CoinGecko) |
| `mvrv_proxy` | MVRV proxy (комбинация 180d/365d/730d) |
| `nupl_proxy` | NUPL proxy |
| `sopr_proxy` | SOPR proxy (price/MA × volume_change) |
| `volatility_30d` | Волатильность (30d) |
| `drawdown` | Просадка от максимума |
| `mvrv_z`, `nupl_z`, `sopr_z`, `drawdown_z`, `volatility_z` | Rolling Z-score |
| `composite_onchain` | Единый сигнал (взвешенная сумма z) |
| `composite_smooth` | Сглаженный composite (например `rolling(7)`) |
| `signal` | STRONG BUY / BUY / HOLD / REDUCE / STRONG REDUCE |

Можно строить графики через matplotlib или plotly и делать аналогичные анализы.

**Интеграция:** Добавить `pycoingecko` в `requirements.txt`. Модуль `onchain.py` может использовать этот метод как fallback при недоступности LookIntoBitcoin; `composite_onchain` / `composite_smooth` / `signal` согласовать с `BitTrendScorer` или вывести в Streamlit. Обязательный шаг — **бэктест** порогов (−1 / +1) в ноутбуке перед боевыми весами.

---

## 9. Ссылки на исходники CryptoConsult

| Компонент | Путь |
|-----------|------|
| Fear & Greed | `CryptoConsult/backend/market_data/fear_greed.py` |
| Derivatives | `CryptoConsult/backend/market_data/derivatives.py` |
| Onchain | `CryptoConsult/backend/market_data/onchain.py` |
| Macro | `CryptoConsult/backend/market_data/macro.py` |
| Institutions | `CryptoConsult/backend/market_data/institutions.py` |
| PriceService | `CryptoConsult/backend/portfolios/services.py` |
| DecisionScorer | `CryptoConsult/backend/advisor/decision_scorer.py` (референс, не копировать) |

---

*Документ создан на основе PLAN_BTC.md и анализа папки CryptoConsult.*
