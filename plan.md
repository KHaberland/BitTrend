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
| Onchain | `CryptoConsult/backend/market_data/onchain.py` | Добавить MVRV Z-Score, NUPL (LookIntoBitcoin или Glassnode) |

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
- `GLASSNODE_API_KEY` — MVRV, NUPL, SOPR
- `COINGLASS_API_KEY` — ETF flows

**Бесплатные источники:**
- Binance API, Alternative.me, LookIntoBitcoin (парсинг), Farside (парсинг)

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
| 6.2 | Валидация весов и порогов | — |

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
- [ ] **Финал:** Интеграция, тестирование, README

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

**DXY** (нет в FRED напрямую) → Yahoo Finance:
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
| MVRV | ✔ | парсинг LookIntoBitcoin |
| NUPL | ✔ | парсинг LookIntoBitcoin |
| SOPR | ✔ | парсинг LookIntoBitcoin |
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
