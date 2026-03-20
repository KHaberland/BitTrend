"""
BitTrend — Streamlit UI.
Этап 5: Главная страница, sidebar, кнопки Execute Part 1/2/3, Recalculate Score.
"""

import logging
import os
import streamlit as st

from bit_trend.data.fetcher import DataFetcher
from bit_trend.data.binance import get_btc_klines
from bit_trend.config.loader import get_scoring_config
from bit_trend.scoring.calculator import BitTrendScorer
from bit_trend.portfolio.manager import PortfolioManager
from bit_trend.portfolio.trade import TradeCalculator
from bit_trend.alerts.generator import generate_from_portfolio
from bit_trend.data.storage import append_signal_history, get_signal_history
from bit_trend.data.coingecko_onchain import get_coingecko_810_chart_frame
from bit_trend.execution.ccxt_executor import execute_rebalance_part, live_trading_status_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация страницы
st.set_page_config(
    page_title="BitTrend",
    page_icon="₿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# TTL кэша из .env
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))


def _init_session_state():
    """Инициализация session_state."""
    if "score" not in st.session_state:
        st.session_state.score = None
    if "signal" not in st.session_state:
        st.session_state.signal = None
    if "recommendation" not in st.session_state:
        st.session_state.recommendation = None
    if "parts" not in st.session_state:
        st.session_state.parts = []
    if "deviation_usdt" not in st.session_state:
        st.session_state.deviation_usdt = 0.0


def _compute_and_store(usdt: float, btc_amount: float, btc_price: float):
    """Вычислить score, сигнал, рекомендацию и сохранить в session_state."""
    fetcher = DataFetcher(ttl_seconds=CACHE_TTL)
    data = fetcher.fetch_all(use_cache=True)
    data["btc_price"] = btc_price  # актуальная цена

    scorer = BitTrendScorer()
    score, signal, components = scorer.compute(data)

    btc_value_usdt = btc_amount * btc_price
    drift_note = (data.get("onchain_drift_note") or "").strip() or None
    recommendation = generate_from_portfolio(
        usdt=usdt,
        btc_value_usdt=btc_value_usdt,
        score=score,
        signal=signal,
        btc_price=btc_price,
        num_parts=3,
        extra_suffix=drift_note,
    )

    pm = PortfolioManager()
    tc = TradeCalculator()
    target_btc_pct = pm.get_target_btc_pct(score)
    _, _, deviation_usdt = pm.get_deviation(usdt, btc_value_usdt, target_btc_pct)
    _, parts = tc.calculate_trade(deviation_usdt, btc_price, num_parts=3)

    st.session_state.score = score
    st.session_state.signal = signal
    st.session_state.recommendation = recommendation
    st.session_state.parts = parts
    st.session_state.deviation_usdt = deviation_usdt
    st.session_state.metrics_data = data
    st.session_state.components = components
    st.session_state.last_btc_price = float(btc_price or 0.0)

    dedupe_sec = int(os.getenv("BITTREND_SIGNAL_DEDUPE_SEC", "90"))
    append_signal_history(
        score=score,
        signal=signal,
        btc_price=btc_price if btc_price else None,
        usdt=usdt,
        btc_amount=btc_amount,
        deviation_usdt=deviation_usdt,
        recommendation=recommendation,
        dedupe_within_seconds=dedupe_sec,
    )


def _execute_part(part_num: int):
    """MVP по умолчанию; при P3 (ccxt + env) — реальный рыночный ордер."""
    parts = st.session_state.get("parts", [])
    if part_num < 1 or part_num > len(parts):
        st.warning(f"Часть {part_num} недоступна.")
        return
    amount = parts[part_num - 1]
    deviation = float(st.session_state.get("deviation_usdt") or 0.0)
    metrics = st.session_state.get("metrics_data") or {}
    drift = bool(metrics.get("onchain_drift_any"))
    btc_p = float(
        metrics.get("btc_price")
        or st.session_state.get("last_btc_price")
        or 0.0
    )
    res = execute_rebalance_part(
        part_num,
        amount,
        deviation,
        btc_p,
        onchain_drift_any=drift,
    )
    if res.ok:
        st.toast(res.message)
    else:
        st.error(res.message)


def main():
    _init_session_state()

    # Sidebar: ввод USDT и BTC (5.2)
    with st.sidebar:
        st.header("Портфель")
        usdt = st.number_input(
            "USDT",
            min_value=0.0,
            value=4000.0,
            step=100.0,
            format="%.2f",
        )
        btc_amount = st.number_input(
            "BTC",
            min_value=0.0,
            value=0.05,
            step=0.01,
            format="%.4f",
        )
        st.divider()
        st.markdown(live_trading_status_message())
        st.caption(
            "P3: без `BITTREND_LIVE_TRADING` + `ACK=YES` + ключей ccxt работает только MVP-логирование."
        )
        if st.button("Recalculate Score", type="primary", use_container_width=True):
            DataFetcher(ttl_seconds=CACHE_TTL).clear_cache()
            st.session_state.score = None
            st.rerun()
        st.caption("Обновить данные и пересчитать score.")

    # Загрузка данных (с индикатором)
    fetcher = DataFetcher(ttl_seconds=CACHE_TTL)
    with st.spinner("Загрузка данных с бирж и API…"):
        data = fetcher.fetch_all(use_cache=True)
    btc_price = data.get("btc_price") or 0.0
    btc_value_usdt = btc_amount * btc_price

    # Первый расчёт или при изменении портфеля
    if st.session_state.score is None:
        with st.spinner("Расчёт score и рекомендаций…"):
            _compute_and_store(usdt, btc_amount, btc_price)
        st.session_state._last_usdt = usdt
        st.session_state._last_btc = btc_amount

    metrics_data = st.session_state.get("metrics_data") or data

    # Главная страница (5.1)
    st.title("BitTrend")
    st.subheader("Анализ BTC и ребаланс портфеля")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("BTC Current Price", f"${btc_price:,.0f}")

    with col2:
        total = usdt + btc_value_usdt
        st.metric(
            "Portfolio",
            f"{usdt:,.0f} USDT, {btc_amount:.4f} BTC (~{btc_value_usdt:,.0f} USDT)",
        )

    with col3:
        score_str = f"{st.session_state.score:+.1f}" if st.session_state.score is not None else "—"
        st.metric("Score", score_str)

    st.divider()

    # Сигнал и рекомендация
    signal = st.session_state.signal or "—"
    signal_color = {
        "BUY": "🟢",
        "HOLD": "🟡",
        "REDUCE": "🟠",
        "EXIT": "🔴",
    }.get(signal, "")
    st.metric("Signal", f"{signal_color} {signal}")

    recommendation = st.session_state.recommendation or "—"
    st.info(f"**Recommended Action:** {recommendation}")
    if metrics_data.get("onchain_drift_any"):
        st.warning(
            "Обнаружен возможный **дрейф** в сохранённой истории LTB (SQLite) по метрикам: "
            f"**{', '.join(metrics_data.get('onchain_drift_labels') or [])}**. "
            f"Веса MVRV/NUPL/SOPR временно умножены на **{get_scoring_config().onchain_drift.weight_factor:g}** (см. `onchain_drift` в scoring.yaml, S3)."
        )

    # Метрики по порядку (1, 2, 3, …); качество ончейна — сразу видно (upgrade_plan D2)
    components = st.session_state.get("components") or {}

    def _safe_float(x, default=None):
        if x is None:
            return default
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    o_src = metrics_data.get("onchain_source")
    o_conf = _safe_float(metrics_data.get("onchain_confidence"))
    o_ss = _safe_float(metrics_data.get("onchain_source_score"))
    o_meth = metrics_data.get("onchain_method")

    has_onchain_vals = any(
        metrics_data.get(k) is not None for k in ("mvrv_z_score", "nupl", "sopr")
    )
    st.caption("**Качество ончейна (MVRV / NUPL / SOPR)** — plan.md §8.9")
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        st.metric(
            "source",
            "—" if not o_src or o_src == "none" else str(o_src),
            help="Источник сырья для тройки MVRV/NUPL/SOPR (glassnode, lookintobitcoin, coingecko, смесь).",
        )
    with q2:
        st.metric(
            "confidence",
            "—" if o_conf is None else f"{o_conf:.2f}",
            help="Уверенность источника после учёта success_rate и свежести (LTB и др.).",
        )
    with q3:
        st.metric(
            "source_score",
            "—" if o_ss is None else f"{o_ss:.2f}",
            help="Итоговая оценка надёжности: success_rate×0.5 + confidence×0.3 + freshness×0.2.",
        )
    with q4:
        st.metric(
            "method",
            "—" if not o_meth else str(o_meth),
            help="Способ получения: api, parse_fast, selenium и т.д.",
        )
    if (not o_src or o_src == "none") and has_onchain_vals:
        st.warning(
            "Есть числа MVRV/NUPL/SOPR, но provenance не заполнен — проверьте цепочку get_btc_onchain / DataFetcher."
        )

    def _fmt(val, fmt_str=".2f"):
        if val is None:
            return "—"
        if isinstance(val, float):
            return f"{val:{fmt_str}}"
        return str(val)

    _sconf = get_scoring_config()
    _w810 = _sconf.composite_in_scorer.weight
    _810_weight_label = f"{_w810 * 100:.0f}%" if _w810 else "0% (только блок §8.10)"

    metrics_list = [
        (1, "MVRV Z-Score", metrics_data.get("mvrv_z_score"), "25%", components.get("mvrv_z_score")),
        (2, "NUPL", metrics_data.get("nupl"), "15%", components.get("nupl")),
        (3, "SOPR", metrics_data.get("sopr"), "10%", components.get("sopr")),
        (4, "MA200", metrics_data.get("ma200"), "15%", components.get("ma200")),
        (5, "Funding + OI", f"funding={_fmt(metrics_data.get('funding_rate'))}, OI 7d={_fmt(metrics_data.get('open_interest_7d_change_pct'))}%", "15%", components.get("derivatives")),
        (6, "ETF flow 7d (USD)", metrics_data.get("etf_flow_7d_usd"), "15%", components.get("etf")),
        (7, "Macro (signal)", metrics_data.get("macro_signal"), "10%", components.get("macro")),
        (8, "Fear & Greed", metrics_data.get("fear_greed_value"), "5%", components.get("fear_greed")),
    ]
    if metrics_data.get("cg_composite_onchain") is not None or (components.get("composite_810") is not None and abs(float(components.get("composite_810") or 0)) > 1e-9):
        metrics_list.append(
            (9, "§8.10 cg_composite_onchain (z)", metrics_data.get("cg_composite_onchain"), _810_weight_label, components.get("composite_810")),
        )

    with st.expander("📊 Все метрики (1–8+§8.10)"):
        for num, name, raw_val, weight, comp in metrics_list:
            if isinstance(raw_val, str):
                raw_str = raw_val
            else:
                raw_str = _fmt(raw_val, ",.0f") if isinstance(raw_val, (int, float)) and (raw_val or 0) > 1000 else _fmt(raw_val)
            comp_str = f" → вклад {comp:+.0f}" if comp is not None else ""
            weight_str = f" (вес {weight})" if weight else ""
            st.text(f"{num}. {name}{weight_str}: {raw_str}{comp_str}")

    def _cg810_zone(z) -> str:
        """Дискретная зона по plan.md §8.10 (пороги по z-композиту, ориентир)."""
        if z is None:
            return "—"
        try:
            x = float(z)
        except (TypeError, ValueError):
            return "—"
        if x < -1.5:
            return "STRONG BUY (proxy)"
        if x < -0.5:
            return "BUY (proxy)"
        if x < 0.5:
            return "HOLD (proxy)"
        if x < 1.5:
            return "REDUCE (proxy)"
        return "STRONG REDUCE / риск (proxy)"

    with st.expander("🔎 Качество ончейн-данных (источник и уверенность)"):
        if not o_src or o_src == "none":
            st.warning(
                "Ончейн MVRV/NUPL/SOPR без явного источника или недоступны — "
                "вклад этих метрик в score может опираться на «тишину» (нулевые компоненты)."
            )
        else:
            conf_s = f"{o_conf:.2f}" if o_conf is not None else "—"
            ss_s = f"{o_ss:.2f}" if o_ss is not None else "—"
            st.markdown(
                f"**source:** `{o_src}`  \n"
                f"**confidence:** `{conf_s}`  \n"
                f"**source_score:** `{ss_s}`  \n"
                f"**method:** `{o_meth or '—'}`"
            )
            if o_ss is not None and o_ss < 0.5:
                st.caption("Низкий source_score — трактуйте MVRV/NUPL/SOPR осторожно (прокси или ухудшенный парсинг).")

    cg_c = metrics_data.get("cg_composite_onchain")
    if cg_c is not None or metrics_data.get("cg_volatility_30d") is not None:
        with st.expander("📈 §8.10 ончейн-composite (CoinGecko proxy, S1)"):
            st.caption(
                "Отдельный ряд по plan.md §8.10: rolling z по прокси MVRV/NUPL/SOPR, волатильность 30d, drawdown; "
                "composite не дублирует веса MVRV/NUPL/SOPR в основном score, пока в scoring.yaml `composite_in_scorer.weight` = 0 "
                "(или задайте SCORER_WEIGHT_COMPOSITE_810 в .env)."
            )
            st.metric("cg_composite_onchain (z)", f"{cg_c:.3f}" if cg_c is not None else "—", help="Взвешенная сумма z; низкие значения часто ближе к зоне накопления в примерах плана.")
            st.caption(f"Зона (ориентир): **{_cg810_zone(cg_c)}**")
            c810_comp = components.get("composite_810")
            if c810_comp is not None:
                st.caption(
                    f"Вклад в шкалу -100…+100 (для смешивания): **{c810_comp:+.1f}**; "
                    f"вес в score (E2): **{_w810:g}**, scale: **{_sconf.composite_in_scorer.scale:g}**"
                )
            zcols = st.columns(2)
            with zcols[0]:
                st.markdown(
                    f"| z | значение |\n|---|----------|\n"
                    f"| cg_mvrv_z | `{metrics_data.get('cg_mvrv_z')}` |\n"
                    f"| cg_nupl_z | `{metrics_data.get('cg_nupl_z')}` |\n"
                    f"| cg_sopr_z | `{metrics_data.get('cg_sopr_z')}` |\n"
                )
            with zcols[1]:
                st.markdown(
                    f"| z / сырьё | значение |\n|-----------|----------|\n"
                    f"| cg_volatility_z | `{metrics_data.get('cg_volatility_z')}` |\n"
                    f"| cg_drawdown_z | `{metrics_data.get('cg_drawdown_z')}` |\n"
                    f"| cg_volatility_30d | `{metrics_data.get('cg_volatility_30d')}` |\n"
                    f"| cg_drawdown | `{metrics_data.get('cg_drawdown')}` |\n"
                )
            ts810 = metrics_data.get("cg_proxy_updated_at")
            if ts810:
                st.caption(f"Обновление ряда CoinGecko: `{ts810}`")
            st.caption(
                "Веса composite: переменные COMPOSITE_810_W_MVRV, …_NUPL, …_SOPR, …_DRAWDOWN, …_VOLATILITY (.env)."
            )

    cpi_y = metrics_data.get("cpi_yoy_pct")
    sp_raw = metrics_data.get("sp500")
    sp_ch = metrics_data.get("sp500_30d_change_pct")
    macro_interp = metrics_data.get("macro_interpretation")
    with st.expander("🌐 Макро §8.5: CPI и S&P 500 (приоритет отображения)"):
        st.caption(
            "**CPI** — FRED `CPIAUCSL` (г/г); **S&P 500** — yfinance `^GSPC` (~22 торг. дня к предыдущему якорю). "
            "ФРС, DXY (FRED `DTWEXBGS`), 10Y — при `FRED_API_KEY`, они же питают общий `macro_signal`."
        )
        if cpi_y is not None:
            st.metric("CPI г/г", f"{cpi_y:.2f}%")
        else:
            st.caption("CPI: нужен `FRED_API_KEY` и доступный месячный ряд FRED.")
        if sp_raw is not None:
            st.metric("S&P 500", f"{sp_raw:,.2f}", delta=f"{sp_ch:.2f}%" if sp_ch is not None else None)
        else:
            st.caption("S&P: не удалось загрузить (yfinance).")
        if macro_interp:
            st.caption(f"Интерпретация макросигнала: {macro_interp}")

    # Кнопки
    st.divider()
    btn_col1, btn_col2, btn_col3, btn_col4, _ = st.columns([1, 1, 1, 1, 1])

    with btn_col1:
        if st.button("Execute Part 1", use_container_width=True):
            _execute_part(1)

    with btn_col2:
        if st.button("Execute Part 2", use_container_width=True):
            _execute_part(2)

    with btn_col3:
        if st.button("Execute Part 3", use_container_width=True):
            _execute_part(3)

    with btn_col4:
        if st.button("Recalculate Score", use_container_width=True):
            fetcher.clear_cache()
            _compute_and_store(usdt, btc_amount, btc_price)
            st.rerun()

    # Пересчёт при изменении портфеля (usdt/btc в sidebar)
    if st.session_state.get("_last_usdt") != usdt or st.session_state.get("_last_btc") != btc_amount:
        st.session_state._last_usdt = usdt
        st.session_state._last_btc = btc_amount
        _compute_and_store(usdt, btc_amount, btc_price)

    # Опционально: график MA200, история сигналов (5.5)
    st.divider()
    with st.expander("График MA200 и история сигналов"):
        tab1, tab2, tab3 = st.tabs(["MA200 vs Price", "История сигналов", "Composite §8.10 vs цена (P2)"])

        with tab1:
            prices = get_btc_klines(400)
            if prices and len(prices) >= 200:
                import pandas as pd
                import plotly.graph_objects as go

                df = pd.DataFrame({"close": prices})
                df["ma200"] = df["close"].rolling(200).mean()
                df = df.dropna()

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    y=df["close"],
                    name="BTC Price",
                    line=dict(color="#F7931A"),
                ))
                fig.add_trace(go.Scatter(
                    y=df["ma200"],
                    name="MA200",
                    line=dict(color="#888", dash="dash"),
                ))
                fig.update_layout(
                    title="BTC Price vs MA200",
                    height=350,
                    margin=dict(l=0, r=0, t=40, b=0),
                    legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Недостаточно данных для MA200.")

        with tab2:
            st.caption(
                "Персистентная история (P1): SQLite `data/bittrend.db`, таблица `signal_history`. "
                "Опциональный дубликат в CSV — `BITTREND_SIGNAL_CSV_PATH` в `.env`; окно дедупликации — `BITTREND_SIGNAL_DEDUPE_SEC` (сек)."
            )
            history = get_signal_history(500)
            if history:
                import pandas as pd
                df_history = pd.DataFrame(history)
                st.dataframe(df_history, use_container_width=True, hide_index=True)
            else:
                st.caption("История сигналов пуста: выполните расчёт (первый запуск или «Recalculate Score»).")

        with tab3:
            st.caption(
                "Два ряда по plan.md §8.10: **цена BTC** (CoinGecko `market_chart`) и **cg_composite_onchain** "
                "(взвешенная сумма z по прокси MVRV/NUPL/SOPR, drawdown, volatility). "
                "Сглаживание `composite_smooth` — rolling(7) как в плане. Данные из того же кэша, что и блок §8.10 после S1/D1."
            )
            cwide = st.slider("Число последних дневных точек", min_value=200, max_value=4000, value=2000, step=100, key="cg_chart_points")
            cwsmooth = st.slider("Окно сглаживания composite (дней)", min_value=1, max_value=30, value=7, key="cg_chart_smooth")
            cg_df = get_coingecko_810_chart_frame(max_points=cwide, smooth_window=cwsmooth)
            if cg_df is not None and not cg_df.empty:
                import plotly.graph_objects as go
                from plotly.subplots import make_subplots

                x = cg_df.index
                fig_c = make_subplots(specs=[[{"secondary_y": True}]])
                fig_c.add_trace(
                    go.Scatter(
                        x=x,
                        y=cg_df["price"],
                        name="BTC (close, USD)",
                        line=dict(color="#F7931A"),
                    ),
                    secondary_y=False,
                )
                fig_c.add_trace(
                    go.Scatter(
                        x=x,
                        y=cg_df["composite_onchain"],
                        name="composite_onchain (z)",
                        line=dict(color="rgba(66, 133, 244, 0.35)", width=1),
                    ),
                    secondary_y=True,
                )
                fig_c.add_trace(
                    go.Scatter(
                        x=x,
                        y=cg_df["composite_smooth"],
                        name=f"composite_smooth ({cwsmooth}d)",
                        line=dict(color="#1a73e8", width=2),
                    ),
                    secondary_y=True,
                )
                fig_c.update_layout(
                    title="Composite proxy (§8.10) vs цена BTC",
                    height=420,
                    margin=dict(l=0, r=0, t=48, b=0),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    hovermode="x unified",
                )
                fig_c.update_yaxes(title_text="USD", secondary_y=False)
                fig_c.update_yaxes(title_text="composite (z)", secondary_y=True)
                fig_c.add_hline(y=1.0, line_dash="dot", line_color="rgba(128,128,128,0.5)", secondary_y=True)
                fig_c.add_hline(y=-1.0, line_dash="dot", line_color="rgba(128,128,128,0.5)", secondary_y=True)
                st.plotly_chart(fig_c, use_container_width=True)
            else:
                st.info(
                    "Ряд недоступен: включите `USE_COINGECKO_ONCHAIN`, проверьте доступ к CoinGecko API "
                    "(ключ при необходимости) или дождитесь загрузки данных на главной странице."
                )


if __name__ == "__main__":
    main()
