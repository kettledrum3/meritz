"""Meritz Open API CAVR 자동매매 통합 스케줄러 (core/scheduler.py)

한국 주식시장(KR) 및 미국 주식시장(US)의 운영 일정에 맞춰
라오어 무한매수법(CA) 및 밸류 리밸런싱(VR) 알고리즘 주문을 정기 집행하고,
메리츠 외환(FX) 실시간 환전 및 계좌 정산/텔레그램 알림을 자동 수행합니다.
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import pytz
from pytz import timezone

# 프로젝트 루트 경로 등록
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings, load_market_env
from core.database import (
    init_db,
    get_all_states_db,
    load_state_db,
    save_state_db,
    get_trade_mode,
    rotate_log_file,
    get_connection,
)
from core.notifier import send_telegram_message
from core.brokers.meritz_kr import MeritzKrBroker
from core.brokers.meritz_us import MeritzUsBroker
from core.forex import forex_manager
from core.cavr import (
    CAConfig,
    VRConfig,
    CostAveragingEngine,
    ValueRebalancingEngine,
    fetch_kr_holiday,
    is_us_market_holiday,
    load_etf_list,
)
from core.utils import format_symbol_display

# 로깅 설정
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
log_file_path = os.path.join(LOG_DIR, "scheduler.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(filename)s:%(lineno)d) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file_path, encoding="utf-8")
    ]
)
logger = logging.getLogger("scheduler")

KST = timezone("Asia/Seoul")
EST = timezone("America/New_York")

# 브로커 캐싱 싱글톤
_kr_broker: Optional[MeritzKrBroker] = None
_us_broker: Optional[MeritzUsBroker] = None

def get_kr_broker() -> MeritzKrBroker:
    global _kr_broker
    if _kr_broker is None:
        _kr_broker = MeritzKrBroker()
    return _kr_broker

def get_us_broker() -> MeritzUsBroker:
    global _us_broker
    if _us_broker is None:
        _us_broker = MeritzUsBroker()
    return _us_broker


def is_us_dst(target_dt: Optional[datetime] = None) -> bool:
    """미국 서머타임(Daylight Saving Time) 적용 여부 확인"""
    if target_dt is None:
        target_dt = datetime.now(EST)
    else:
        target_dt = target_dt.astimezone(EST)
    return bool(target_dt.dst())


def ensure_default_strategies_exist():
    """DB에 활성화된 전략이 하나도 없으면 env 설정을 바탕으로 기본 전략을 생성합니다."""
    try:
        init_db()
        trade_mode = get_trade_mode()
        active_states = get_all_states_db(trade_mode=trade_mode)
        if active_states:
            return

        logger.info("ℹ️ DB에 등록된 활성 전략이 없습니다. 기본 환경설정(env)으로부터 기본 전략을 초기화합니다.")
        
        # 1. 한국장 기본 전략 (CA)
        kr_env = load_market_env("KR")
        kr_symbol = kr_env.get("ticker", "122630")
        kr_ca_cfg = CAConfig(
            symbol=kr_symbol,
            strategy_type="CA",
            use_db=True,
            market="KR",
            strategy_name=f"CA_{kr_symbol}_1차",
            initial_budget=float(kr_env.get("initial_cash", 10000000)),
            a_default=int(kr_env.get("a_default", 40)),
            target_profit_pct=float(kr_env.get("T_profit", 0.07)),
            use_quarter_stop=bool(kr_env.get("quarter_loss_stop", False))
        )
        kr_engine = CostAveragingEngine(config=kr_ca_cfg, broker=get_kr_broker())
        save_state_db(kr_engine.state, market="KR", strategy_name=kr_ca_cfg.strategy_name)
        logger.info(f"✅ 기본 한국장 전략 생성 완료: {kr_ca_cfg.strategy_name}")

        # 2. 미국장 기본 전략 (VR & CA)
        us_env = load_market_env("US")
        us_symbol = us_env.get("ticker", "SOXL")
        us_vr_cfg = VRConfig(
            symbol=us_symbol,
            strategy_type="VR",
            use_db=True,
            market="US",
            strategy_name=f"VR_{us_symbol}",
            initial_budget=float(us_env.get("initial_cash", 10000.0)),
            G=10.0,
            band_low_pct=85.0,
            band_high_pct=115.0
        )
        us_vr_engine = ValueRebalancingEngine(config=us_vr_cfg, broker=get_us_broker())
        save_state_db(us_vr_engine.state, market="US", strategy_name=us_vr_cfg.strategy_name)
        logger.info(f"✅ 기본 미국장 전략 생성 완료: {us_vr_cfg.strategy_name}")

    except Exception as e:
        logger.error(f"❌ 기본 전략 초기화 실패: {e}", exc_info=True)


# ==============================================================================
# [한국 주식 시장 (KR) 작업 루틴]
# ==============================================================================

def job_kr_morning_prep():
    """[KR 08:50] 장전 유지보수 및 점검"""
    now_kst = datetime.now(KST)
    if not fetch_kr_holiday():
        logger.info("⏸️ [KR] 오늘은 한국 주식시장 휴장일(주말/공휴일)입니다. 장전 준비를 건너뜁니다.")
        return

    logger.info("🌅 [KR 08:50] 한국 정규장 개장 전 점검 및 유지보수 시작")
    rotate_log_file("scheduler.log", max_size_mb=2)
    init_db(run_maintenance=True)

    try:
        broker = get_kr_broker()
        cash = broker.get_cash_pool()
        logger.info(f"💰 [KR] 당일 가용 원화 예수금: {int(cash):,}원")
    except Exception as e:
        logger.error(f"❌ [KR] 장전 브로커 잔고 확인 실패: {e}")


def job_kr_market_open():
    """[KR 09:00] 한국 정규장 개장 주문 집행 (VR 일일 지정가 주문 / CA 차수 갱신 확인)"""
    now_kst = datetime.now(KST)
    if not fetch_kr_holiday():
        return

    logger.info("🔔 [KR 09:00] 한국 정규장 개장! 전략 주문 집행 시작")
    trade_mode = get_trade_mode()
    states = get_all_states_db(market="KR", trade_mode=trade_mode)

    for st in states:
        symbol = st.get("symbol")
        strategy_name = st.get("strategy_name", "")
        strategy_type = st.get("strategy_type", "")

        try:
            broker = get_kr_broker()
            if strategy_type == "VR":
                cfg = VRConfig(
                    symbol=symbol,
                    strategy_type="VR",
                    use_db=True,
                    market="KR",
                    strategy_name=strategy_name
                )
                engine = ValueRebalancingEngine(config=cfg, broker=broker)
                engine.place_daily_limit_orders(date=now_kst, is_cycle_start_day=True, check_existing_orders=True)
                logger.info(f"✅ [KR VR] {strategy_name} 일일 지정가 주문 제출 완료")

            elif strategy_type == "CA":
                cfg = CAConfig(
                    symbol=symbol,
                    strategy_type="CA",
                    use_db=True,
                    market="KR",
                    strategy_name=strategy_name
                )
                engine = CostAveragingEngine(config=cfg, broker=broker)
                # 장 시작 시 전일 매도 후 차수 전환 여부 확인
                if getattr(engine.state, 'pending_cycle_transition', False):
                    engine.run_cycle(date=now_kst, check_existing_orders=True)
                    logger.info(f"✅ [KR CA] {strategy_name} 신규 차수 시작 처리 완료")

        except Exception as e:
            logger.error(f"❌ [KR 주문 오류] {strategy_name}: {e}", exc_info=True)


def job_kr_sell_limit():
    """[KR 10:00] 한국장 CA 75% 지정가 매도 주문 배치"""
    now_kst = datetime.now(KST)
    if not fetch_kr_holiday():
        return

    logger.info("📈 [KR 10:00] CA 전략 75% 지정가 매도 주문 확인")
    trade_mode = get_trade_mode()
    states = get_all_states_db(strategy_type="CA", market="KR", trade_mode=trade_mode)

    for st in states:
        symbol = st.get("symbol")
        strategy_name = st.get("strategy_name", "")
        try:
            cfg = CAConfig(
                symbol=symbol,
                strategy_type="CA",
                use_db=True,
                market="KR",
                strategy_name=strategy_name
            )
            engine = CostAveragingEngine(config=cfg, broker=get_kr_broker())
            engine.run_cycle(date=now_kst, check_existing_orders=True, order_filter="SELL_LIMIT_ONLY")
        except Exception as e:
            logger.error(f"❌ [KR 10:00 매도 오류] {strategy_name}: {e}")


def job_kr_intraday_check():
    """[KR 09:05 ~ 15:20] 한국장 정규시간 내 CA 급락 감시 (5분 주기)"""
    now_kst = datetime.now(KST)
    if not fetch_kr_holiday():
        return

    # 정규장 시간(09:05 ~ 15:20) 확인
    curr_time = now_kst.time()
    if not (datetime.strptime("09:05", "%H:%M").time() <= curr_time <= datetime.strptime("15:20", "%H:%M").time()):
        return

    trade_mode = get_trade_mode()
    states = get_all_states_db(strategy_type="CA", market="KR", trade_mode=trade_mode)

    for st in states:
        symbol = st.get("symbol")
        strategy_name = st.get("strategy_name", "")
        try:
            cfg = CAConfig(
                symbol=symbol,
                strategy_type="CA",
                use_db=True,
                market="KR",
                strategy_name=strategy_name
            )
            engine = CostAveragingEngine(config=cfg, broker=get_kr_broker())
            engine.run_intraday_check()
        except Exception as e:
            logger.debug(f"[KR 장중 감시 스킵/오류] {strategy_name}: {e}")


def job_kr_market_close():
    """[KR 15:20] 한국장 장마감 전 CA 분할 매수 집행 (LOC/종가)"""
    now_kst = datetime.now(KST)
    if not fetch_kr_holiday():
        return

    logger.info("🏁 [KR 15:20] 한국 정규장 마감 10분 전 CA 정기 매수 사이클 집행")
    trade_mode = get_trade_mode()
    states = get_all_states_db(strategy_type="CA", market="KR", trade_mode=trade_mode)

    for st in states:
        symbol = st.get("symbol")
        strategy_name = st.get("strategy_name", "")
        try:
            cfg = CAConfig(
                symbol=symbol,
                strategy_type="CA",
                use_db=True,
                market="KR",
                strategy_name=strategy_name
            )
            engine = CostAveragingEngine(config=cfg, broker=get_kr_broker())
            engine.run_cycle(date=now_kst, check_existing_orders=True)
            logger.info(f"✅ [KR CA 15:20 매수] {strategy_name} 사이클 완료")
        except Exception as e:
            logger.error(f"❌ [KR 15:20 매수 오류] {strategy_name}: {e}", exc_info=True)


def job_kr_daily_summary():
    """[KR 15:40] 한국장 일일 정산 및 텔레그램 일일 리포트 발송"""
    now_kst = datetime.now(KST)
    if not fetch_kr_holiday():
        return

    logger.info("📊 [KR 15:40] 한국장 당일 결산 및 리포트 작성")
    try:
        broker = get_kr_broker()
        cash = broker.get_cash_pool()
        trade_mode = get_trade_mode()
        states = get_all_states_db(market="KR", trade_mode=trade_mode)

        report = f"🇰🇷 <b>[Meritz 한국시장 일일 결산]</b> ({now_kst.strftime('%Y-%m-%d')})\n"
        report += f"원화 예수금: <b>{int(cash):,}원</b>\n\n"
        report += "<b>운용 전략 현황:</b>\n"

        for st in states:
            s_name = st.get("strategy_name", "")
            sym = st.get("symbol", "")
            curr_price = float(st.get("current_price", 0))
            avg_price = float(st.get("avg_price", 0))
            shares = float(st.get("total_shares", 0))
            
            pnl_rate = ((curr_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            turn = st.get("current_turn", 0)
            a_def = st.get("a_default", 40)
            
            report += f"• <b>{s_name}</b> ({sym}): {int(shares)}주 | 평단 {int(avg_price):,}원 | 수익률: <b>{pnl_rate:+.2f}%</b> (회차: {turn}/{a_def})\n"

        send_telegram_message(report)
    except Exception as e:
        logger.error(f"❌ [KR 일일 결산 오류]: {e}")


# ==============================================================================
# [미국 주식 시장 (US) 작업 루틴]
# ==============================================================================

def job_us_pre_market_prep():
    """[US 개장 30분 전] 미국장 개장 전 준비 및 스마트 외화 환전(Auto-Funding)"""
    now_kst = datetime.now(KST)
    if is_us_market_holiday():
        logger.info("⏸️ [US] 오늘은 미국 주식시장 휴장일입니다. 미국장 장전 준비를 건너뜁니다.")
        return

    logger.info("🇺🇸 [US 장전 준비] 미국 정규장 개장 전 점검 및 환전 검토 시작")
    try:
        broker = get_us_broker()
        usd_cash = broker.get_cash_pool()
        logger.info(f"💵 [US] 현재 가용 외화(USD) 예수금: ${usd_cash:,.2f}")

        # 환전 설정이 켜져 있는 경우 부족분 충전(Auto-Funding) 검토
        if settings.FX_AUTO_EXCHANGE:
            logger.info("💱 [US FX Auto-Funding] 미국장 매수 자금 부족 여부 확인...")
            trade_mode = get_trade_mode()
            us_states = get_all_states_db(market="US", trade_mode=trade_mode)

            needed_usd = 0.0
            for st in us_states:
                st_type = st.get("strategy_type", "")
                if st_type == "CA":
                    unit_buy = float(st.get("unit_buy_amount", 0.0))
                    if unit_buy <= 0:
                        budget = float(st.get("cycle_budget", 10000.0))
                        a_def = float(st.get("a_default", 40))
                        unit_buy = budget / a_def if a_def > 0 else 250.0
                    needed_usd += unit_buy
                elif st_type == "VR":
                    needed_usd += 100.0  # VR 기본 완충 버퍼

            if needed_usd > 0:
                forex_manager.ensure_usd_balance(
                    current_usd=usd_cash,
                    required_usd=needed_usd,
                    buffer_usd=settings.FX_BUFFER_USD,
                    strategy_name="US_AutoTrade_Funding"
                )

    except Exception as e:
        logger.error(f"❌ [US 장전 준비 오류]: {e}", exc_info=True)


def job_us_market_open():
    """[US 개장 10분 전] 미국장 VR 지정가 주문 및 CA LOC 주문 제출"""
    now_kst = datetime.now(KST)
    if is_us_market_holiday():
        return

    logger.info("🚀 [US 개장 전] 미국 정규장 전략 주문 전송 시작 (VR 지정가 & CA LOC)")
    trade_mode = get_trade_mode()
    states = get_all_states_db(market="US", trade_mode=trade_mode)

    for st in states:
        symbol = st.get("symbol")
        strategy_name = st.get("strategy_name", "")
        strategy_type = st.get("strategy_type", "")

        try:
            broker = get_us_broker()
            if strategy_type == "VR":
                cfg = VRConfig(
                    symbol=symbol,
                    strategy_type="VR",
                    use_db=True,
                    market="US",
                    strategy_name=strategy_name
                )
                engine = ValueRebalancingEngine(config=cfg, broker=broker)
                engine.place_daily_limit_orders(date=now_kst, is_cycle_start_day=True, check_existing_orders=True)
                logger.info(f"✅ [US VR] {strategy_name} 일일 지정가 주문 제출 완료")

            elif strategy_type == "CA":
                cfg = CAConfig(
                    symbol=symbol,
                    strategy_type="CA",
                    use_db=True,
                    market="US",
                    strategy_name=strategy_name
                )
                engine = CostAveragingEngine(config=cfg, broker=broker)
                engine.run_cycle(date=now_kst, check_existing_orders=True)
                logger.info(f"✅ [US CA] {strategy_name} LOC/지정가 주문 제출 완료")

        except Exception as e:
            logger.error(f"❌ [US 주문 오류] {strategy_name}: {e}", exc_info=True)


def job_us_intraday_check():
    """[US 정규장 중] 미국장 CA 장중 급락 감시 (5분 주기)"""
    now_kst = datetime.now(KST)
    if is_us_market_holiday():
        return

    # 서머타임에 따른 정규장 시간 체크
    is_dst = is_us_dst()
    curr_time = now_kst.time()

    if is_dst:
        # 서머타임: 22:35 ~ 04:55
        is_market_hours = (curr_time >= datetime.strptime("22:35", "%H:%M").time() or
                           curr_time <= datetime.strptime("04:55", "%H:%M").time())
    else:
        # 표준시: 23:35 ~ 05:55
        is_market_hours = (curr_time >= datetime.strptime("23:35", "%H:%M").time() or
                           curr_time <= datetime.strptime("05:55", "%H:%M").time())

    if not is_market_hours:
        return

    trade_mode = get_trade_mode()
    states = get_all_states_db(strategy_type="CA", market="US", trade_mode=trade_mode)

    for st in states:
        symbol = st.get("symbol")
        strategy_name = st.get("strategy_name", "")
        try:
            cfg = CAConfig(
                symbol=symbol,
                strategy_type="CA",
                use_db=True,
                market="US",
                strategy_name=strategy_name
            )
            engine = CostAveragingEngine(config=cfg, broker=get_us_broker())
            engine.run_intraday_check()
        except Exception as e:
            logger.debug(f"[US 장중 감시 스킵/오류] {strategy_name}: {e}")


def job_us_market_close():
    """[US 정규장 마감 후] 미국장 일일 정산 및 텔레그램 일일 리포트 발송"""
    now_kst = datetime.now(KST)
    if is_us_market_holiday():
        return

    logger.info("🏁 [US 장마감] 미국 정규장 결산 및 일일 리포트 작성")
    try:
        broker = get_us_broker()
        usd_cash = broker.get_cash_pool()
        trade_mode = get_trade_mode()
        states = get_all_states_db(market="US", trade_mode=trade_mode)

        report = f"🇺🇸 <b>[Meritz 미국시장 일일 결산]</b> ({now_kst.strftime('%Y-%m-%d')})\n"
        report += f"USD 예수금: <b>${usd_cash:,.2f}</b>\n\n"
        report += "<b>운용 전략 현황:</b>\n"

        for st in states:
            s_name = st.get("strategy_name", "")
            sym = st.get("symbol", "")
            curr_price = float(st.get("current_price", 0))
            avg_price = float(st.get("avg_price", 0))
            shares = float(st.get("total_shares", 0))
            
            pnl_rate = ((curr_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            st_type = st.get("strategy_type", "")
            
            if st_type == "CA":
                turn = st.get("current_turn", 0)
                a_def = st.get("a_default", 40)
                report += f"• <b>{s_name}</b> ({sym}): {int(shares)}주 | 평단 ${avg_price:,.2f} | 수익률: <b>{pnl_rate:+.2f}%</b> (회차: {turn}/{a_def})\n"
            else: # VR
                v_val = float(st.get("V", 0.0))
                pool_val = float(st.get("pool", 0.0))
                report += f"• <b>{s_name}</b> ({sym}): {int(shares)}주 | V: ${v_val:,.1f} | Pool: ${pool_val:,.1f} | 수익률: <b>{pnl_rate:+.2f}%</b>\n"

        send_telegram_message(report)
    except Exception as e:
        logger.error(f"❌ [US 일일 결산 오류]: {e}")


def job_heartbeat():
    """[30분 주기] 스케줄러 작동 하트비트 로깅"""
    now_kst = datetime.now(KST)
    read_only_msg = " [READ ONLY (모의)]" if settings.MERITZ_READ_ONLY else " [REAL TRADING]"
    logger.info(f"💓 [Heartbeat] Meritz CAVR Scheduler 정상 구동 중 ({now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}){read_only_msg}")


# ==============================================================================
# [대시보드 수동 실행 및 개별 전략 실행 헬퍼]
# ==============================================================================

def job_update_exchange_rate(broker=None, force=False, is_market_open=False):
    """메리츠 외환 관리자를 사용하여 실시간 고시환율을 조회하고 DB에 저장"""
    try:
        from core.database import (
            save_exchange_rate_db,
            get_exchange_rate_by_date_db,
            get_previous_exchange_rate_db,
            set_config
        )
        if broker is None:
            broker = get_us_broker()

        fx_info = broker.get_exchange_rate(force=force)
        if not fx_info or fx_info.get("rate", 0) <= 0:
            logger.warning("⚠️ [FX 갱신] 환율 정보를 가져오지 못했습니다.")
            return None

        rate = float(fx_info["rate"])
        diff = float(fx_info.get("diff", 0.0))
        pct = float(fx_info.get("pct", 0.0))
        base_rate = float(fx_info.get("base_rate", rate - diff))
        trade_date = datetime.now(KST).strftime("%Y-%m-%d")
        now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        set_config("USDKRW", f"{rate:.2f}")
        set_config("USDKRW_DIFF", f"{diff:+.2f}")
        set_config("USDKRW_PCT", f"{pct:+.2f}")
        set_config("USDKRW_UPDATE_TIME", now_str)

        save_exchange_rate_db(
            trade_date=trade_date,
            recorded_at=now_str,
            rate=rate,
            base_rate=base_rate,
            diff=diff,
            pct=pct,
            source=fx_info.get("source", "MERITZ_FOREX")
        )
        logger.info(f"💱 [FX 갱신] USD/KRW = {rate:,.2f}원 ({diff:+.2f}원, {pct:+.2f}%)")
        return {"rate": rate, "diff": diff, "pct": pct}
    except Exception as e:
        logger.error(f"❌ [FX 갱신 실패]: {e}")
        return None

def run_ca_strategies(market: str = "US", check_existing: bool = False, force: bool = False, order_filter: str = None, transition_only: bool = False, broker=None):
    """DB에 저장된 CA 전략 실행"""
    if broker is None:
        broker = get_kr_broker() if market == "KR" else get_us_broker()
    trade_mode = get_trade_mode()
    states = get_all_states_db(strategy_type="CA", market=market, trade_mode=trade_mode)
    results = []
    for st in states:
        if not st.get("is_active", True) and not force:
            continue
        sym = st.get("symbol")
        alias = st.get("strategy_name")
        try:
            cfg = CAConfig(symbol=sym, use_db=True, market=market, strategy_name=alias)
            eng = CostAveragingEngine(cfg, broker=broker)
            orders = eng.run_cycle(datetime.now(), check_existing_orders=check_existing, preview=False)
            results.append((alias, orders))
        except Exception as e:
            logger.error(f"❌ [CA 실행 오류] {alias}: {e}")
    return results

def run_vr_strategies(market: str = "US", check_existing: bool = False, force: bool = False, order_filter: str = None, broker=None):
    """DB에 저장된 VR 전략 실행"""
    if broker is None:
        broker = get_kr_broker() if market == "KR" else get_us_broker()
    trade_mode = get_trade_mode()
    states = get_all_states_db(strategy_type="VR", market=market, trade_mode=trade_mode)
    results = []
    for st in states:
        if not st.get("is_active", True) and not force:
            continue
        sym = st.get("symbol")
        alias = st.get("strategy_name")
        try:
            cfg = VRConfig(symbol=sym, use_db=True, market=market, strategy_name=alias)
            eng = ValueRebalancingEngine(cfg, broker=broker)
            orders = eng.place_daily_limit_orders(datetime.now(), contribution=0.0, is_cycle_start_day=False, check_existing_orders=check_existing, preview=False)
            results.append((alias, orders))
        except Exception as e:
            logger.error(f"❌ [VR 실행 오류] {alias}: {e}")
    return results

# ==============================================================================
# [스케줄러 메인 실행부]
# ==============================================================================

def setup_scheduler() -> BlockingScheduler:
    """APScheduler 작업 등록"""
    scheduler = BlockingScheduler(timezone=KST)

    # 1. 공통 하트비트 (매 30분)
    scheduler.add_job(job_heartbeat, IntervalTrigger(minutes=30, timezone=KST), id="job_heartbeat")

    # 2. 한국 주식 시장 스케줄 (월~금)
    scheduler.add_job(job_kr_morning_prep, CronTrigger(day_of_week='mon-fri', hour=8, minute=50, timezone=KST), id="kr_prep")
    scheduler.add_job(job_kr_market_open, CronTrigger(day_of_week='mon-fri', hour=9, minute=0, timezone=KST), id="kr_open")
    scheduler.add_job(job_kr_sell_limit, CronTrigger(day_of_week='mon-fri', hour=10, minute=0, timezone=KST), id="kr_sell_limit")
    scheduler.add_job(job_kr_intraday_check, IntervalTrigger(minutes=5, timezone=KST), id="kr_intraday")
    scheduler.add_job(job_kr_market_close, CronTrigger(day_of_week='mon-fri', hour=15, minute=20, timezone=KST), id="kr_close")
    scheduler.add_job(job_kr_daily_summary, CronTrigger(day_of_week='mon-fri', hour=15, minute=40, timezone=KST), id="kr_summary")

    # 3. 미국 주식 시장 스케줄 (월~금 밤)
    # 서머타임(22:30 개장) 및 표준시(23:30 개장) 둘 다 대응하도록 장전 준비 및 개장 트리거 등록
    scheduler.add_job(job_us_pre_market_prep, CronTrigger(day_of_week='mon-fri', hour=22, minute=0, timezone=KST), id="us_prep_dst")
    scheduler.add_job(job_us_market_open, CronTrigger(day_of_week='mon-fri', hour=22, minute=20, timezone=KST), id="us_open_dst")
    scheduler.add_job(job_us_pre_market_prep, CronTrigger(day_of_week='mon-fri', hour=23, minute=0, timezone=KST), id="us_prep_std")
    scheduler.add_job(job_us_market_open, CronTrigger(day_of_week='mon-fri', hour=23, minute=20, timezone=KST), id="us_open_std")

    # 미국 장중 급락 감시 (매 5분)
    scheduler.add_job(job_us_intraday_check, IntervalTrigger(minutes=5, timezone=KST), id="us_intraday")

    # 미국 장 마감 정산 (화~토 새벽 05:10 및 06:10)
    scheduler.add_job(job_us_market_close, CronTrigger(day_of_week='tue-sat', hour=5, minute=10, timezone=KST), id="us_close_dst")
    scheduler.add_job(job_us_market_close, CronTrigger(day_of_week='tue-sat', hour=6, minute=10, timezone=KST), id="us_close_std")

    return scheduler


def main():
    logger.info("==================================================")
    logger.info("   Meritz Open API CAVR 자동매매 스케줄러 시작   ")
    logger.info("==================================================")
    logger.info(f"• 현재 KST 시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"• READ_ONLY 모드: {settings.MERITZ_READ_ONLY} (1=모의주문/모의환전, 0=실거래)")
    logger.info(f"• 텔레그램 알림 활성화: {settings.NOTIFIER_ENABLED}")
    logger.info(f"• 자동 환전(FX_AUTO_EXCHANGE): {settings.FX_AUTO_EXCHANGE}")

    # DB 초기화 및 기본 전략 확인
    init_db(run_maintenance=True)
    ensure_default_strategies_exist()

    scheduler = setup_scheduler()

    # 안전 종료 시그널 핸들러 등록
    def handle_exit(signum, frame):
        logger.info(f"\n🛑 종료 시그널({signum}) 수신. 스케줄러를 안전하게 중지합니다.")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    send_telegram_message("🚀 <b>[Meritz CAVR 스케줄러 가동]</b> 자동매매 백그라운드 엔진이 정상 시작되었습니다.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러가 정상 종료되었습니다.")


if __name__ == "__main__":
    main()
