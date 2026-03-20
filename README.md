# BitTrend

MVP-приложение для анализа BTC и ребаланса портфеля долгосрочного инвестора.

## Возможности

- **Score** — агрегированный показатель от -100 до +100 на основе 8 метрик (MVRV, NUPL, SOPR, MA200, Funding, ETF flows, Macro, Fear & Greed)
- **Сигналы** — BUY / HOLD / REDUCE / EXIT по таблице порогов
- **Ребаланс** — целевая доля BTC в портфеле по score, расчёт отклонения и объёма сделки
- **Рекомендации** — форматированные действия с разбиением на 2–3 части

## Требования

- Python 3.10+
- Windows / Linux / macOS

## Установка

```powershell
# Клонировать репозиторий
git clone <repo-url>
cd BitTrend

# Создать виртуальное окружение (рекомендуется)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Установить зависимости
pip install -r requirements.txt

# Скопировать переменные окружения (опционально)
Copy-Item .env.example .env
```

## Запуск

```powershell
streamlit run app.py
```

Приложение откроется в браузере по адресу `http://localhost:8501`.

## Использование

1. **Sidebar** — введите сумму в USDT и количество BTC в портфеле
2. **Recalculate Score** — обновить данные и пересчитать score
3. **Execute Part 1/2/3** — MVP: логирование объёма сделки (реальные ордеры не исполняются)

### Макет главного экрана

```
BTC Current Price: $70,800
Portfolio: 4000 USDT, 0.05 BTC (~3500 USDT)
Score: 55 (+/-)
Signal: BUY
Recommended Action: Convert 2500 USDT → BTC (3 parts)
Confidence: MEDIUM

[Execute Part 1] [Execute Part 2] [Execute Part 3] [Recalculate Score]
```

## Переменные окружения

Создайте файл `.env` на основе `.env.example`:

| Переменная | Описание | Обязательно |
|------------|----------|--------------|
| `FRED_API_KEY` | API ключ FRED (макро) | Нет |
| `GLASSNODE_API_KEY` | API ключ Glassnode (onchain) | Нет |
| `COINGLASS_API_KEY` | API ключ Coinglass (ETF) | Нет |
| `CACHE_TTL` | TTL кэша в секундах (по умолчанию 300) | Нет |

**Бесплатные источники** (работают без ключей): Binance API, Alternative.me (Fear & Greed), LookIntoBitcoin (парсинг), Farside (парсинг ETF).

## Тестирование

```powershell
# Запуск всех тестов
python -m pytest tests/ -v

# С покрытием (если установлен pytest-cov)
python -m pytest tests/ -v --cov=bit_trend
```

## Структура проекта

```
BitTrend/
├── bit_trend/
│   ├── data/          # Сбор данных (Binance, onchain, macro, ETF, Fear & Greed)
│   ├── scoring/       # BitTrendScorer — расчёт score и сигнала
│   ├── portfolio/     # Portfolio Manager, Trade Calculator
│   └── alerts/        # Alert Generator — форматирование рекомендаций
├── app.py             # Streamlit UI
├── tests/             # Unit и integration тесты
├── notebooks/         # Jupyter: формулы; backtest_onchain_proxy.ipynb (S2, §8.10)
├── data/              # SQLite (onchain_history)
├── requirements.txt
└── .env.example
```

## Источники данных

| Метрика | Источник |
|---------|----------|
| Цена, MA200, Funding, OI | Binance API |
| MVRV, NUPL, SOPR | LookIntoBitcoin (парсинг) / Glassnode |
| ETF flows | Farside (парсинг) / Coinglass |
| Macro (ставки, DXY) | FRED API / Yahoo Finance |
| Fear & Greed | Alternative.me |

## Лицензия

MIT
