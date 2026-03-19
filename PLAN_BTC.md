# Bit-trend: MVP анализа BTC для долгосрочного инвестора

## Сравнение стеков

| Аспект | CryptoConsult | Bit-trend |
|--------|---------------|-----------|
| Backend | Django + DRF | Нет (логика в Python-модулях) |
| Frontend | Next.js 14 | Streamlit |
| БД | SQLite | Опционально (JSON/CSV для MVP) |
| Развёртывание | Django + npm build | `streamlit run app.py` |
| Сложность | Высокая | Низкая (MVP) |
| Фокус | Универсальный консультант + чат | Только BTC, ребаланс портфеля |

---

## Анализ программы CryptoConsult

### Текущий стек CryptoConsult

| Слой | Технология | Назначение |
|------|------------|------------|
| Backend | Django 4.2 + DRF | REST API, ORM, бизнес-логика |
| Frontend | Next.js 14 + TypeScript | SPA, Zustand, Recharts |
| БД | SQLite | Портфели, профили, чат |
| Цены | CoinGecko API | Spot-цены, история |
| Деривативы | Binance Futures API | Funding, OI, Long/Short |
| Он-чейн | Blockchain.com + Glassnode | MVRV, SOPR, exchange flow |
| Макро | FRED API | ФРС, DXY, 10Y, S&P 500 |
| ETF | Coinglass API | Потоки, AUM |
| Сентимент | Alternative.me | Fear & Greed Index |

### Логика CryptoConsult (DecisionScorer)

- **5 блоков** с весами: A (25%), B (20%), C (20%), D (20%), E (15%)
- **Диапазон score**: от -2 до +2
- **Сигнал**: BUY (>0.75), HOLD ([-0.75..0.75]), REDUCE (<-0.75)
- **Блоки**: структура (MA200, HH/LL), импульс (RSI, MACD), деривативы, он-чейн, макро+F&G

### Что можно переиспользовать для Bit-trend

| Компонент CryptoConsult | Пригодность для Bit-trend |
|-------------------------|---------------------------|
| `market_data/fear_greed.py` | ✅ Прямое использование |
| `market_data/derivatives.py` | ✅ Адаптация (Funding, OI) |
| `market_data/onchain.py` | ⚠️ Расширить: добавить MVRV Z-Score, NUPL (LookIntoBitcoin/Glassnode) |
| `market_data/macro.py` | ✅ Адаптация (FRED) |
| `market_data/institutions.py` | ✅ Адаптация (ETF flows → Farside) |
| `portfolios/services.py` (PriceService) | ✅ Логика кэша, Binance/CoinGecko |
| `advisor/decision_scorer.py` | ❌ Новая модель: другие метрики, веса, шкала -100..+100 |

---

## Почему Python + Streamlit + API — отличный вариант

1. **Быстрый MVP** — Streamlit даёт UI без React/Next.js
2. **Единый стек** — всё на Python: данные, логика, интерфейс
3. **Меньше зависимостей** — не нужны Django, Node.js, npm
4. **Jupyter для отладки** — удобно тестировать формулы и метрики
5. **Легко развернуть** — `streamlit run app.py` или Streamlit Cloud
6. **API как есть** — Binance, CoinGecko, Alternative.me, FRED и др. уже используются в CryptoConsult

---

# MVP Bit-trend: Техническое задание

## 1️⃣ Цель

Создать MVP, который позволяет:

- оценивать текущую ситуацию на рынке BTC для долгосрочного инвестирования;
- тестировать стратегии ребаланса портфеля (BTC/USDT);
- получать конкретные рекомендации по покупке/продаже с учётом текущего score.

---

## 2️⃣ Структура программы (модули)

### Data Fetcher

**Источники данных:**

| Метрика | Источник | API / метод |
|---------|----------|-------------|
| BTC Price | Binance API / CoinGecko API | `fapi.binance.com` / `api.coingecko.com` |
| MA200 | Вычисляется из цены BTC | pandas / numpy |
| MVRV Z-Score | LookIntoBitcoin (парсинг) / Glassnode | Бесплатно / `GLASSNODE_API_KEY` |
| NUPL | LookIntoBitcoin / Glassnode | Бесплатно / Glassnode |
| SOPR | Glassnode / LookIntoBitcoin | `GLASSNODE_API_KEY` / парсинг |
| Funding Rate + Open Interest | Binance Futures / Coinglass | `fapi.binance.com` / `COINGLASS_API_KEY` |
| ETF flows | Farside Investors (парсинг) / Coinglass | Парсинг / `COINGLASS_API_KEY` |
| Macro (ставки, DXY) | FRED / Trading Economics | `FRED_API_KEY` |
| Fear & Greed Index | Alternative.me | Бесплатно |

**Функции:**

- сбор и хранение последних значений метрик;
- кэширование для минимизации запросов API (TTL 5–15 мин);
- fallback при недоступности API.

---

### Score Calculator

- Вычисление score по весам (от **-100** до **+100**).
- Применение формул расчёта для каждой метрики.
- Генерация сигнала: **BUY** / **HOLD** / **REDUCE** / **EXIT**.

---

### Portfolio Manager

- Перевод score в целевую долю BTC/USDT.
- Подсчёт отклонения текущего портфеля от целевой доли.

---

### Trade Calculator

- Расчёт объёма сделки (USDT → BTC или BTC → USDT).
- Деление сделки на 2–3 части для постепенного входа/выхода.

---

### Alert Generator

- Форматирование рекомендаций для пользователя.
- Пример:
  ```
  SIGNAL: BUY
  Action: перевести 1000 USDT → BTC
  Confidence: HIGH
  ```

---

### UI / Dashboard

- Визуализация: текущий score, баланс BTC/USDT, рекомендации.
- История сигналов и сделок (для тестирования стратегии).
- Кнопки для ручного ребаланса (MVP режим).

---

## 3️⃣ Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.10+ |
| Отладка | Jupyter Notebook |
| UI | Streamlit |
| HTTP | requests / CCXT |
| Данные | pandas, numpy |
| Графики | plotly / matplotlib |

---

## 4️⃣ Метрики и веса

| Метрика | Вес (%) | Назначение |
|---------|---------|------------|
| MVRV Z-Score | 25 | Цикл рынка, переоценка/недооценка |
| NUPL | 15 | Фаза рынка: прибыль/убыток участников |
| SOPR | 10 | Фиксация прибыли/убытка |
| MA200 | 15 | Долгосрочный тренд, фильтр держать/осторожно |
| Funding Rate + Open Interest | 15 | Перегрев или капитуляция на деривативах |
| ETF flows | 15 | Институциональные деньги → поддержка тренда |
| Macro (ставки, DXY) | 10 | Внешнее давление → коррекция риска |
| Fear & Greed Index | 5 | Страх/жадность толпы, дополняет MVRV/SOPR |

**Итого:** 100%

---

## 5️⃣ Логика расчёта сигналов

```
1. Сбор данных через Data Fetcher
2. Вычисление score → Score Calculator
3. Определение целевой доли BTC/USDT → Portfolio Manager
4. Сравнение с текущим портфелем → Trade Calculator
5. Вывод рекомендации → Alert Generator
```

### Целевая аллокация BTC по score

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

### Маппинг score → сигнал

| Score | Сигнал |
|-------|--------|
| ≥ 50 | BUY |
| 10 … 49 | HOLD (накопление) |
| -10 … 9 | HOLD (осторожность) |
| -30 … -11 | REDUCE |
| < -30 | EXIT |

---

## 6️⃣ Пример расчёта сделки

**Портфель:** 4000 USDT + 0.05 BTC (~3500 USDT)  
**Score:** +55 → целевая доля BTC = 80%

- Целевая доля = 80% от портфеля (4000 + 3500) = 6000 USDT
- Текущая доля BTC = 3500 USDT
- Нужно докупить BTC на **2500 USDT**
- Деление сделки на 3 части → **833 + 833 + 834 USDT**

---

## 7️⃣ MVP UI (Streamlit)

### Главный экран

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

### Возможные расширения

- График MA200
- История сигналов (score по времени)
- Настройка весов и порогов score (тестирование стратегий)

---

## 8️⃣ MVP функционал (быстрая реализация)

1. Fetch данных через API
2. Вычисление score по формуле
3. Определение целевой доли BTC/USDT
4. Расчёт сделки и деление на части
5. Простая визуализация через Streamlit (таблица + кнопки)
6. История сигналов в виде DataFrame / plotly графика

---

## 9️⃣ Где брать данные (бесплатно)

### Цена / MA

| Источник | Метод |
|----------|-------|
| Binance API | `GET /fapi/v1/ticker/price`, `GET /fapi/v1/klines` |
| CoinGecko | `GET /api/v3/coins/bitcoin/market_chart` |

### Деривативы

| Источник | Метод |
|----------|-------|
| Coinglass | API (нужен ключ) |
| Binance Futures | Funding Rate, Open Interest — бесплатно |
| CryptoQuant | Ограниченно бесплатно |

### Он-чейн (без платного API)

| Источник | Метод |
|----------|-------|
| LookIntoBitcoin | Парсинг HTML/JSON |
| Glassnode | Ограниченно бесплатно |

### ETF

| Источник | Метод |
|----------|-------|
| Farside Investors | Парсинг страницы flows |

### Сентимент

| Источник | Метод |
|----------|-------|
| Alternative.me | `GET https://api.alternative.me/fng/` — бесплатно |

### Макро

| Источник | Метод |
|----------|-------|
| Trading Economics | API (ограничения) |
| FRED | `FRED_API_KEY` — бесплатно |
| MacroMicro | Парсинг |

---

## 🔟 План миграции из CryptoConsult

### Этап 1: Выделение Data Fetcher

1. Скопировать `market_data/` в отдельный пакет `bit_trend/data/`.
2. Добавить модули для MVRV Z-Score, NUPL (LookIntoBitcoin или Glassnode).
3. Реализовать парсинг Farside для ETF flows (fallback при отсутствии Coinglass).
4. Объединить все вызовы в единый `DataFetcher.fetch_all()` с кэшем.

### Этап 2: Score Calculator

1. Реализовать `BitTrendScorer` с метриками и весами из раздела 4.
2. Шкала -100..+100 вместо -2..+2.
3. Сигнал BUY/HOLD/REDUCE/EXIT по таблице из раздела 5.

### Этап 3: Portfolio Manager + Trade Calculator

1. Таблица целевой аллокации по score.
2. Расчёт отклонения и объёма сделки.
3. Деление на 2–3 части.

### Этап 4: Streamlit UI

1. Главная страница с текущими данными и рекомендациями.
2. Sidebar для ввода портфеля (USDT, BTC).
3. Кнопки Execute Part 1/2/3 (MVP: только логирование, без реальных ордеров).
4. График score и истории сигналов (опционально).

### Этап 5: Jupyter для отладки

1. Notebook для тестирования формул MVRV, NUPL, SOPR.
2. Валидация весов и порогов.

---

## Структура проекта Bit-trend (предлагаемая)

```
bit_trend/
├── data/
│   ├── fetcher.py      # Data Fetcher
│   ├── binance.py      # Цена, Funding, OI
│   ├── onchain.py      # MVRV, NUPL, SOPR
│   ├── macro.py        # FRED
│   ├── etf.py          # Farside / Coinglass
│   └── fear_greed.py   # Alternative.me
├── scoring/
│   └── calculator.py   # Score Calculator
├── portfolio/
│   ├── manager.py      # Portfolio Manager
│   └── trade.py        # Trade Calculator
├── alerts/
│   └── generator.py    # Alert Generator
├── app.py              # Streamlit entry point
├── notebooks/          # Jupyter для отладки
│   └── test_formulas.ipynb
├── requirements.txt
└── .env.example
```

---

## Зависимости (requirements.txt)

```
streamlit>=1.28.0
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
plotly>=5.18.0
python-dotenv>=1.0.0
```

Опционально: `ccxt` для унификации работы с биржами.
