"""
BitTrend — Streamlit UI.
Этап 5: Главная страница, sidebar, кнопки Execute Part 1/2/3, Recalculate Score.
"""

import logging
import os
from datetime import datetime

import streamlit as st

from bit_trend.data.fetcher import DataFetcher
from bit_trend.data.binance import get_btc_klines
from bit_trend.scoring.calculator import BitTrendScorer
from bit_trend.portfolio.manager import PortfolioManager
from bit_trend.portfolio.trade import TradeCalculator
from bit_trend.alerts.generator import generate_from_portfolio

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
    if "signal_history" not in st.session_state:
        st.session_state.signal_history = []


def _compute_and_store(usdt: float, btc_amount: float, btc_price: float):
    """Вычислить score, сигнал, рекомендацию и сохранить в session_state."""
    fetcher = DataFetcher(ttl_seconds=CACHE_TTL)
    data = fetcher.fetch_all(use_cache=True)
    data["btc_price"] = btc_price  # актуальная цена

    scorer = BitTrendScorer()
    score, signal, _ = scorer.compute(data)

    btc_value_usdt = btc_amount * btc_price
    recommendation = generate_from_portfolio(
        usdt=usdt,
        btc_value_usdt=btc_value_usdt,
        score=score,
        signal=signal,
        btc_price=btc_price,
        num_parts=3,
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

    # История сигналов (опционально)
    st.session_state.signal_history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "score": score,
        "signal": signal,
    })
    if len(st.session_state.signal_history) > 20:
        st.session_state.signal_history = st.session_state.signal_history[-20:]


def _execute_part(part_num: int):
    """MVP: логирование Execute Part N без реальных ордеров."""
    parts = st.session_state.get("parts", [])
    if part_num < 1 or part_num > len(parts):
        st.warning(f"Часть {part_num} недоступна.")
        return
    amount = parts[part_num - 1]
    logger.info(f"[MVP] Execute Part {part_num}: {amount:.2f} USDT (логирование, ордер не исполнен)")
    st.toast(f"Part {part_num}: {amount:,.0f} USDT — логирование (MVP, ордер не исполнен)")


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
        tab1, tab2 = st.tabs(["MA200 vs Price", "История сигналов"])

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
            history = st.session_state.get("signal_history", [])
            if history:
                import pandas as pd
                df_history = pd.DataFrame(history)
                st.dataframe(df_history, use_container_width=True, hide_index=True)
            else:
                st.caption("История сигналов пуста пока не выполнен расчёт.")


if __name__ == "__main__":
    main()
