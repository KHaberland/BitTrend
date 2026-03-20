# BitTrend

MVP-приложение для анализа BTC и ребаланса портфеля долгосрочного инвестора.

## Возможности

- **Score** — агрегированный показатель от -100 до +100 на основе восьми метрик (MVRV, NUPL, SOPR, MA200, деривативы, ETF flows, макро, Fear & Greed). Веса и пороги задаются в `bit_trend/config/scoring.yaml` (переопределение пути — `BITTREND_SCORING_CONFIG`).
- **Сигналы** — BUY / HOLD / REDUCE / EXIT по таблице порогов из того же конфига.
- **Ребаланс** — целевая доля BTC в портфеле по score, расчёт отклонения и объёма сделки.
- **Рекомендации** — форматированные действия с разбиением на 2–3 части.
- **Качество ончейна в UI** — источник (`source`), `confidence`, `source_score` для MVRV/NUPL/SOPR, чтобы «тишина» или прокси не воспринимались как полноценный Glassnode.
- **§8.10 CoinGecko** — опциональный блок в интерфейсе: composite по прокси (цена, капитализация, объём) и сырьевые ряды; при необходимости composite можно смешать в основной score через `SCORER_WEIGHT_COMPOSITE_810` (см. `.env.example`).

## Требования

- Python 3.10+
- Windows / Linux / macOS
- Для **LookIntoBitcoin** при `USE_SELENIUM=true` и для **Farside** (fallback ETF-потоков) при `USE_FARSIDE_SELENIUM=true` — установленный **Google Chrome** (Selenium 4 подтянет совместимый драйвер). Отключение Selenium ускоряет запуск, но HTML-страницы могут отличаться или быть недоступны (логика в `bit_trend/data/onchain.py`, `bit_trend/data/etf.py`).

## Стек и зависимости

Основные пакеты перечислены в `requirements.txt`:

| Область | Библиотеки / замечания |
|--------|-------------------------|
| UI | Streamlit, Plotly |
| Данные и расчёты | pandas, numpy, requests, BeautifulSoup4 |
| Конфиг | PyYAML; значения по умолчанию в `bit_trend/config/scoring.yaml` |
| Макро | FRED (при ключе), **yfinance** для S&P 500 (^GSPC) |
| Ончейн LTB | Selenium (опционально) + встроенный circuit breaker / кэш |
| **CoinGecko** | Прямые HTTP-запросы к `api.coingecko.com` (`market_chart`). Библиотека **pycoingecko в проекте не используется**. |
| Деривативы | **Binance** + **Bybit** — funding rate и open interest **усредняются** там, где доступны оба источника (`bit_trend/data/binance.py`, `bit_trend/data/bybit.py`). Ключи API бирж не требуются (публичные эндпоинты). |
| HTTP | Общий клиент с интервалом между запросами к хосту, ретраями и backoff (`bit_trend/data/http_client.py`); параметры — `HTTP_*` в `.env`. |

**ccxt** в `requirements.txt` (P3): по умолчанию кнопки Execute только логируют объём (MVP). Рыночные ордера включаются явно через `.env` — см. `BITTREND_LIVE_*` в таблице ниже и `.env.example`.

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

# Скопировать переменные окружения (опционально, но удобно для тюнинга)
Copy-Item .env.example .env
```

## Запуск

```powershell
streamlit run app.py
```

Приложение откроется в браузере по адресу `http://localhost:8501`.

## Использование

1. **Sidebar** — введите сумму в USDT и количество BTC в портфеле.
2. **Recalculate Score** — обновить данные и пересчитать score (кэш: общий `CACHE_TTL`, отдельно при необходимости `CACHE_TTL_FAST` / `CACHE_TTL_SLOW`).
3. Блок **ончейна** — при наличии данных показываются источник и метрики качества; раскрывающийся раздел **§8.10** — composite и компоненты CoinGecko-proxy.
4. **Execute Part 1/2/3** — по умолчанию **MVP**: в лог и toast пишется объём, ордер не отправляется. При **`BITTREND_LIVE_TRADING=true`**, **`BITTREND_LIVE_TRADING_ACK=YES`** и ключах **`BITTREND_CCXT_*`** отправляется рыночный buy/sell на сумму части в сторону `deviation_usdt` (докупка / продажа); при дрейфе ончейна live по умолчанию блокируется (`BITTREND_LIVE_BLOCK_ON_DRIFT`).

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

**Обязательных ключей нет** — ончейн MVRV/NUPL/SOPR по умолчанию с CoinGecko `market_chart` (прокси §8.10); Glassnode и парсинг LookIntoBitcoin включаются флагами. Остальное: Binance/Bybit публичные эндпоинты, Alternative.me, Farside и т.д.

Создайте `.env` на основе `.env.example`. Кратко о группах:

| Переменная | Описание |
|------------|----------|
| `FRED_API_KEY` | Fed Funds, 10Y, DXY (FRED `DTWEXBGS`), CPI — без ключа эти ряды недоступны; S&P всё равно подтягивается через yfinance |
| `USE_GLASSNODE`, `GLASSNODE_API_KEY` | Дозаполнение ончейна после CoinGecko (по умолчанию Glassnode выключен) |
| `COINGLASS_API_KEY` | Данные ETF через Coinglass (иначе — парсинг Farside и т.п., см. код) |
| `BITTREND_SCORING_CONFIG` | Путь к своему YAML со весами/порогами (по умолчанию встроенный `scoring.yaml`) |
| `HTTP_RATE_MIN_INTERVAL_SEC`, `HTTP_MAX_RETRIES`, `HTTP_BACKOFF_*` | Лимиты и повторы HTTP |
| `CACHE_TTL`, `CACHE_TTL_FAST`, `CACHE_TTL_SLOW` | TTL кэша: общий и раздельно для «быстрого» и «медленного» блоков данных |
| `USE_COINGECKO_ONCHAIN`, `COINGECKO_*`, `COMPOSITE_810_*`, `SCORER_WEIGHT_COMPOSITE_810` | Основной proxy ончейна (§8.10) и веса composite |
| `ONCHAIN_DRIFT_*` | S3: дрейф по истории LTB в SQLite (`detect_drift`) — предупреждение в алерте и снижение весов MVRV/NUPL/SOPR (детали в `scoring.yaml` → `onchain_drift`) |
| `USE_SELENIUM`, `USE_LOOKINTOBITCOIN`, `LOOKINTOBITCOIN_*` | Дозаполнение ончейна парсингом LTB (по умолчанию выкл.), circuit breaker, пороги |
| `BITTREND_DB_PATH` | Путь к SQLite (по умолчанию `data/bittrend.db`) |
| `FREECRYPTO_API_TOKEN`, `FREECRYPTO_API_BASE`, `MARKET_DATA_PRIMARY`, `MARKET_DATA_FALLBACK`, `MARKET_CURRENT_CACHE_TTL_SEC`, `MARKET_SOURCE_*`, `MARKET_CIRCUIT_BREAKER`, `MARKET_CB_*` | Рыночные price/cap/volume (plan01): primary FreeCrypto, цепочка fallback, TTL кэша, ретраи / circuit breaker; справочный YAML — `bit_trend/config/market_data.example.yaml` |
| `COINGECKO_VERIFY` | При `1` / `true` включает интеграционную сверку с CoinGecko (`pytest -m integration`, нужен токен FreeCrypto и сеть) |
| `BITTREND_SIGNAL_CSV_PATH`, `BITTREND_SIGNAL_DEDUPE_SEC` | P1: дублировать историю сигналов из UI в CSV; окно дедупликации повторных расчётов (сек), `0` — писать каждый раз |
| `BITTREND_LIVE_TRADING`, `BITTREND_LIVE_TRADING_ACK` | P3: live-ордера только при `ACK=YES` ровно; иначе всегда MVP |
| `BITTREND_CCXT_EXCHANGE`, `BITTREND_CCXT_SYMBOL`, `BITTREND_CCXT_API_KEY`, `BITTREND_CCXT_API_SECRET`, `BITTREND_CCXT_PASSWORD`, `BITTREND_CCXT_TESTNET` | Параметры ccxt (например `binance`, `BTC/USDT`) |
| `BITTREND_LIVE_BLOCK_ON_DRIFT` | При `true` и флаге дрейфа ончейна live не вызывается, остаётся MVP-логирование |

Полный список с значениями по умолчанию — в **`.env.example`**.

## Тестирование

```powershell
# Запуск всех тестов
python -m pytest tests/ -v

# Только быстрые unit/integration-локальные (без живых API plan01 §11.2)
python -m pytest tests/ -v -m "not integration"

# Сверка FreeCrypto vs CoinGecko (сеть + COINGECKO_VERIFY=1 + FREECRYPTO_API_TOKEN)
$env:COINGECKO_VERIFY = "1"
python -m pytest tests/ -v -m integration

# С покрытием (если установлен pytest-cov)
python -m pytest tests/ -v --cov=bit_trend
```

## Структура проекта

```
BitTrend/
├── bit_trend/
│   ├── config/        # scoring.yaml, загрузка конфига (E2)
│   ├── data/          # Сбор данных (Binance, Bybit, onchain, macro, ETF, Fear & Greed, CoinGecko)
│   ├── scoring/       # BitTrendScorer — расчёт score и сигнала
│   ├── portfolio/     # Portfolio Manager, Trade Calculator
│   └── alerts/        # Alert Generator — форматирование рекомендаций
├── app.py             # Streamlit UI
├── tests/             # Unit и integration тесты
├── notebooks/         # Jupyter: формулы; backtest_onchain_proxy.ipynb (S2, §8.10)
├── data/              # SQLite: onchain_history, signal_history (P1)
├── requirements.txt
└── .env.example
```

## Источники данных

| Метрика | Источник |
|---------|----------|
| Цена, MA200 | Binance API |
| Funding, OI (среднее при двух источниках) | Binance API + Bybit API (публичные) |
| MVRV, NUPL, SOPR | Glassnode (ключ) → LookIntoBitcoin (парсинг) → **fallback: прокси CoinGecko** (`coingecko_onchain`, §8.10) |
| Volatility / drawdown / composite §8.10 | Ряды CoinGecko `market_chart` (тот же запрос, кэш бандла) |
| ETF flows | Coinglass (с `COINGLASS_API_KEY`) → иначе парсинг **Farside** (часто через Selenium + таблица на странице) |
| Macro | FRED (ставки, 10Y, DXY `DTWEXBGS`, CPI при `FRED_API_KEY`); S&P 500 — **yfinance** |
| Fear & Greed | Alternative.me |

## Лицензия

MIT
