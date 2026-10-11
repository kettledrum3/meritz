"""Meritz Open API CAVR 자동매매 통합 대시보드 (dashboard.py)

Streamlit 기반 웹 UI로, 실시간 계좌 자산, CA/VR 전략 진행 현황,
주문 및 체결 이력, 메리츠 실시간 외환 환전(Forex) 내역 및 시스템 로그를 모니터링합니다.
"""

import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pytz import timezone

# 프로젝트 루트 경로 등록
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import settings
from core.database import (
    init_db,
    get_all_states_db,
    get_order_history_db,
    get_detailed_trade_history_db,
    get_forex_history_db,
    get_trade_mode,
)
from core.forex import forex_manager
from core.brokers.meritz_kr import MeritzKrBroker
from core.brokers.meritz_us import MeritzUsBroker
from core.utils import format_symbol_display, get_ticker_name

# Streamlit 페이지 설정
st.set_page_config(
    page_title="Meritz CAVR Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

KST = timezone("Asia/Seoul")
EST = timezone("America/New_York")


@st.cache_resource
def get_brokers():
    kr_broker = None
    us_broker = None
    try:
        kr_broker = MeritzKrBroker()
    except Exception as e:
        st.warning(f"KR Broker 초기화 경고: {e}")
    try:
        us_broker = MeritzUsBroker()
    except Exception as e:
        st.warning(f"US Broker 초기화 경고: {e}")
    return kr_broker, us_broker


def is_kr_market_open() -> bool:
    """한국 정규장(09:00~15:30) 운영 여부 (주말 제외)"""
    now = datetime.now(KST)
    if now.weekday() >= 5:  # 토, 일
        return False
    curr_time = now.time()
    open_time = datetime.strptime("09:00", "%H:%M").time()
    close_time = datetime.strptime("15:30", "%H:%M").time()
    return open_time <= curr_time <= close_time


def is_us_market_open() -> bool:
    """미국 정규장 운영 여부 (월~금 현지시간 09:30~16:00)"""
    now = datetime.now(EST)
    if now.weekday() >= 5:
        return False
    curr_time = now.time()
    open_time = datetime.strptime("09:30", "%H:%M").time()
    close_time = datetime.strptime("16:00", "%H:%M").time()
    return open_time <= curr_time <= close_time


LOGO_PATH = os.path.join(BASE_DIR, "meritz_logo.png")


def main():
    init_db()
    kr_broker, us_broker = get_brokers()
    trade_mode = get_trade_mode()

    # ----------------------------------------------------
    # 사이드바
    # ----------------------------------------------------
    with st.sidebar:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=160)
        st.title("⚙️ 시스템 설정")
        
        # 안전 모드 안내
        if settings.MERITZ_READ_ONLY:
            st.warning("🛡️ **안전 모드 (READ_ONLY)**: 모의 주문 및 모의 환전 실행 중")
        else:
            st.error("🚨 **실거래 모드 (REAL TRADING)**: 실제 자금 주문 및 환전 활성화")

        st.markdown("---")
        st.subheader("🔄 화면 새로고침")
        auto_refresh = st.checkbox("자동 새로고침 사용", value=False)
        refresh_interval = st.slider("새로고침 주기(초)", min_value=5, max_value=60, value=15, step=5)
        
        if st.button("즉시 새로고침", use_container_width=True):
            st.rerun()

        st.markdown("---")
        st.subheader("🌐 환경 정보")
        st.text(f"서버 시각: {datetime.now(KST).strftime('%H:%M:%S KST')}")
        st.text(f"API Base: {settings.MERITZ_BASE_URL}")
        st.text(f"계좌 모드: {trade_mode}")
        st.text(f"텔레그램 알림: {'ON' if settings.NOTIFIER_ENABLED else 'OFF'}")
        st.text(f"FX 자동환전: {'ON' if settings.FX_AUTO_EXCHANGE else 'OFF'}")

    # ----------------------------------------------------
    # 상단 헤더 & 상태 지표
    # ----------------------------------------------------
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        header_col_logo, header_col_text = st.columns([1, 4])
        with header_col_logo:
            if os.path.exists(LOGO_PATH):
                st.image(LOGO_PATH, width=150)
        with header_col_text:
            st.title("Meritz CAVR 자동매매 대시보드")
        st.caption("메리츠증권 Open API 기반 무한매수법(CA) & 밸류 리밸런싱(VR) + 실시간 환전(FX) 통합 관제")
    with col_t2:
        now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        st.metric(label="현재 시각", value=now_str)

    # 시장 개장 상태 배지
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        kr_open = is_kr_market_open()
        st.metric(
            label="🇰🇷 한국 정규장 (09:00~15:30)",
            value="🟢 개장 중 (OPEN)" if kr_open else "🔴 휴장 (CLOSED)"
        )
    with col_m2:
        us_open = is_us_market_open()
        st.metric(
            label="🇺🇸 미국 정규장 (22:30/23:30)",
            value="🟢 개장 중 (OPEN)" if us_open else "🔴 휴장 (CLOSED)"
        )
    with col_m3:
        # 실시간 고시환율 조회 시도
        try:
            rate_info = forex_manager.get_market_rate("USD")
            curr_rate = float(rate_info.get("deal_stnd_exrt", 1400.0))
            st.metric(label="💵 USD/KRW 기준 고시환율", value=f"{curr_rate:,.2f}원")
        except Exception:
            st.metric(label="💵 USD/KRW 기준 고시환율", value="조회 대기")
    with col_m4:
        st.metric(
            label="안전 모드 (ReadOnly)",
            value="모의 시뮬레이션" if settings.MERITZ_READ_ONLY else "실거래 주문"
        )

    st.markdown("---")

    # ----------------------------------------------------
    # 자산 현황 요약
    # ----------------------------------------------------
    st.subheader("💰 계좌 자산 현황")
    col_a1, col_a2, col_a3 = st.columns(3)

    krw_cash = 0.0
    usd_cash = 0.0

    try:
        if kr_broker:
            krw_cash = kr_broker.get_cash_pool()
    except Exception:
        pass

    try:
        if us_broker:
            usd_cash = us_broker.get_cash_pool()
    except Exception:
        pass

    with col_a1:
        st.metric(label="원화 가용 예수금", value=f"{int(krw_cash):,}원")
    with col_a2:
        st.metric(label="외화(USD) 가용 예수금", value=f"${usd_cash:,.2f}")
    with col_a3:
        # 환율 적용 합산 추정
        est_total = krw_cash + (usd_cash * 1400.0)
        st.metric(label="현금 예수금 추정 합산 (환율 ~1,400원)", value=f"{int(est_total):,}원")

    # ----------------------------------------------------
    # 메인 탭 구성
    # ----------------------------------------------------
    tab_strategies, tab_orders, tab_trades, tab_forex, tab_logs = st.tabs([
        "📈 운용 전략 현황 (CA / VR)",
        "📋 당일 주문 내역 (Orders)",
        "📜 체결 및 실현손익 (Trades)",
        "💱 실시간 환전 내역 (Forex)",
        "🖥️ 시스템 로그 (Logs)"
    ])

    # ----------------------------------------------------
    # 탭 1: 운용 전략 현황
    # ----------------------------------------------------
    with tab_strategies:
        all_states = get_all_states_db(trade_mode=trade_mode)
        if not all_states:
            st.info("등록된 전략 상태가 없습니다. 스케줄러가 실행되면 기본 전략이 생성됩니다.")
        else:
            ca_states = [s for s in all_states if s.get("strategy_type") == "CA"]
            vr_states = [s for s in all_states if s.get("strategy_type") == "VR"]

            # 1. 무한매수법(CA) 현황
            st.markdown("### 🔄 무한매수법 (Cost Averaging) 전략")
            if not ca_states:
                st.caption("운용 중인 CA 전략이 없습니다.")
            else:
                for st_data in ca_states:
                    sym = st_data.get("symbol", "")
                    s_name = st_data.get("strategy_name", "")
                    market = st_data.get("market", "US")
                    shares = float(st_data.get("total_shares", 0))
                    avg_p = float(st_data.get("avg_price", 0))
                    curr_p = float(st_data.get("current_price", 0))
                    turn = float(st_data.get("current_turn", 0))
                    a_def = float(st_data.get("a_default", 40))
                    target_p_pct = float(st_data.get("target_profit_pct", 0.10)) * 100
                    mode = st_data.get("mode", "NORMAL")

                    # 현재 수익률 계산
                    pnl_rate = ((curr_p - avg_p) / avg_p * 100) if avg_p > 0 else 0.0
                    target_sell_price = avg_p * (1.0 + (target_p_pct / 100.0)) if avg_p > 0 else 0.0

                    cur_sym = "₩" if market == "KR" else "$"
                    p_fmt = (lambda v: f"{int(v):,}") if market == "KR" else (lambda v: f"{v:,.2f}")

                    with st.expander(f"📌 {s_name} ({format_symbol_display(sym, market)}) - {mode} 모드", expanded=True):
                        c1, c2, c3, c4, c5 = st.columns(5)
                        c1.metric("보유 수량", f"{int(shares)}주")
                        c2.metric("평균 매수가", f"{cur_sym}{p_fmt(avg_p)}")
                        c3.metric("현재가", f"{cur_sym}{p_fmt(curr_p)}", f"{pnl_rate:+.2f}%")
                        c4.metric(f"목표 익절가 (+{target_p_pct:.1f}%)", f"{cur_sym}{p_fmt(target_sell_price)}")
                        c5.metric("진행 회차", f"{turn:.1f} / {a_def:.0f}회")

                        # 진행률 바
                        progress_val = min(max(turn / a_def if a_def > 0 else 0.0, 0.0), 1.0)
                        st.progress(progress_val, text=f"원금 소진 진행률: {progress_val*100:.1f}%")

            # 2. 밸류 리밸런싱(VR) 현황
            st.markdown("### ⚖️ 밸류 리밸런싱 (Value Rebalancing) 전략")
            if not vr_states:
                st.caption("운용 중인 VR 전략이 없습니다.")
            else:
                for st_data in vr_states:
                    sym = st_data.get("symbol", "")
                    s_name = st_data.get("strategy_name", "")
                    market = st_data.get("market", "US")
                    shares = float(st_data.get("total_shares", 0))
                    v_val = float(st_data.get("V", 0.0))
                    pool_val = float(st_data.get("pool", 0.0))
                    last_e = float(st_data.get("last_E", 0.0))
                    band_low = v_val * 0.85
                    band_high = v_val * 1.15
                    mode = st_data.get("mode", "RUNNING")

                    cur_sym = "₩" if market == "KR" else "$"
                    p_fmt = (lambda v: f"{int(v):,}") if market == "KR" else (lambda v: f"{v:,.2f}")

                    with st.expander(f"📌 {s_name} ({format_symbol_display(sym, market)}) - {mode} 모드", expanded=True):
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("목표 밸류 (V)", f"{cur_sym}{p_fmt(v_val)}")
                        c2.metric("주식 평가액 (E)", f"{cur_sym}{p_fmt(last_e)}")
                        c3.metric("가용 Pool (현금)", f"{cur_sym}{p_fmt(pool_val)}")
                        c4.metric("밴드 범위 (±15%)", f"{cur_sym}{p_fmt(band_low)} ~ {cur_sym}{p_fmt(band_high)}")

                        # Plotly 밴드 내 위치 시각화
                        fig = go.Figure()
                        fig.add_trace(go.Bar(
                            y=["밸류 위치"],
                            x=[band_low],
                            name="하단 밴드 (Low)",
                            orientation='h',
                            marker=dict(color='rgba(54, 162, 235, 0.4)')
                        ))
                        fig.add_trace(go.Bar(
                            y=["밸류 위치"],
                            x=[v_val - band_low],
                            name="목표 V",
                            orientation='h',
                            marker=dict(color='rgba(75, 192, 192, 0.6)')
                        ))
                        fig.add_trace(go.Bar(
                            y=["밸류 위치"],
                            x=[band_high - v_val],
                            name="상단 밴드 (High)",
                            orientation='h',
                            marker=dict(color='rgba(255, 99, 132, 0.4)')
                        ))
                        fig.update_layout(
                            barmode='stack',
                            height=120,
                            margin=dict(l=20, r=20, t=10, b=10),
                            showlegend=False
                        )
                        st.plotly_chart(fig, use_container_width=True)

    # ----------------------------------------------------
    # 탭 2: 당일 주문 내역
    # ----------------------------------------------------
    with tab_orders:
        st.subheader("📋 최근 주문 내역 (order_history)")
        orders = get_order_history_db()
        if not orders:
            st.info("기록된 주문 내역이 없습니다.")
        else:
            df_orders = pd.DataFrame(orders)
            st.dataframe(
                df_orders,
                use_container_width=True,
                column_config={
                    "timestamp": "주문 시각",
                    "symbol": "종목코드",
                    "strategy": "전략",
                    "side": "구분",
                    "price": st.column_config.NumberColumn("주문가", format="%.2f"),
                    "qty": "수량",
                    "type": "유형",
                    "status": "상태",
                    "odno": "주문번호",
                    "msg": "메시지"
                }
            )

    # ----------------------------------------------------
    # 탭 3: 체결 및 실현손익
    # ----------------------------------------------------
    with tab_trades:
        st.subheader("📜 체결 이력 및 실현손익 (trade_history)")
        trades = get_detailed_trade_history_db(symbol=None)
        if not trades:
            st.info("체결된 거래 내역이 없습니다.")
        else:
            df_trades = pd.DataFrame(trades)
            st.dataframe(df_trades, use_container_width=True)

            # 누적 실현손익 차트
            if "realized_profit" in df_trades.columns and not df_trades.empty:
                df_trades['cum_profit'] = df_trades['realized_profit'].cumsum()
                fig_profit = px.line(
                    df_trades,
                    x="date",
                    y="cum_profit",
                    title="📈 누적 실현손익 추이",
                    markers=True
                )
                st.plotly_chart(fig_profit, use_container_width=True)

    # ----------------------------------------------------
    # 탭 4: 실시간 환전 내역
    # ----------------------------------------------------
    with tab_forex:
        st.subheader("💱 메리츠 실시간 외화 환전 기록 (forex_history)")
        forex_records = get_forex_history_db(limit=100)
        if not forex_records:
            st.info("환전 거래 내역이 아직 없습니다. (스케줄러에 의해 자동 환전 시 여기에 기록됩니다)")
        else:
            df_fx = pd.DataFrame(forex_records)
            st.dataframe(
                df_fx,
                use_container_width=True,
                column_config={
                    "created_at": "환전 일시",
                    "direction": "환전 방향",
                    "crcd": "통화",
                    "applied_rate": st.column_config.NumberColumn("적용 환율(원)", format="%.2f"),
                    "wncr_amt": st.column_config.NumberColumn("원화 금액", format="%,.0f원"),
                    "frcr_amt": st.column_config.NumberColumn("외화 금액", format="$%,.2f"),
                    "fee": "수수료",
                    "note": "비고",
                    "tr_srno": "거래번호"
                }
            )

    # ----------------------------------------------------
    # 탭 5: 시스템 로그
    # ----------------------------------------------------
    with tab_logs:
        st.subheader("🖥️ 스케줄러 실행 로그 (scheduler.log)")
        log_path = os.path.join(BASE_DIR, "logs", "scheduler.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                recent_logs = "".join(lines[-150:])
            st.text_area("최근 150줄 로그", recent_logs, height=450)
        else:
            st.info("로그 파일이 아직 생성되지 않았습니다.")

    # 자동 새로고침 처리
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()
