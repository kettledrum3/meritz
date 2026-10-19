import streamlit as st
import sqlite3
st.set_page_config(page_title="메리츠CAVR Dashboard", layout="wide")

import pandas as pd
import os
import math
import sys
import time
import re
import plotly.graph_objects as go
from datetime import datetime, time as dtime, timedelta
import pytz
import logging
from logging.handlers import RotatingFileHandler
import html
from dotenv import load_dotenv, set_key


# 로거 설정
logger = logging.getLogger(__name__)

# 프로젝트 루트 경로 추가
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)

# 공통 환경 변수 로드
load_dotenv(os.path.join(PROJECT_ROOT, "env", ".env"))

# --- 로깅 설정 및 핸들러 정의 ---
def setup_logging():
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "error_log.txt")

    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    err_handler = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(formatter)
    root_logger.addHandler(err_handler)

    msg_log_file = os.path.join(log_dir, "message_log.txt")
    msg_handler = RotatingFileHandler(msg_log_file, maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
    msg_handler.setLevel(logging.INFO)
    msg_handler.setFormatter(formatter)
    root_logger.addHandler(msg_handler)
    
    st_handler = StreamlitLogHandler()
    st_handler.setFormatter(formatter)
    root_logger.addHandler(st_handler)

    # 메리츠 OpenAPI 저수준 HTTP 통신 로그(GET ... -> ok) 및 urllib3 노이즈 억제 (WARNING 이상만 기록)
    logging.getLogger("meritz").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

class StreamlitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        # 로컬 세션에도 남기지만, 이제 파일에서 읽어오므로 보조 수단으로 사용
        try:
            if "log_messages" not in st.session_state:
                st.session_state.log_messages = []
            st.session_state.log_messages.append(msg)
        except: pass

setup_logging()

def safe_float(val, default=0.0):
    try:
        if val is None or str(val).strip() == "":
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

# --- 모듈 임포트 (데이터베이스 관련 임포트를 호출부 위로 이동) ---
from core.database import (
    get_all_states_db, save_state_db, get_detailed_trade_history_db, migrate_sync_trades_db, get_order_history_db, sync_open_orders_db,
    load_state_db, init_db, get_config, set_config, delete_strategy_db, finish_strategy_db, get_finished_states_db, rename_strategy_db, sync_trade_history_db, migrate_manual_trades_db,
    save_ui_settings_db, load_ui_settings_db, cleanup_invalid_orders_db, cleanup_processed_orders_db,
    recalculate_all_profits_db, get_trade_mode
)

# --- 세션 상태 초기화 (AttributeError 방지) ---
init_db(run_maintenance=False) 

# --- 세션 상태 초기화 (AttributeError 방지) ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "temp_pass_mode" not in st.session_state:
    st.session_state.temp_pass_mode = False
if "log_messages" not in st.session_state:
    st.session_state.log_messages = []
if "planned_orders" not in st.session_state:
    st.session_state.planned_orders = []
if "last_activity" not in st.session_state:
    st.session_state.last_activity = time.time()
if "remembered_username" not in st.session_state:
    st.session_state.remembered_username = get_config("last_logged_in_user", "")
if "auth_trace" not in st.session_state:
    st.session_state.auth_trace = []
if "pending_market_selector_update" not in st.session_state:
    st.session_state.pending_market_selector_update = None
if "pending_symbol_update" not in st.session_state:
    st.session_state.pending_symbol_update = None
if "pending_alias_update" not in st.session_state:
    st.session_state.pending_alias_update = None
if "pending_strat_update" not in st.session_state:
    st.session_state.pending_strat_update = None

st.session_state.auth_trace.append(f"Run started at {datetime.now().strftime('%H:%M:%S')}")

# --- [FIX] 위젯이 렌더링되기 전에 대기 중인 UI 업데이트 프로세싱 ---
t_mode_val = get_trade_mode().lower()

if st.session_state.pending_market_selector_update is not None:
    st.session_state["market_selector"] = st.session_state.pending_market_selector_update
    st.session_state.pending_market_selector_update = None

if st.session_state.pending_strat_update is not None:
    p = st.session_state.pending_strat_update
    m_key = f"{t_mode_val}_{p['m_code'].lower()}_strat"
    st.session_state[m_key] = p['strat']
    st.session_state.pending_strat_update = None

if st.session_state.pending_symbol_update is not None:
    p = st.session_state.pending_symbol_update
    m_key = f"{t_mode_val}_{p['m_code'].lower()}_{p['strat'].lower()}_symbol_sel"
    st.session_state[m_key] = p['symbol']
    slot_key = f"target_{p['m_code'].lower()}_{p['strat'].lower()}"
    if slot_key not in st.session_state:
        st.session_state[slot_key] = {}
    st.session_state[slot_key]['symbol'] = p['symbol']
    st.session_state.pending_symbol_update = None

if st.session_state.pending_alias_update is not None:
    p = st.session_state.pending_alias_update
    m_key = f"{t_mode_val}_{p['m_code'].lower()}_{p['strat'].lower()}_alias_sel"
    st.session_state[m_key] = p['alias']
    slot_key = f"target_{p['m_code'].lower()}_{p['strat'].lower()}"
    if slot_key not in st.session_state:
        st.session_state[slot_key] = {}
    st.session_state[slot_key]['alias'] = p['alias']
    st.session_state.pending_alias_update = None

# 자동 로그아웃 체크 (1시간 = 3600초)
if st.session_state.authenticated:
    if time.time() - st.session_state.last_activity > 3600:
        st.session_state.authenticated = False
        st.warning("⚠️ 세션이 만료되었습니다. 다시 로그인해주세요.")
        time.sleep(2)
        st.rerun()
    else:
        # 활동 시간 업데이트
        st.session_state.last_activity = time.time()

# --- 모듈 임포트 (상단으로 이동) ---
from dotenv import load_dotenv, set_key
from config.settings import settings
from core.cavr import CAConfig, CAState, CostAveragingEngine, VRConfig, VRState, ValueRebalancingEngine
from core.backtest import run_backtest
from core.fetch_data import update_ticker_data
from core.auth import (
    update_user_email, generate_otp, verify_otp, check_login, register_user, update_password, reset_password_request,
    save_ip_session, get_ip_session, clear_ip_session
)
from core.notifier import send_telegram_message
from core.scheduler import run_ca_strategies, run_vr_strategies, job_update_exchange_rate # 스케줄러 로직 직접 호출을 위해 임포트
from core.database import (
    get_exchange_rate_history_db, get_latest_exchange_rate_db, get_forex_history_db,
    save_forex_strategy_state_db, load_forex_strategy_state_db
)
from core.forex import forex_manager, forex_dca_engine
import glob
import json
import base64

def get_logo_html(height: int = 32, margin_right: int = 8, align: str = "middle") -> str:
    """메리츠 공식 로고의 base64 HTML 태그 반환 (인라인 헤더/타이틀용)"""
    logo_file = os.path.join(PROJECT_ROOT, "meritz_logo.png")
    if os.path.exists(logo_file):
        try:
            with open(logo_file, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f'<img src="data:image/png;base64,{b64}" style="height:{height}px; vertical-align:{align}; margin-right:{margin_right}px; object-fit:contain; display:inline-block;" />'
        except Exception:
            pass
    return ""

def get_client_ip() -> str:
    """Streamlit 요청 헤더 또는 런타임에서 접속 클라이언트 IP 추출"""
    try:
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            headers = st.context.headers
            if headers:
                fwd = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
                if fwd:
                    return fwd.split(",")[0].strip()
                remote = headers.get("remote-addr") or headers.get("Remote-Addr")
                if remote:
                    return remote.strip()
    except Exception:
        pass

    # 구버전 Streamlit fallback (동적 import로 IDE 정적 분석 에러 방지)
    try:
        import importlib
        ws_mod = importlib.import_module("streamlit.web.server.websocket_headers")
        _get_websocket_headers = getattr(ws_mod, "_get_websocket_headers", None)
        if _get_websocket_headers:
            headers = _get_websocket_headers()
            if headers:
                fwd = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
                if fwd:
                    return fwd.split(",")[0].strip()
                remote = headers.get("Remote-Addr") or headers.get("remote-addr")
                if remote:
                    return remote.strip()
    except Exception:
        pass

    return "127.0.0.1"

# 동일 IP 기반 자동 로그인 체크 (대시보드 재실행 시 로그인 유지)
_client_ip = get_client_ip()
if not st.session_state.authenticated and not st.session_state.temp_pass_mode:
    _saved_ip_session = get_ip_session(_client_ip)
    if _saved_ip_session:
        st.session_state.authenticated = True
        st.session_state.user_email = _saved_ip_session["email"]
        st.session_state.username = _saved_ip_session["username"]
        st.session_state.remembered_username = _saved_ip_session["username"]
        st.session_state.last_activity = time.time()
        st.session_state.auth_trace.append(f"Auto-login via IP: {_client_ip} ({_saved_ip_session['username']})")

        # UI 설정 복원
        l_market, l_symbol, l_alias = load_ui_settings_db(_saved_ip_session["email"])
        kr_now = datetime.now(pytz.timezone('Asia/Seoul'))
        kr_opnd_yn = get_config("kr_market_opnd_yn", "Y")
        us_opnd_yn = get_config("us_market_opnd_yn", "Y")
        
        selected_market_for_session = None
        if 8 <= kr_now.hour < 17 and kr_opnd_yn == "Y":
            selected_market_for_session = "한국 시장"
        elif us_opnd_yn == "Y":
            selected_market_for_session = "미국 시장"
        if not selected_market_for_session:
            selected_market_for_session = l_market if l_market else "미국 시장"
            
        if "market_selector" not in st.session_state:
            st.session_state["market_selector"] = selected_market_for_session
        if l_symbol and "last_loaded_symbol" not in st.session_state:
            st.session_state["last_loaded_symbol"] = l_symbol
        if l_alias and "last_loaded_alias" not in st.session_state:
            st.session_state["last_loaded_alias"] = l_alias

# KIS 주문 유형 코드 매핑 (cavr.py와 동일하게 유지)
ORDER_TYPE_MAP = {
    # 미국주식 (ust20000/ust20001)
    "00": "지정가",
    "03": "시장가",
    "26": "VWAP지정가",
    "27": "TWAP지정가",
    "30": "LOC / 중간가(IOC)",
    "33": "MOC",
    "36": "VWAP시장가",
    "37": "TWAP시장가",
    "35": "STOP",
    "34": "STOP LIMIT",

    # 국내주식 (kt10000/kt10001)
    "0": "보통",
    "3": "시장가",
    "5": "조건부지정가",
    "81": "장마감후시간외",
    "61": "장시작전시간외",
    "62": "시간외단일가",
    "6": "최유리지정가",
    "7": "최우선지정가",
    "10": "보통(IOC)",
    "13": "시장가(IOC)",
    "16": "최유리(IOC)",
    "20": "보통(FOK)",
    "23": "시장가(FOK)",
    "26": "최유리(FOK)",
    "28": "스톱지정가",
    "29": "중간가",
    "31": "중간가(FOK)",
}

st.session_state.auth_trace.append(f"Auth Check: auth={st.session_state.authenticated}, temp={st.session_state.temp_pass_mode}")

if not st.session_state.authenticated:
    logo_file = os.path.join(PROJECT_ROOT, "meritz_logo.png")
    if os.path.exists(logo_file):
        st.image(logo_file, width=220)
    st.title("🔐 메리츠CAVR 시스템 로그인")
    auth_mode = st.radio("모드 선택", ["로그인", "회원가입"], horizontal=True)
    
    with st.container(border=True):
        if auth_mode == "로그인":
            with st.form("login_form", clear_on_submit=False):
                login_user = st.text_input("사용자 이름", value=st.session_state.remembered_username, key="login_username")
                password = st.text_input("비밀번호", type="password", key="login_pw")
                submit_btn = st.form_submit_button("로그인", width='stretch', type="primary")
            
            if submit_btn:
                st.session_state.auth_trace.append(f"Login button clicked for {login_user}")
                res = check_login(login_user, password)
                if res and res["status"] == "success":
                    st.session_state.remembered_username = login_user # 사용자명 기억
                    set_config("last_logged_in_user", login_user) # DB에 영구 기억
                    if res["is_temp"]:
                        st.session_state.auth_trace.append("Temporary password detected")
                        st.session_state.temp_pass_mode = True
                        st.session_state.user_email = res["email"]
                        # 임시 비번 모드 활성화를 위해 리런하지 않고 아래 비번 변경 UI를 보여줌
                        st.rerun() 
                    else:
                        st.session_state.auth_trace.append("Auth success, setting session state")
                        st.session_state.authenticated = True
                        st.session_state.user_email = res["email"]
                        st.session_state.username = res["username"]
                        st.session_state.last_activity = time.time() # 세션 시작 시간 설정
                        
                        # [ADD] 클라이언트 IP 기반 세션 저장 (대시보드 재실행 시 자동 로그인 유지)
                        save_ip_session(get_client_ip(), res["username"], res["email"])

                        send_telegram_message(f"🔓 <b>{res['username']}</b>님이 대시보드에 접속했습니다.")
                        
                        # [UI 복원 로직 추가]
                        l_market, l_symbol, l_alias = load_ui_settings_db(res["email"])
                        
                        # [FIX] 시장 자동 활성화 로직 개선 (한국 우선순위, 휴장일 고려)
                        kr_now = datetime.now(pytz.timezone('Asia/Seoul'))
                        kr_opnd_yn = get_config("kr_market_opnd_yn", "Y")
                        us_opnd_yn = get_config("us_market_opnd_yn", "Y")
                        
                        selected_market_for_session = None
                        
                        # 1. 한국 시장 우선 감지 (오전 8시 ~ 오후 5시 사이이며 개장일인 경우)
                        if 8 <= kr_now.hour < 17 and kr_opnd_yn == "Y":
                            selected_market_for_session = "한국 시장"
                        # 2. 그 외 시간대이고 미국 시장이 개장일인 경우 (미국 프리마켓 포함)
                        elif us_opnd_yn == "Y":
                            selected_market_for_session = "미국 시장"
                        
                        # [보정] 만약 위 조건으로 결정되지 않았거나 기존 저장된 값이 있다면 저장값 우선순위 고려
                        if not selected_market_for_session:
                            selected_market_for_session = l_market if l_market else "미국 시장"
                        
                        st.session_state["market_selector"] = selected_market_for_session if selected_market_for_session else "미국 시장" # 기본값 설정
                        
                        if l_symbol: st.session_state["last_loaded_symbol"] = l_symbol
                        if l_alias: st.session_state["last_loaded_alias"] = l_alias

                        st.rerun()
                elif res and res["status"] == "locked":
                    # [ADD] 시장 자동 활성화 시간대 (한국 우선순위)
                    kr_now = datetime.now(pytz.timezone('Asia/Seoul'))
                    ny_now = datetime.now(pytz.timezone('America/New_York'))
                    if 8 <= kr_now.hour < 17: st.session_state["market_selector"] = "한국 시장"
                    elif 4 <= ny_now.hour < 20: st.session_state["market_selector"] = "미국 시장"
                    st.error(res["msg"])
                else:
                    st.error(res["msg"] if res else "계정 정보가 없습니다.")
            
            if st.button("🔑 비밀번호 재설정", width='stretch'):
                if login_user and "@" in login_user: # 사용자 이름 칸에 이메일 형식을 입력한 경우
                    if reset_password_request(login_user):
                        st.info("이메일로 임시 비밀번호를 발송했습니다. 확인 후 로그인하세요.")
                    else: st.error("등록되지 않은 이메일입니다.")
                else: st.warning("비밀번호 재설정을 위해 '사용자 이름' 칸에 가입 시 사용한 이메일을 입력해주세요.")

            if st.session_state.temp_pass_mode:
                st.divider()
                st.subheader("🆕 새 비밀번호 설정")
                new_pw = st.text_input("새 비밀번호", type="password")
                confirm_pw = st.text_input("새 비밀번호 확인", type="password")
                if st.button("비밀번호 변경 및 완료"):
                    if new_pw != confirm_pw:
                        st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        success, message = update_password(st.session_state.user_email, new_pw)
                        if success:
                            st.success(message)
                            st.session_state.temp_pass_mode = False
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(message)
                            
        else:
            username = st.text_input("사용자 이름")
            email = st.text_input("이메일 주소") # 회원가입 시 이메일 입력 필드 추가
            if st.button("회원가입 신청", width='stretch'):
                if email and username:
                    if register_user(username, email):
                        st.success("회원가입 완료! 이메일로 발송된 임시 비밀번호로 로그인하세요.")
                        time.sleep(2)
                    else: st.error("이미 등록된 이메일이거나 오류가 발생했습니다.")
                else: st.error("이름과 이메일을 모두 입력해주세요.")
    st.sidebar.expander("Debug Trace").write(st.session_state.auth_trace)
    st.stop() # 인증되지 않은 경우 여기서 실행 중단

st.session_state.auth_trace.append("Authentication Passed - Starting Main App")

# 로그아웃 버튼 (사이드바 하단용 미리 정의)
def handle_logout():
    clear_ip_session(get_client_ip())
    st.session_state.authenticated = False
    st.rerun()

# --- 데이터 로드 함수 (시장 코드에 따라 동적 호출) ---
def get_market_tickers(m_code):
    """m_code: 'US' 또는 'KR'"""
    etf_data = {}
    try:
        file_name = f"ETF_list_{m_code.lower()}.txt"
        etf_path = os.path.join(PROJECT_ROOT, "env", file_name)
        if os.path.exists(etf_path):
            with open(etf_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.split('#')[0].strip()
                    if line:
                        # '122630 "KODEX 레버리지"' 또는 'TQQQ' 형식 처리
                        parts = line.split(None, 1)
                        ticker = parts[0].upper()
                        name = parts[1].strip().strip('"') if len(parts) > 1 else ticker
                        etf_data[ticker] = name
                # 만약 파일이 비어있거나 읽지 못했다면 기본값 반환
                if not etf_data:
                    if m_code == "US": return {"TQQQ": "TQQQ", "SOXL": "SOXL"}
                    if m_code == "KR": return {"005930": "삼성전자", "122630": "KODEX 레버리지"}
    except Exception as e:
        logger.error(f"[{m_code}] ETF 리스트 로드 실패: {e}")
        if m_code == "US": return {"TQQQ": "TQQQ", "SOXL": "SOXL"}
        if m_code == "KR": return {"005930": "삼성전자", "122630": "KODEX 레버리지"}
    
    # 파일 로드가 끝난 후에도 비어있으면 기본값 반환
    if not etf_data:
        if m_code == "US": return {"TQQQ": "TQQQ", "SOXL": "SOXL"}
        if m_code == "KR": return {"005930": "삼성전자", "122630": "KODEX 레버리지"}
    return etf_data

def check_market_active(m_code):
    """시장별 운영 시간 및 주말 여부 체크"""
    trade_mode = get_trade_mode()
    if m_code == "KR":
        tz = pytz.timezone('Asia/Seoul')
        if trade_mode == "MOCK":
            open_time, close_time = dtime(9, 0), dtime(15, 30)
        else:
            open_time, close_time = dtime(7, 20), dtime(16, 40)
    else:
        tz = pytz.timezone('America/New_York')
        if trade_mode == "MOCK":
            open_time, close_time = dtime(9, 30), dtime(16, 0)
        else:
            open_time, close_time = dtime(7, 0), dtime(18, 0) # [수정] US 시장 활성화 시간 조정 (07:00 ET ~ 18:00 ET)
    
    now = datetime.now(tz)
    if now.weekday() >= 5: # 토, 일
        return False, now
    return open_time <= now.time() <= close_time, now

def format_currency(val, m_code):
    """시장별 통화 포맷팅 (KR은 소수점 제거, US는 소수점 2자리, 공통 천단위 콤마)"""
    try:
        num_val = float(val)
        if m_code == "KR":
            return f"{int(num_val):,}"
        return f"{num_val:,.2f}"
    except (ValueError, TypeError):
        return str(val)

def format_ticker_display(t, m_code):
    """종목 코드와 이름을 보기 좋게 포맷팅"""
    m_tickers = get_market_tickers(m_code)
    name = m_tickers.get(t, t)
    if name and name != t:
        return f"{t} ({name})"
    return t

# 1. 심박 확인 (30초마다 독립적으로 갱신되는 프래그먼트)
@st.fragment(run_every=30)
def display_heartbeat():
    last_hb_str = get_config("scheduler_heartbeat")
    current_status = get_config("scheduler_status", "stopped")
    is_alive = False
    last_hb_time = ""

    if last_hb_str:
        try:
            last_hb = datetime.strptime(last_hb_str, "%Y-%m-%d %H:%M:%S")
            # 3분 이내에 심박이 있으면 프로세스가 살아있는 것으로 판정
            if datetime.now() - last_hb < timedelta(minutes=3):
                is_alive = True
            last_hb_time = last_hb_str.split()[-1]
        except:
            pass

    if is_alive:
        if current_status == "running":
            st.success(f"🟢 프로세스 정상 동작 중 (심박: {last_hb_time})")
        else:
            st.warning(f"🟡 프로세스 대기 중 (심박: {last_hb_time} | [▶ 실행] 필요)")
    else:
        st.error("🔴 프로세스 응답 없음 (scheduler.py 실행 필요)")
        st.caption("※ 백그라운드 데몬 또는 터미널에서 `python -m core.scheduler`를 실행하세요.")

# --- 사이드바 스케줄러 제어 ---
def display_scheduler_control():
    st.sidebar.markdown("---")
    st.sidebar.subheader("🕹️ 스케줄러 제어")

    with st.sidebar:
        display_heartbeat()

    # 2. 동작 상태 제어 (ON/OFF)
    current_status = get_config("scheduler_status", "stopped")

    col_s1, col_s2 = st.sidebar.columns(2)
    if col_s1.button("▶ 실행", type="primary" if current_status=="stopped" else "secondary", width='stretch'):
        set_config("scheduler_status", "running")
        st.rerun()
    if col_s2.button("⏹ 정지", type="primary" if current_status=="running" else "secondary", width='stretch'):
        set_config("scheduler_status", "stopped")
        st.rerun()

    status_msg = "🟢 가동 중 (Running)" if current_status == "running" else "🔴 정지됨 (Stopped)"
    st.sidebar.info(f"운영 설정: **{status_msg}**")

    # 3. 수동 실행 (Manual Trigger with Preview)
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚡ 수동 주문 제어")
    
    # 주문 계획 세션 상태 초기화
    if "planned_orders" not in st.session_state:
        st.session_state.planned_orders = []

    # [1단계] 주문 계획 생성 (Preview)
    if st.sidebar.button("📋 주문 계획 생성 (Preview)", help="실제 주문 전에 매매 계획을 시뮬레이션하여 보여줍니다."):
        planned = []
        
        # CA 전략 프리뷰
        try:
            ca_states = get_all_states_db("CA", market=market_code, strategy_name=strategy_alias)
            for state in ca_states:
                sym = state.get('symbol')
                try:
                    # [수정] 현재 선택된 별칭(strategy_alias) 정보를 사용하여 Config 생성
                    cfg = CAConfig(symbol=sym, use_db=True, market=market_code, strategy_name=state.get('strategy_name'))
                    eng = CostAveragingEngine(cfg, broker=ActiveBroker)
                    # preview=True로 호출하여 계획만 가져옴
                    orders = eng.run_cycle(datetime.now(), check_existing_orders=True, preview=True)
                    if orders:
                        planned.extend(orders)
                except Exception as e:
                    st.sidebar.error(f"{sym} CA 계획 생성 오류: {e}")
        except Exception as ex:
            st.sidebar.error(f"CA 전략 조회 오류: {ex}")
        
        # VR 전략 프리뷰
        try:
            vr_states = get_all_states_db("VR", market=market_code, strategy_name=strategy_alias)
            for state in vr_states:
                sym = state.get('symbol')
                try:
                    cfg = VRConfig(symbol=sym, use_db=True, market=market_code, strategy_name=state.get('strategy_name'))
                    eng = ValueRebalancingEngine(cfg, broker=ActiveBroker)
                    # preview=True
                    orders = eng.place_daily_limit_orders(datetime.now(), contribution=0.0, is_cycle_start_day=False, check_existing_orders=True, preview=True)
                    if orders:
                        planned.extend(orders)
                except Exception as e:
                    st.sidebar.error(f"{sym} VR 계획 생성 오류: {e}")
        except Exception as ex:
            st.sidebar.error(f"VR 전략 조회 오류: {ex}")
        
        st.session_state.planned_orders = planned
        if not planned:
            st.sidebar.info("생성된 주문 계획이 없습니다. (조건 미충족 등)")
        else:
            st.sidebar.success(f"총 {len(planned)}건의 주문 계획이 생성되었습니다.")
            st.rerun() # 메인 화면 갱신을 위해 리런

# 사이드바 상태 요약 표시 함수
def display_sidebar_summary(m_display, m_code):
    st.sidebar.markdown("---")
    st.sidebar.subheader(f"📊 {m_display} 투자 현황 (전략별)")
    
    # 현재 활성화된 거래 모드 (REAL 또는 MOCK) 가져오기
    t_mode = get_trade_mode()
    
    # DB에서 현재 거래 모드(MOCK/REAL)에 맞는 활성 전략 상태만 로드하여 백테스트를 요약에서 제외
    states_ca = get_all_states_db("CA", market=m_code, trade_mode=t_mode)
    states_vr = get_all_states_db("VR", market=m_code, trade_mode=t_mode)
    states = states_ca + states_vr
    
    if not states:
        st.sidebar.caption("DB에 저장된 전략이 없습니다.")
        return

    for state in states:
        try:
            stype = state.get('strategy_type', '?')
            sym = state.get('symbol')
            alias = state.get('strategy_name', '')
            is_active = state.get('is_active', True)

            status_prefix = "🟢" if is_active else "⏸️"
            status_suffix = "" if is_active else " (정지)"
            
            summary_text = (
                f"**{status_prefix} {sym} ({stype}) - {alias}{status_suffix}**\n"
            )
            
            if stype == "CA":
                invested = state.get('avg_price', 0) * state.get('total_shares', 0)
                budget = state.get('cycle_budget', 1)
                progress = (invested / budget) * 100 if budget > 0 else 0
                summary_text += f"- T: {state.get('current_turn', 0):.1f} ({progress:.1f}%)\n"
                summary_text += f"- 보유: {state.get('total_shares', 0)}주"
            elif stype == "VR":
                v_curr = state.get('cycle_V', 0)
                pool = state.get('pool', 0)
                summary_text += f"- V: ${v_curr:,.0f}\n"
                summary_text += f"- Pool: ${pool:,.0f}"

            if is_active:
                st.sidebar.info(summary_text)
            else:
                st.sidebar.caption(summary_text)
            
        except Exception as e:
            st.sidebar.error(f"Error loading state: {e}")

with st.sidebar:
    # [메리츠 공식 로고 및 헤더 - H1 크기로 로고 축소 탑재]
    logo_html_sidebar = get_logo_html(height=28, margin_right=8)
    st.markdown(f"<h1 style='display:flex; align-items:center; font-size:1.42rem; font-weight:700; margin: 0 0 0.8rem 0;'>{logo_html_sidebar}메리츠CAVR 컨트롤 패널</h1>", unsafe_allow_html=True)
    st.write(f"👤 **{st.session_state.get('username', 'Investor')}**님 환영합니다.")
    if st.button("🔓 로그아웃", key="sidebar_top_logout_btn", width='stretch'):
        handle_logout()
    
    st.write("### 🎛️ 시스템 운영 설정")
    with st.container(border=True):
        # 모의투자 라디오 옵션 dimming 및 마우스 클릭 차단 스타일 (컬럼 밖 상단에 1회 선언하여 컬럼 간 높이 왜곡 방지)
        st.markdown("""
        <style>
        div[data-testid="stRadio"] div[role="radiogroup"] > label:nth-of-type(2),
        div[data-testid="stRadio"] div[role="radiogroup"] > label:nth-child(2),
        div[data-testid="stRadio"] label:has(input[value="모의 투자"]) {
            opacity: 0.35 !important;
            pointer-events: none !important;
            cursor: not-allowed !important;
            filter: grayscale(100%) !important;
        }
        div[data-testid="stRadio"] div[role="radiogroup"] > label:nth-of-type(2) * {
            pointer-events: none !important;
            cursor: not-allowed !important;
        }
        </style>
        """, unsafe_allow_html=True)

        current_trade_mode = get_trade_mode()
        if current_trade_mode == "MOCK":
            set_config("TRADE_MODE", "REAL")
            current_trade_mode = "REAL"

        # 세션 캐시로 인해 모의 투자가 선택된 상태로 렌더링되지 않도록 강제 리셋
        if st.session_state.get("trade_mode_selector_ui") != "실전 투자":
            st.session_state["trade_mode_selector_ui"] = "실전 투자"

        def _guard_mock_trade_mode():
            if st.session_state.get("trade_mode_selector_ui") == "모의 투자":
                st.session_state["trade_mode_selector_ui"] = "실전 투자"
                st.toast("⚠️ 메리츠 Open API는 모의투자를 미지원합니다. (HTS 전용)", icon="ℹ️")

        # 1행: 운영 모드 & 활성 시장 (동일한 라디오 구성으로 상단 높이 완벽 일치)
        r1_col1, r1_col2 = st.columns(2)
        with r1_col1:
            active_mode_display = st.radio(
                "🏷️ 운영 모드",
                ["실전 투자", "모의 투자"],
                index=0,
                key="trade_mode_selector_ui",
                on_change=_guard_mock_trade_mode
            )
            active_mode = "REAL"

        with r1_col2:
            active_market_display = st.radio("🌐 활성 시장", ["미국 시장", "한국 시장"], key="market_selector")
            active_market_code = "US" if active_market_display == "미국 시장" else "KR"
            m_lower = active_market_code.lower()
            
        st.divider() # 행 구분선
        
        # 2행: 방법론 & 실행 모드
        r2_col1, r2_col2 = st.columns(2)
        with r2_col1:
            t_mode = active_mode.lower()
            prev_strat = st.session_state.get(f"{t_mode}_{m_lower}_strat")
            if not prev_strat:
                if st.session_state.user_email:
                    db_strat_key = f"last_strategy_{st.session_state.user_email}_{active_mode}_{active_market_code}"
                    prev_strat = get_config(db_strat_key, None)
                if not prev_strat:
                    prev_strat = st.session_state.get("last_loaded_strategy_choice", "CA")
                    
            strat_key = f"{t_mode}_{m_lower}_strat"
            if strat_key not in st.session_state:
                st.session_state[strat_key] = prev_strat
            
            s_choice = st.radio("📈 방법론", ["CA", "VR"], key=strat_key)

        with r2_col2:
            # 실행 모드 선택 (투자 실행 vs 백테스트)
            mode_key = f"{t_mode}_{m_lower}_run_mode"
            s_mode = st.radio("🎯 실행 모드", ["투자 실행", "백테스트"], key=mode_key)

        st.divider() # 행 구분선

        # 3행: 환전 모드 (메리츠 100% 우대 이벤트 연계)
        r3_col1, r3_col2 = st.columns([1.1, 0.9])
        with r3_col1:
            current_fx_mode = get_config("FX_MODE", "AUTO" if getattr(settings, "FX_AUTO_EXCHANGE", True) else "MANUAL")
            fx_mode_options = ["자동 환전", "수동 환전"]
            fx_def_idx = 0 if current_fx_mode == "AUTO" else 1
            active_fx_display = st.radio("💱 환전 모드", fx_mode_options, index=fx_def_idx, key="fx_mode_selector_ui")
            active_fx_mode = "AUTO" if active_fx_display == "자동 환전" else "MANUAL"
            if active_fx_mode != current_fx_mode:
                set_config("FX_MODE", active_fx_mode)
                settings.FX_AUTO_EXCHANGE = (active_fx_mode == "AUTO")
                st.toast(f"환전 모드 변경됨: {active_fx_display}", icon="💱")
        with r3_col2:
            st.markdown(
                """
                <div style='margin-top: 1.35rem; padding: 6px 8px; background-color: #f0f7ff; border: 1px solid #cce3f5; border-radius: 6px;'>
                    <span style='color: #1976d2; font-weight: bold; font-size: 0.78rem;'>🎉 환율우대 100%</span><br>
                    <span style='color: #666; font-size: 0.70rem;'>스프레드 0원 (이벤트)</span>
                </div>
                """,
                unsafe_allow_html=True
            )

    # --- Broker 및 Currency Symbol 정의 (한 번만) ---
    @st.cache_resource
    def get_active_broker_instance(market_code_param: str, mode: str):
        if market_code_param == "KR":
            from core.brokers.meritz_kr import MeritzKrBroker
            return MeritzKrBroker()
        else:
            from core.brokers.meritz_us import MeritzUsBroker
            return MeritzUsBroker()

    ActiveBroker = get_active_broker_instance(active_market_code, active_mode)
    
    # 감지: 모드나 시장이 달라졌다면 live_account 캐시 클리어
    if "last_active_market_code" not in st.session_state:
        st.session_state["last_active_market_code"] = active_market_code
    if "last_active_mode" not in st.session_state:
        st.session_state["last_active_mode"] = active_mode
        
    if st.session_state["last_active_market_code"] != active_market_code or st.session_state["last_active_mode"] != active_mode:
        if 'live_account' in st.session_state:
            del st.session_state['live_account']
        st.session_state["last_active_market_code"] = active_market_code
        st.session_state["last_active_mode"] = active_mode

    currency_symbol = "₩" if active_market_code == "KR" else "$"
    # --- Broker 및 Currency Symbol 정의 끝 ---

    st.divider()
    
    def render_strategy_settings(m_code, s_choice, s_mode):
        m_lower = m_code.lower()
        m_curr = "₩" if m_code == "KR" else "$"
        
        st.subheader(f"📍 {m_code} 전략 설정")
        t_mode = get_trade_mode().lower()

        # --- 종목 선택 (신규 입력 기능 추가) ---
        m_tickers = get_market_tickers(m_code)

        # "--- 신규 입력 ---" 옵션을 추가
        t_options_with_new = ["--- 신규 입력 ---"] + list(m_tickers.keys())
        
        def fmt_t_symbol(t):
            if t == "--- 신규 입력 ---":
                return t
            n = m_tickers.get(t, "")
            return f"{n} ({t})" if n and n != t else t
            
        # [8구획 독립 UI 상태 복원]
        target_key = f"target_{t_mode}_{m_lower}_{s_choice.lower()}"
        if target_key not in st.session_state:
            if st.session_state.user_email:
                db_key = f"ui_target_{st.session_state.user_email}_{get_trade_mode()}_{s_choice}_{m_code}"
                saved_val = get_config(db_key, None)
                if saved_val:
                    try:
                        import json
                        parsed = json.loads(saved_val)
                        st.session_state[target_key] = parsed
                    except:
                        st.session_state[target_key] = {"symbol": "", "alias": ""}
                else:
                    st.session_state[target_key] = {"symbol": "", "alias": ""}
            else:
                st.session_state[target_key] = {"symbol": "", "alias": ""}

        prev_symbol = st.session_state[target_key].get("symbol")
        if not prev_symbol:
            env_suffix = m_code.lower()
            env_path = os.path.join(PROJECT_ROOT, "env", f".env.{env_suffix}")
            if os.path.exists(env_path):
                from dotenv import dotenv_values
                env_config = dotenv_values(env_path)
                prev_symbol = env_config.get("ticker", "SOXL" if m_code == "US" else "122630")
            else:
                prev_symbol = "SOXL" if m_code == "US" else "122630"
        
        def_sym_idx = t_options_with_new.index(prev_symbol) if prev_symbol in t_options_with_new else 0
        widget_key = f"{t_mode}_{m_lower}_{s_choice.lower()}_symbol_sel"
        if widget_key not in st.session_state:
            st.session_state[widget_key] = t_options_with_new[def_sym_idx]
        selected_symbol_opt = st.selectbox("종목 선택", t_options_with_new, format_func=fmt_t_symbol, key=widget_key)

        s_symbol = "" # s_symbol 초기화
        if selected_symbol_opt == "--- 신규 입력 ---":
            # [Requirement 2 & 3] 검색 및 확인 UI
            c_in1, c_in2 = st.columns([3, 1])
            s_symbol_input = c_in1.text_input("새 종목 코드 입력", value="", key=f"{m_lower}_new_symbol_input", placeholder="예: 122630").upper().strip()
            search_btn = c_in2.button("🔍 검색", key=f"{m_lower}_search_btn")
            
            if search_btn and s_symbol_input:
                with st.spinner("메리츠 API 종목 정보 조회 중..."):
                    try:
                        info = ActiveBroker.get_stock_info(s_symbol_input)
                        if info:
                            # 검색 성공 시 세션에 임시 저장
                            st.session_state[f"{m_lower}_pending_ticker"] = s_symbol_input
                            st.session_state[f"{m_lower}_pending_name"] = info.get("prdt_name", "이름 없음")
                            st.session_state[f"{m_lower}_pending_clsf"] = info.get("prdt_clsf_name", "분류 정보 없음")
                            st.session_state[f"{m_lower}_pending_type"] = info.get("ivst_prdt_type_cd_name", "유형 정보 없음")
                        else:
                            # [Requirement 3] 실패 시 메시지
                            st.error(f"❌ '{s_symbol_input}' 종목 정보를 찾을 수 없습니다. 코드를 다시 확인해 주세요.")
                            st.session_state[f"{m_lower}_pending_ticker"] = None
                    except Exception as e:
                        st.error(f"조회 중 오류 발생: {e}")
            
            # 검색 결과 확인 및 저장 버튼
            if st.session_state.get(f"{m_lower}_pending_ticker"):
                p_ticker = st.session_state[f"{m_lower}_pending_ticker"]
                p_name = st.session_state[f"{m_lower}_pending_name"]
                p_clsf = st.session_state.get(f"{m_lower}_pending_clsf", "")
                p_type = st.session_state.get(f"{m_lower}_pending_type", "")
                
                st.info(f"🔍 **종목 조회 성공**\n"
                        f"- 종목명: **{p_name}** ({p_ticker})\n"
                        f"- 분류: {p_clsf} / {p_type}")
                
                if st.button(f"✅ 위 종목을 {m_code} 리스트에 추가", key=f"{m_lower}_confirm_add", width='stretch', type="primary"):
                    if p_ticker in m_tickers:
                        st.warning(f"⚠️ '{p_ticker}' 종목은 이미 {m_code} 리스트에 존재합니다.")
                        st.session_state[f"{m_lower}_pending_ticker"] = None
                    else:
                        file_name = f"ETF_list_{m_code.lower()}.txt"
                        file_path = os.path.join(PROJECT_ROOT, "env", file_name)
                        
                        try:
                            # 파일의 마지막 문자가 개행인지 확인하여 포맷팅 최적화
                            has_content = False
                            last_char_is_newline = True
                            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                                has_content = True
                                with open(file_path, "rb") as f:
                                    f.seek(-1, os.SEEK_END)
                                    last_char_is_newline = f.read(1) == b'\n'
                            
                            # [Requirement 2] 코드 "종목명" 형식으로 추가
                            prefix = "" if not has_content or last_char_is_newline else "\n"
                            entry = f'{prefix}{p_ticker} "{p_name}"\n'
                            
                            with open(file_path, "a", encoding="utf-8") as f:
                                f.write(entry)
                            
                            st.success(f"✨ {p_name} ({p_ticker}) 종목이 {file_name}에 추가되었습니다.")
                            st.session_state[f"{m_lower}_pending_ticker"] = None
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"파일 저장 중 오류: {e}")
            
            s_symbol = st.session_state.get(f"{m_lower}_pending_ticker", "")
        else:
            s_symbol = selected_symbol_opt
        
        # s_mode가 "투자 실행"인 경우 내부 비즈니스 로직 연동을 위해 "실전 투자"로 변환
        internal_mode = "실전 투자" if s_mode == "투자 실행" else "백테스트"

        # --- 저장된 전략 목록 불러오기 로직 추가 ---
        existing_states = get_all_states_db(strategy_type=s_choice, market=m_code)
        # 현재 종목에 해당하는 전략 필터링 및 최근 수정순 정렬
        symbol_states = [s for s in existing_states if s.get('symbol') == s_symbol]
        symbol_states.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        
        existing_aliases = [s.get('strategy_name', '') for s in symbol_states]
        
        alias_options = ["--- 신규 입력 ---"] + existing_aliases # 기존 별칭 선택 또는 신규 입력
        
        # 세션 상태에서 이전 별칭 인덱스 찾기
        prev_alias = st.session_state[target_key].get("alias")
        default_idx = alias_options.index(prev_alias) if prev_alias in alias_options else (1 if existing_aliases else 0)
        
        alias_widget_key = f"{t_mode}_{m_lower}_{s_choice.lower()}_alias_sel"
        if alias_widget_key not in st.session_state:
            st.session_state[alias_widget_key] = alias_options[default_idx]
        selected_alias_opt = st.selectbox("📁 저장된 전략 선택", alias_options, key=alias_widget_key)
        
        if selected_alias_opt == "--- 신규 입력 ---":
            s_alias = st.text_input("전략 별칭 (Alias)", value=f"{m_code}_전략_1", key=f"{t_mode}_{m_lower}_{s_choice.lower()}_alias")
        else:
            s_alias = selected_alias_opt
            st.info(f"선택됨: **{s_alias}**")
            
        widget_suffix = f"{s_symbol}_{s_alias}"
        
        # DB에서 기존 설정 로드
        d_state = load_state_db(s_symbol, s_choice, market=m_code, strategy_name=s_alias) if internal_mode == "실전 투자" and s_symbol else None

        # --- [통합] 백테스트 전용 설정 ---
        f_days, f_rate, t_rate = 300, 0.0007, 0.0
        if internal_mode == "백테스트":
            col_bt1, col_bt2 = st.columns(2)
            f_days = col_bt1.number_input("데이터 기간 (일)", value=300, min_value=30, key=f"{m_lower}_{widget_suffix}_bt_days")
            
            # 모의투자 수수료 기준 적용 여부 토글
            use_mock_fee = st.checkbox("모의투자 수수료 기준 적용 (국내 0.35% / 해외 0.30%)", value=False, key=f"{m_lower}_{widget_suffix}_bt_mock_fee")
            
            if use_mock_fee:
                default_fee_val = 0.35 if m_code == "KR" else 0.30
            else:
                default_fee_val = 0.015 if m_code == "KR" else 0.07

            f_rate = col_bt2.number_input("수수료 (%)", value=default_fee_val, step=0.01, format="%.4f", key=f"{m_lower}_{widget_suffix}_bt_fee") / 100.0
            if m_code == "KR":
                t_rate = st.number_input("매도 세금 (%)", value=0.20, step=0.01, format="%.4f", key=f"{m_lower}_{widget_suffix}_bt_tax") / 100.0
        
        if s_choice == "CA":
            # [CA 전용] 전략 할당 예수금
            def_pool = d_state.get('pool', 0.0) if d_state else 0.0
            s_pool = st.number_input(f"전략 할당 예수금 ({m_curr})", value=float(def_pool), key=f"{m_lower}_{widget_suffix}_pool", help="이 전략에서 사용할 현금 한도입니다.")

            def_a = d_state.get('a_default', 40) if d_state else 40
            def_tp_val = d_state.get('target_profit_pct', 0.07 if m_code == "KR" else 0.10) if d_state else (0.07 if m_code == "KR" else 0.10)
            def_qs = d_state.get('use_quarter_stop', True) if d_state else True
            def_ver = d_state.get('version', "V2.2") if d_state else "V2.2"
            
            s_ver = st.radio("버전 선택", ["V2.2", "V4.0"], index=0 if def_ver == "V2.2" else 1, horizontal=True, key=f"{m_lower}_{widget_suffix}_ca_ver")
            
            # 1. 분할 횟수 (a) 설정 (위로 이동)
            a_val = st.number_input("분할 횟수 (a)", 20, 60, int(def_a), key=f"{m_lower}_{widget_suffix}_ca_a")
            
            # 2. 1회 매수 금액 자동 계산 (전략 할당 예수금 / 분할 횟수)
            if s_pool > 0 and a_val > 0:
                calc_ub = round(s_pool / a_val, 2) if m_code == "US" else float(int(s_pool / a_val))
            else:
                calc_ub = d_state.get('unit_buy_amount', 250.0) if d_state else 250.0
            
            u_buy = st.number_input(
                f"1회 매수 금액 ({m_curr})", 
                value=float(calc_ub), 
                key=f"{m_lower}_{widget_suffix}_ca_ub",
                help=f"전략할당예수금({s_pool:,.2f})을 분할횟수({a_val})로 나눈 1회 매수금액입니다."
            )
            
            t_profit = st.slider("목표 수익 (%)", 5, 30, int(def_tp_val * 100), key=f"{m_lower}_{widget_suffix}_ca_tp") / 100.0
            q_stop = st.checkbox("쿼터 손절 사용", value=def_qs, key=f"{m_lower}_{widget_suffix}_ca_qs")
            
            return {
                "mode": internal_mode, "strategy": s_choice, "alias": s_alias, "symbol": s_symbol, "pool": s_pool, "version": s_ver,
                "unit_buy": u_buy, "target_profit": t_profit, "a_default": a_val, "use_quarter_stop": q_stop,
                "initial_cash": s_pool, "fetch_days": f_days, "fee_rate": f_rate, "tax_rate": t_rate
            }
        else:
            # [VR 전용] 운용 자본금만 표시 (예수금은 내부 상태 유지)
            def_budget = d_state.get('initial_budget', 10000.0) if d_state else 10000.0
            def_pool = d_state.get('pool', 0.0) if d_state else 0.0
            i_cash = st.number_input(f"운용 자본금 ({m_curr})", value=float(def_budget), key=f"{m_lower}_{widget_suffix}_budget", help="밸류리밸런싱 운용 자본금(VR용).")

            def_pa = d_state.get('periodic_accumulation', 250.0) if d_state else 250.0
            def_g = d_state.get('G', 10.0) if d_state else 10.0
            def_b = (d_state.get('band_high_pct', 115.0) if d_state else 115.0) - 100.0
            
            g_val = st.slider("G 값", 10, 30, int(def_g), key=f"{m_lower}_{widget_suffix}_vr_g")
            b_pct = st.slider("밴드 (%)", 5, 30, int(def_b), key=f"{m_lower}_{widget_suffix}_vr_b")
            
            v_type_disp = st.selectbox("투자 방식", ["적립식", "거치식", "인출식"], key=f"{m_lower}_{widget_suffix}_vr_type")
            type_map = {"적립식": "accumulation", "거치식": "deferment", "인출식": "withdrawal"}
            v_type = type_map[v_type_disp]
            
            p_amt = st.number_input(f"주기별 적립/인출액 ({m_curr})", value=float(def_pa), key=f"{m_lower}_{widget_suffix}_vr_pa")
            v_freq = st.selectbox("주기", ["매일", "매주 금요일", "격주 금요일 (2주)", "4주마다 금요일"], index=2, key=f"{m_lower}_{widget_suffix}_vr_freq")
            
            # [신규] 0일차 기존 잔고 편입 체크박스 옵션 제공 (DB 상태가 없거나 수량이 0인 신규 세팅 시 사용)
            include_existing = st.checkbox("기존 잔고 편입 (0일차)", value=False, key=f"{m_lower}_{widget_suffix}_vr_inc_exist", help="체크 시 계좌에 이미 보유 중인 주식 수량과 평단가를 이 전략의 0일차 시작 잔고로 편입합니다.")
            
            # [수정] 초기 빌드업 일수 슬라이더를 Pool 사용한도 슬라이더로 변경
            def_limit_pct = 50.0
            if v_type_disp == "적립식": def_limit_pct = 75.0
            elif v_type_disp == "인출식": def_limit_pct = 25.0
            
            if d_state and d_state.get('pool_limit_pct') is not None:
                def_limit_pct = float(d_state.get('pool_limit_pct'))

            pool_limit_pct = st.slider(
                "Pool 사용한도 (%)", 
                25, 75, int(def_limit_pct), 
                key=f"{m_lower}_{widget_suffix}_vr_pool_limit", 
                help="전략에서 사용할 수 있는 최대 Pool 한도 비율입니다. (추천: 적립식 75%, 거치식 50%, 인출식 25%)"
            )
            
            return {
                "mode": internal_mode, "strategy": s_choice, "alias": s_alias, "symbol": s_symbol, "pool": def_pool,
                "g_value": g_val, "band_pct": b_pct, "periodic_amt": p_amt,
                "initial_cash": i_cash, "investment_type": v_type, "freq": v_freq, "invest_type_disp": v_type_disp,
                "include_existing": include_existing,
                "pool_limit_pct": pool_limit_pct,
                "fetch_days": f_days, "fee_rate": f_rate, "tax_rate": t_rate
            }

    # [수정] 사이드바 탭을 제거하고 활성 시장에 맞는 설정만 렌더링하여 UI 혼선 방지
    active_settings = render_strategy_settings(active_market_code, s_choice, s_mode)
    
    market_code = active_market_code
    mode = active_settings["mode"]
    strategy_choice = active_settings["strategy"]
    strategy_alias = active_settings["alias"]
    symbol = active_settings["symbol"]
    # [점검] symbol 변수에 "종목명 (코드)" 형태의 포맷팅된 문자열이 들어있는 경우, 괄호 안의 순수 코드만 추출
    if isinstance(symbol, str) and "(" in symbol and ")" in symbol:
        # [FIX] "Ticker (Name)" 형식에서 첫 번째 파트(Ticker)만 추출하도록 수정
        symbol = symbol.split('(')[0].strip()
    
    allocated_pool = active_settings["pool"]
    
    # [UI 상태 저장] 선택이 변경될 때마다 DB 업데이트
    save_ui_settings_db(st.session_state.user_email, active_market_display, symbol, strategy_alias)
    
    # [8구획 독립 UI 상태 저장]
    if st.session_state.user_email:
        import json
        current_trade_mode_val = get_trade_mode()
        save_key = f"ui_target_{st.session_state.user_email}_{current_trade_mode_val}_{strategy_choice}_{market_code}"
        target_val = json.dumps({"symbol": symbol, "alias": strategy_alias})
        set_config(save_key, target_val)
        
        # 각 시장 및 모드별 마지막 전략 타입(CA/VR) 저장
        set_config(f"last_strategy_{st.session_state.user_email}_{current_trade_mode_val}_{market_code}", strategy_choice)
        
        # 세션 상태도 업데이트
        target_key = f"target_{current_trade_mode_val.lower()}_{market_code.lower()}_{strategy_choice.lower()}"
        st.session_state[target_key] = {"symbol": symbol, "alias": strategy_alias}
    initial_cash = active_settings["initial_cash"]
    fetch_days = active_settings.get("fetch_days", 300)
    fee_rate = active_settings.get("fee_rate", 0.0007)
    tax_rate = active_settings.get("tax_rate", 0.0)

    if strategy_choice == "CA":
        unit_buy = active_settings["unit_buy"]
        target_profit = active_settings["target_profit"]
        ca_version = active_settings["version"]
        a_default = active_settings["a_default"]
        use_quarter_stop = active_settings["use_quarter_stop"]
    else:
        vr_g_value = active_settings["g_value"]
        vr_band_pct = active_settings["band_pct"]
        vr_periodic_amt = active_settings["periodic_amt"]
        vr_investment_type = active_settings["investment_type"]
        vr_freq = active_settings["freq"]
        vr_invest_type_disp = active_settings["invest_type_disp"]
        vr_include_existing = active_settings.get("include_existing", False)
        vr_bootstrap_days = active_settings.get("bootstrap_days", 10)
        vr_pool_limit_pct = active_settings.get("pool_limit_pct", 50.0)

    st.divider()

    # [요청] 전략 관리 버튼 구성 (전략 설정 바로 아래 배치)
    col_b1, col_b2 = st.columns(2)
    save_run_btn = col_b1.button("💾 신규전략 저장 및 실행", width='stretch', type="primary")
    load_strategy_btn = col_b2.button("📂 저장된 전략 불러오기", width='stretch')
    update_strategy_btn = st.button("✏️ 전략 업데이트", width='stretch')

    if load_strategy_btn:
        st.sidebar.info("🔄 최신 전략 데이터를 로드합니다.")
        time.sleep(0.5)
        st.rerun()

    if save_run_btn:
        if mode == "실전 투자":
            # 중복 전략 확인
            existing_state = load_state_db(symbol, strategy_choice, market=market_code, strategy_name=strategy_alias)
            if existing_state:
                st.sidebar.error(f"'{strategy_alias}' 전략이 이미 존재합니다. 다른 이름을 사용하거나 '전략 이름 변경'을 이용하세요.")
                st.stop()
            # 현재 입력된 파라미터로 새로운 전략 객체 생성
            if strategy_choice == "CA":
                new_state = CAState(
                    symbol=symbol,
                    strategy_type="CA",
                    version=ca_version,
                    strategy_name=strategy_alias,
                    market=market_code,
                    cycle_budget=initial_cash, # 사이드바 초기자본 값 사용
                    pool=allocated_pool,       # 할당 예수금 저장
                    unit_buy_amount=unit_buy,
                    a_default=a_default,
                    # 나머지 필드는 기본값 사용
                )
            elif strategy_choice == "VR":
                # 기존 잔고를 편입하거나 미편입하는 로직 적용
                broker = ActiveBroker
                equity_res = broker.get_account_equity(symbol)
                shares, avg_price, eval_amt = equity_res if equity_res else (0.0, 0.0, 0.0)
                
                if vr_include_existing:
                    initial_shares = shares
                    initial_avg_price = avg_price
                    stock_value = eval_amt
                else:
                    initial_shares = 0.0
                    initial_avg_price = 0.0
                    stock_value = 0.0
                
                # 운용자본금을 모두 pool에 부여
                initial_pool = initial_cash
                
                # V 계산: 0 + pool/G + E/(2*sqrt(G))
                import math
                initial_V = (initial_pool / vr_g_value) + (stock_value / (2.0 * math.sqrt(vr_g_value)))
                
                vr_pool_limit_pct = active_settings.get("pool_limit_pct", 50.0)
                
                # 가변 Bootstrap 조건 및 진입 여부 판별
                low_band = initial_V * ((100.0 - vr_band_pct) / 100.0)
                usable_pool = initial_pool * (vr_pool_limit_pct / 100.0)
                
                mode = "RUNNING"
                bootstrap_days = 0
                bootstrap_order_amt = 0.0
                
                if usable_pool > low_band:
                    # 실시간 주가 확인
                    price = broker.get_price(symbol)
                    if price <= 0:
                        price = broker.get_previous_close(symbol)
                    
                    if price > 0:
                        # 1) 10등분 시도
                        amt_10 = usable_pool / 10.0
                        qty_10 = int(amt_10 / price)
                        if qty_10 >= 2:
                            mode = "BOOTSTRAP"
                            bootstrap_days = 10
                            bootstrap_order_amt = amt_10
                        else:
                            # 2) 5등분 시도
                            amt_5 = usable_pool / 5.0
                            qty_5 = int(amt_5 / price)
                            if qty_5 >= 2:
                                mode = "BOOTSTRAP"
                                bootstrap_days = 5
                                bootstrap_order_amt = amt_5
                            else:
                                # 3) 매수 미진행 -> 즉시 RUNNING 진입
                                mode = "RUNNING"
                                bootstrap_days = 0
                                bootstrap_order_amt = 0.0
                    else:
                        # 주가 조회 실패 시, 10등분으로 가정한 뒤 BOOTSTRAP 모드로 시작합니다 (안전한 폴백)
                        mode = "BOOTSTRAP"
                        bootstrap_days = 10
                        bootstrap_order_amt = usable_pool / 10.0
                
                new_state = VRState(
                    symbol=symbol,
                    strategy_type="VR",
                    strategy_name=strategy_alias,
                    market=market_code,
                    initial_budget=initial_cash,
                    pool=initial_pool,
                    periodic_accumulation=vr_periodic_amt,
                    freq=vr_freq,
                    V=initial_V,
                    last_E=stock_value, # E는 주식 평가액 단독
                    cycle_V=initial_V,
                    cycle_start_pool=initial_pool,
                    total_shares=initial_shares,
                    avg_price=initial_avg_price,
                    mode=mode,
                    bootstrap_days=bootstrap_days,
                    bootstrap_day_count=0,
                    bootstrap_order_amount=bootstrap_order_amt,
                    G=vr_g_value,
                    band_low_pct=100.0 - vr_band_pct,
                    band_high_pct=100.0 + vr_band_pct,
                    investment_type=vr_investment_type,
                    pool_limit_pct=vr_pool_limit_pct
                )
            
            # DB에 저장
            save_state_db(new_state, market=market_code, strategy_name=strategy_alias)
            # 스케줄러 가동 상태로 전환
            set_config("scheduler_status", "running")
            st.sidebar.success(f"✅ '{strategy_alias}' 저장 및 스케줄러 실행 시작!")
            time.sleep(1)
            st.rerun()
        else:
            st.sidebar.warning("백테스트 모드에서는 전략을 저장할 수 없습니다.")
    if update_strategy_btn:
        if mode == "실전 투자":
            # 기존 전략 로드 (별칭 조건 추가)
            existing_state_data = load_state_db(symbol, strategy_choice, market=market_code, strategy_name=strategy_alias)
            if existing_state_data:
                import dataclasses
                # 현재 사이드바 파라미터로 업데이트
                if strategy_choice == "CA":
                    # 데이터클래스 생성자에 없는 여분 필드 필터링 (TypeError 방지)
                    valid_keys = {f.name for f in dataclasses.fields(CAState)}
                    filtered_data = {k: v for k, v in existing_state_data.items() if k in valid_keys}
                    state_obj = CAState(**filtered_data)
                    state_obj.strategy_name = strategy_alias
                    state_obj.version = ca_version
                    state_obj.cycle_budget = initial_cash
                    state_obj.pool = allocated_pool
                    state_obj.unit_buy_amount = unit_buy
                    state_obj.a_default = a_default
                    state_obj.target_profit_pct = target_profit
                    state_obj.use_quarter_stop = use_quarter_stop
                elif strategy_choice == "VR":
                    # 데이터클래스 생성자에 없는 여분 필드 필터링 (TypeError 방지)
                    valid_keys = {f.name for f in dataclasses.fields(VRState)}
                    filtered_data = {k: v for k, v in existing_state_data.items() if k in valid_keys}
                    state_obj = VRState(**filtered_data)
                    state_obj.strategy_name = strategy_alias
                    state_obj.initial_budget = initial_cash
                    state_obj.pool = allocated_pool
                    state_obj.periodic_accumulation = vr_periodic_amt
                    state_obj.G = vr_g_value
                    state_obj.band_low_pct = 100.0 - vr_band_pct
                    state_obj.band_high_pct = 100.0 + vr_band_pct
                    state_obj.freq = vr_freq
                    state_obj.investment_type = vr_investment_type
                    state_obj.pool_limit_pct = vr_pool_limit_pct
                                    
                save_state_db(state_obj, market=market_code, strategy_name=strategy_alias)
                st.sidebar.success(f"✅ '{strategy_alias}' 전략이 업데이트되었습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.sidebar.warning("업데이트할 기존 전략을 찾을 수 없습니다. '새 전략 저장'을 이용하세요.")
        else:
            st.sidebar.warning("백테스트 모드에서는 전략을 업데이트할 수 없습니다.")

    st.divider()

    # 스케줄러 제어 및 요약 정보 호출
    display_scheduler_control()
    display_sidebar_summary(active_market_display, market_code)

display_mode = "모의 투자" if (current_trade_mode == "MOCK" and mode == "실전 투자") else mode
logo_html_main = get_logo_html(height=34, margin_right=10)
st.markdown(f"<h1 style='display:flex; align-items:center; font-size:2.0rem; font-weight:700; margin: 0.5rem 0 1rem 0;'>{logo_html_main}{display_mode} - {strategy_choice} 전략</h1>", unsafe_allow_html=True)

# [ADD] 현재 활성화된 모드에 대한 명확한 한글 설명 제공
if display_mode == "실전 투자":
    st.info(f"💼 **[실전 투자 모드]** 실제 메리츠증권 계좌(계좌번호: `{ActiveBroker.account_no}`)를 연동하여 실제 매매를 진행합니다. 신중히 결정해 주세요.")
elif display_mode == "모의 투자":
    st.success(f"📈 **[모의 투자 모드]** 메리츠증권 모의 계좌(계좌번호: `{ActiveBroker.account_no}`)를 연동하여 가상의 잔고로 안전한 시뮬레이션 투자를 진행합니다.")
elif display_mode == "백테스트":
    st.warning(f"🧪 **[백테스트 모드]** 과거 {fetch_days}일간의 누적 데이터를 토대로 CA/VR 전략 시뮬레이션을 수행합니다. 실제 주문은 발생하지 않습니다.")

# --- [ADD] 메리츠 MY 계좌평가 & 잔고내역 상단 영역 (기본 닫힘 expander) ---
def fetch_meritz_account_data(force=False):
    """메리츠 Open API를 통해 자산평가 및 보유종목 데이터를 세션 캐시(15초)와 함께 조회"""
    now = time.time()
    cache = st.session_state.get("_meritz_my_account_cache")
    if not force and cache and (now - cache.get("ts", 0) < 15):
        return cache.get("valuation", {}), cache.get("holdings", [])

    # 메리츠 일일 전산 점검 시간(23:50~00:20 KST)인 경우 API 에러를 피하고 기존 캐시 유지
    kr_now = datetime.now(pytz.timezone('Asia/Seoul'))
    if kr_now.time() >= dtime(23, 50) or kr_now.time() < dtime(0, 20):
        if cache:
            return cache.get("valuation", {}), cache.get("holdings", [])

    val_data = {}
    hld_data = []
    try:
        from meritz import client, load_catalog
        cat, c = load_catalog(), client()

        val_api = cat.get("valuation")
        if val_api:
            res_val = c.call(val_api, {})
            if res_val.get("ok"):
                body = res_val.get("body", {})
                if isinstance(body, dict):
                    val_data = body.get("data", {})

        hld_api = cat.get("holdings")
        if hld_api:
            res_hld = c.call(hld_api, {})
            if res_hld.get("ok"):
                body = res_hld.get("body", {})
                if isinstance(body, dict):
                    hld_data = body.get("data", [])
    except Exception as e:
        if "서비스 가능시간이 아닙니다" in str(e):
            logger.warning("⚠️ 메리츠 일일 점검 시간 (23:50 ~ 00:20)으로 인해 잔고 조회가 대기 상태입니다.")
            if cache:
                return cache.get("valuation", {}), cache.get("holdings", [])
        else:
            logger.error(f"메리츠 MY 계좌평가/잔고 조회 실패: {e}")

    st.session_state["_meritz_my_account_cache"] = {
        "ts": now,
        "valuation": val_data,
        "holdings": hld_data
    }
    return val_data, hld_data

def render_my_account_expander(broker):
    """모든 화면 상단에 기본으로 닫힌(expanded=False) 메리츠 MY 계좌평가/보유잔고 영역을 렌더링"""
    with st.expander("💼 MY 계좌평가 (계좌자산 및 보유잔고 상세)", expanded=False):
        # 메리츠 일일 전산 점검 시간(23:50 ~ 00:20) 안내 배너
        kr_now = datetime.now(pytz.timezone('Asia/Seoul'))
        if kr_now.time() >= dtime(23, 50) or kr_now.time() < dtime(0, 20):
            st.warning("🕒 **메리츠증권 일일 시스템 점검 시간 안내 (23:50 ~ 00:20)**: 시스템 점검 동안은 계좌정보 조회 및 서비스가 일시 제한되며, 점검 시간 이후(00:20) 자동으로 최신 상태로 재조회됩니다.")

        # 상단 제어 바: 계좌번호, 성명, 상품, 조회 버튼
        c_acc, c_btn = st.columns([0.85, 0.15])
        
        # 계좌번호 포맷팅 (예: 3043653601 -> 3043-6536-01)
        raw_acc = getattr(broker, "account_no", None) or getattr(settings, "ACCOUNT_NO", "3043653601") or "3043653601"
        clean_acc = re.sub(r'[^0-9]', '', str(raw_acc))
        if len(clean_acc) == 10:
            formatted_acc = f"{clean_acc[:4]}-{clean_acc[4:8]}-{clean_acc[8:]}"
        elif len(clean_acc) >= 8:
            formatted_acc = f"{clean_acc[:4]}-{clean_acc[4:]}"
        else:
            formatted_acc = "3043-6536-01"
            
        user_name = getattr(settings, "MERITZ_USER_NAME", "심재한")
        prod_name = "Super365"
        
        with c_acc:
            acc_bar_html = f"""
            <div style="display: flex; align-items: center; gap: 12px; background: #ffffff; padding: 10px 16px; border: 1px solid #e2e4e8; border-radius: 6px; margin-bottom: 12px; flex-wrap: wrap;">
                <div style="font-size: 1.35rem; font-weight: 700; color: #222; margin-right: 15px;">MY 계좌평가</div>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-weight: 600; font-size: 0.9rem; color: #333;">계좌번호</span>
                    <span style="background: #f1f3f5; border: 1px solid #ced4da; padding: 4px 10px; border-radius: 4px; font-weight: 600; font-size: 0.9rem; color: #111;">
                        {formatted_acc} <span style="font-size: 0.75rem; color: #666;">▼</span>
                    </span>
                </div>
                <div style="background: #e9ecef; border: 1px solid #ced4da; padding: 4px 12px; border-radius: 4px; font-weight: 600; font-size: 0.88rem; color: #333;">
                    {user_name}
                </div>
                <div style="background: #f8f9fa; border: 1px solid #dee2e6; padding: 4px 14px; border-radius: 4px; font-size: 0.88rem; color: #495057;">
                    {prod_name}
                </div>
            </div>
            """
            st.markdown("\n".join(l.strip() for l in acc_bar_html.splitlines()), unsafe_allow_html=True)
        with c_btn:
            # 메리츠 HTS 골드/브라운 톤 조회 버튼
            if st.button("조회", key="btn_refresh_my_account", use_container_width=True):
                fetch_meritz_account_data(force=True)
                st.rerun()

        # 데이터 조회
        val_data, hld_data = fetch_meritz_account_data(force=False)
        
        # 1. 계좌자산평가액 섹션
        st.markdown("<div style='font-size: 0.95rem; font-weight: 700; color: #9c6c29; margin-top: 6px; margin-bottom: 6px;'>◆ 계좌자산평가액</div>", unsafe_allow_html=True)
        
        tfam = val_data.get("tfam", 0)
        d2_aft_tfam = val_data.get("d2_aft_tfam", 0)
        frcr_tfam = val_data.get("frcr_tfam", 0)
        mksc_vltn_amt = val_data.get("mksc_vltn_amt", 0)
        vltn_amt = val_data.get("vltn_amt", 0)
        loan_amt = val_data.get("loan_amt", 0)
        aset_vltn_amt = val_data.get("aset_vltn_amt", 0)
        
        val_html = f"""<div style="overflow-x: auto; margin-bottom: 4px;">
<table style="width: 100%; border-collapse: collapse; text-align: right; font-size: 0.88rem; border-top: 2px solid #8d775f; border-bottom: 1px solid #dcdcdc;">
<thead>
<tr style="background: #f5f4f0; color: #222; font-weight: 700; border-bottom: 1px solid #dcdcdc; height: 38px;">
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">원화예수금<br>(D일)</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">원화예수금<br>(D+2)</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">외화예수금</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">유가증권평가액</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">총평가액</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">대출금액</th>
<th style="padding: 6px 12px; text-align: center;">순자산평가액</th>
</tr>
</thead>
<tbody>
<tr style="height: 42px; background: #ffffff; font-weight: 600; color: #111;">
<td style="padding: 6px 14px; border-right: 1px solid #f0f0f0;">{int(tfam):,}</td>
<td style="padding: 6px 14px; border-right: 1px solid #f0f0f0;">{int(d2_aft_tfam):,}</td>
<td style="padding: 6px 14px; border-right: 1px solid #f0f0f0;">{int(frcr_tfam):,}</td>
<td style="padding: 6px 14px; border-right: 1px solid #f0f0f0;">{int(mksc_vltn_amt):,}</td>
<td style="padding: 6px 14px; border-right: 1px solid #f0f0f0;">{int(vltn_amt):,}</td>
<td style="padding: 6px 14px; border-right: 1px solid #f0f0f0;">{int(loan_amt):,}</td>
<td style="padding: 6px 14px;">{int(aset_vltn_amt):,}</td>
</tr>
</tbody>
</table>
</div>
<div style="font-size: 0.78rem; color: #777; margin-bottom: 18px; margin-top: 4px;">
※ 총평가액에 ELB/DLB 청약금액 및 외화증거금 포함
</div>"""
        st.markdown(val_html, unsafe_allow_html=True)
        
        # 2. 보유잔고내역 섹션 (스크린샷 2 2행 1레코드 구조)
        st.markdown("<div style='font-size: 0.95rem; font-weight: 700; color: #9c6c29; margin-bottom: 6px;'>◆ 보유잔고내역</div>", unsafe_allow_html=True)
        
        rows_list = []
        if not hld_data:
            rows_list.append("""<tr><td colspan="7" style="text-align: center; padding: 25px; color: #888;">보유 잔고가 없습니다.</td></tr>""")
        else:
            for idx, item in enumerate(hld_data):
                bg_color = "#ffffff" if idx % 2 == 0 else "#fafafa"
                
                # 1행 항목
                mksc_cls_name = item.get("mksc_cls_name", "해외주식") or "해외주식"
                rmnd_qty = int(safe_float(item.get("rmnd_qty", 0)))
                psnt_prc = safe_float(item.get("psnt_prc", 0))
                vltn_amt_item = int(safe_float(item.get("vltn_amt", 0)))
                ert = safe_float(item.get("ert", 0))
                byov_date = item.get("byov_date", "") or ""
                loan_mtrt_date = item.get("loan_mtrt_date", "") or ""
                
                # 2행 항목
                isnm = item.get("isnm", "")
                byng_unpr = safe_float(item.get("byng_unpr", 0))
                prdy_clpr_vrss = safe_float(item.get("prdy_clpr_vrss", 0))
                vltn_prls_amt = int(safe_float(item.get("vltn_prls_amt", 0)))
                iscd = item.get("iscd", "")
                mtrt_date = item.get("mtrt_date", "") or ""
                loan_amt_item = int(safe_float(item.get("loan_amt", 0)))
                
                # 색상 결정
                ert_color = "#1976d2" if ert < 0 else ("#d32f2f" if ert > 0 else "#333")
                vrss_color = "#1976d2" if prdy_clpr_vrss < 0 else ("#d32f2f" if prdy_clpr_vrss > 0 else "#333")
                prls_color = "#1976d2" if vltn_prls_amt < 0 else ("#d32f2f" if vltn_prls_amt > 0 else "#333")
                
                rows_list.append(f"""<tr style="background: {bg_color}; border-top: 1px solid #eaeaea; height: 34px;">
<td style="padding: 6px 12px; text-align: left; border-right: 1px solid #f0f0f0; color: #333;">{mksc_cls_name}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0; font-weight: 600;">{rmnd_qty:,}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0;">{psnt_prc:,.2f}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0; font-weight: 600;">{vltn_amt_item:,}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0; color: {ert_color}; font-weight: 600;">{ert:+.2f}%</td>
<td style="padding: 6px 12px; text-align: center; border-right: 1px solid #f0f0f0; color: #666;">{byov_date}</td>
<td style="padding: 6px 12px; text-align: center; color: #666;">{loan_mtrt_date}</td>
</tr>
<tr style="background: {bg_color}; border-bottom: 1px solid #e0e0e0; height: 34px;">
<td style="padding: 6px 12px; text-align: left; border-right: 1px solid #f0f0f0; font-weight: 600; color: #111;">{isnm}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0;">{byng_unpr:,.2f}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0; color: {vrss_color};">{prdy_clpr_vrss:+,.2f}</td>
<td style="padding: 6px 12px; text-align: right; border-right: 1px solid #f0f0f0; color: {prls_color}; font-weight: 600;">{vltn_prls_amt:+,}</td>
<td style="padding: 6px 12px; text-align: center; border-right: 1px solid #f0f0f0; color: #1a0dab; font-weight: 600;">{iscd}</td>
<td style="padding: 6px 12px; text-align: center; border-right: 1px solid #f0f0f0; color: #666;">{mtrt_date}</td>
<td style="padding: 6px 12px; text-align: right; color: #333;">{loan_amt_item:,}</td>
</tr>""")

        rows_html = "".join(rows_list)
        hld_html = f"""<div style="overflow-x: auto; margin-bottom: 10px;">
<table style="width: 100%; border-collapse: collapse; font-size: 0.88rem; border-top: 2px solid #8d775f; border-bottom: 1px solid #dcdcdc;">
<thead>
<tr style="background: #f5f4f0; color: #222; font-weight: 700; height: 32px; border-bottom: 1px solid #e5e5e5;">
<th style="padding: 6px 12px; text-align: left; border-right: 1px solid #e7e6e2; width: 22%;">잔고구분</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2; width: 10%;">잔고수량</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2; width: 12%;">현재가</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2; width: 14%;">평가금액</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2; width: 12%;">손익률(%)</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2; width: 15%;">매수일</th>
<th style="padding: 6px 12px; text-align: center; width: 15%;">대출만기일</th>
</tr>
<tr style="background: #f5f4f0; color: #222; font-weight: 700; height: 32px; border-bottom: 1px solid #dcdcdc;">
<th style="padding: 6px 12px; text-align: left; border-right: 1px solid #e7e6e2;">종목명</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2;">매입가</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2;">전일비</th>
<th style="padding: 6px 12px; text-align: right; border-right: 1px solid #e7e6e2;">평가손익</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">종목코드</th>
<th style="padding: 6px 12px; text-align: center; border-right: 1px solid #e7e6e2;">만기일</th>
<th style="padding: 6px 12px; text-align: right;">대출금액</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>"""
        st.markdown(hld_html, unsafe_allow_html=True)

# --- 모든 화면 상단에 기본 닫힌 상태로 배치 ---
render_my_account_expander(ActiveBroker)

# --- 시장별 현황 탭 --- (사이드바 선택에 따라 강조 및 필터링)
# [수정] 활성 시장에 따라 탭 순서를 동적으로 변경하며 외환/환전 관리 탭 추가
if market_code == "KR":
    tab_names = ["✅ 🇰🇷 한국 주식 시장 현황", "🇺🇸 미국 주식 시장 현황", "💱 외환/환전 관리 (Forex)", "🏁 종료된 전략 내역", "📈 손익분석", "⚙️ 설정"]
    tabs = st.tabs(tab_names, key=f"market_tabs_{get_trade_mode().lower()}_{market_code.lower()}")
    tab_kr, tab_us, tab_forex, tab_finished, tab_analysis, tab_settings = tabs[0], tabs[1], tabs[2], tabs[3], tabs[4], tabs[5]
else:
    tab_names = ["✅ 🇺🇸 미국 주식 시장 현황", "🇰🇷 한국 주식 시장 현황", "💱 외환/환전 관리 (Forex)", "🏁 종료된 전략 내역", "📈 손익분석", "⚙️ 설정"]
    tabs = st.tabs(tab_names, key=f"market_tabs_{get_trade_mode().lower()}_{market_code.lower()}")
    tab_us, tab_kr, tab_forex, tab_finished, tab_analysis, tab_settings = tabs[0], tabs[1], tabs[2], tabs[3], tabs[4], tabs[5]


@st.fragment(run_every=5)
def display_holdings_metrics_live(symbol, strategy_choice, market_code, strategy_alias, currency_symbol, ActiveBroker):
    if isinstance(symbol, str) and "(" in symbol:
        symbol = symbol.split('(')[0].strip()
        
    # [Auto-Sync] 최초 로드 시 또는 30초 쿨다운 주기별로 백그라운드 잔고 자동 동기화 트리거
    import time
    now_ts = time.time()
    last_auto_sync_key = f"last_auto_sync_{market_code}_{symbol}"
    
    # 한국/미국 시장의 장중 여부 판별
    is_market_active = True
    if market_code == "KR":
        kr_tz = pytz.timezone('Asia/Seoul')
        now_kr = datetime.now(kr_tz)
        if now_kr.weekday() >= 5:
            is_market_active = False
        else:
            is_market_active = dtime(8, 30) <= now_kr.time() <= dtime(16, 0)
    elif market_code == "US":
        us_tz = pytz.timezone('America/New_York')
        now_us = datetime.now(us_tz)
        if now_us.weekday() >= 5:
            is_market_active = False
        else:
            is_market_active = dtime(7, 0) <= now_us.time() <= dtime(18, 0)
            
    sync_interval = 300.0 if is_market_active else 3600.0
    
    # 메리츠 일일 전산 점검 시간 (23:50 ~ 00:20 KST) 판별
    kr_now_check = datetime.now(pytz.timezone('Asia/Seoul'))
    is_maintenance = (kr_now_check.time() >= dtime(23, 50) or kr_now_check.time() < dtime(0, 20))

    if not is_maintenance and ('live_account' not in st.session_state or st.session_state['live_account'].get('symbol') != symbol or (now_ts - st.session_state.get(last_auto_sync_key, 0) > sync_interval)):
        try:
            logger.info(f"🔄 [Auto-Sync] {symbol} {market_code} 실시간 잔고 자동 연동 및 동기화 실행")
            equity_res = ActiveBroker.get_account_equity(symbol)
            if equity_res is None:
                raise ValueError("잔고 조회 실패 (None 반환)")
            shares, avg_price, eval_amt = equity_res
            pool = ActiveBroker.get_cash_pool()
            current_price = ActiveBroker.get_price(symbol)
            prev_close = ActiveBroker.get_previous_close(symbol)
            
            # DB 상태 업데이트 일관화
            state_data = load_state_db(symbol, strategy_choice, market=market_code, strategy_name=strategy_alias)
            if state_data:
                if strategy_choice == "CA":
                    from core.cavr import CAState
                    import math
                    state_obj = CAState(**state_data)
                    state_obj.avg_price = avg_price
                    a_def = float(getattr(state_obj, 'a_default', 40) or 40)
                    c_budget = float(getattr(state_obj, 'cycle_budget', 0.0) or 0.0)
                    base_unit_buy = (c_budget / a_def) if (c_budget > 0 and a_def > 0) else float(state_obj.unit_buy_amount or 0)
                    if base_unit_buy > 0:
                        invested = avg_price * shares
                        state_obj.current_turn = math.ceil((invested / base_unit_buy) * 10) / 10.0
                    from core.database import save_state_db
                    save_state_db(state_obj, market=market_code, strategy_name=strategy_alias)
                elif strategy_choice == "VR":
                    from core.cavr import VRState
                    import dataclasses
                    db_avg_price = state_data.get('avg_price', 0.0)
                    if db_avg_price > 0.0:
                        valid_keys = {f.name for f in dataclasses.fields(VRState)}
                        filtered_data = {k: v for k, v in state_data.items() if k in valid_keys}
                        state_obj = VRState(**filtered_data)
                        state_obj.total_shares = shares
                        state_obj.avg_price = avg_price
                        from core.database import save_state_db
                        save_state_db(state_obj, market=market_code, strategy_name=strategy_alias)
                    
            st.session_state['live_account'] = {
                'pool': state_data.get('pool', pool) if state_data else pool,
                'broker_cash': pool,
                'shares': shares,
                'avg_price': avg_price,
                'eval_amt': eval_amt,
                'current_price': current_price,
                'prev_close': prev_close,
                'symbol': symbol,
                'market_code': market_code,
                'time': time.strftime("%H:%M:%S")
            }
            st.session_state[last_auto_sync_key] = now_ts
        except Exception as auto_err:
            logger.error(f"[Auto-Sync] 잔고 자동 조회 실패: {auto_err}")

    # 1. DB에서 가장 최신 상태 로드 (웹소켓 체결 업데이트가 실시간으로 반영됨)
    state = load_state_db(symbol, strategy_choice, market=market_code, strategy_name=strategy_alias)
    is_new_strategy = False
    if not state:
        is_new_strategy = True
        state = {
            "pool": 0.0,
            "total_shares": 0.0,
            "avg_price": 0.0,
            "current_price": 0.0,
            "updated_at": "N/A"
        }
        # 만약 실시간 계좌 조회 데이터가 세션에 있으면 수량과 평단가를 그것으로 채워줌
        if 'live_account' in st.session_state and st.session_state['live_account'].get('symbol') == symbol:
            state['total_shares'] = st.session_state['live_account'].get('shares', 0.0)
            state['avg_price'] = st.session_state['live_account'].get('avg_price', 0.0)
            state['pool'] = st.session_state['live_account'].get('pool', 0.0)

    # [STOP] 휴장 시간 브로커 호출 방지
    is_active, _ = check_market_active(market_code)
    
    # 2. 실시간 시세 및 잔고 정보 계산
    broker_cash = 0.0
    if 'live_account' in st.session_state and 'broker_cash' in st.session_state['live_account']:
        broker_cash = st.session_state['live_account']['broker_cash']
    else:
        try:
            broker = ActiveBroker
            broker_cash = broker.get_cash_pool()
            if 'live_account' not in st.session_state:
                st.session_state['live_account'] = {}
            st.session_state['live_account']['broker_cash'] = broker_cash
        except Exception as e:
            broker_cash = state.get('pool', 0.0)

    if is_active:
        broker = ActiveBroker
        curr_price = broker.get_price(symbol)
        prev_close = broker.get_previous_close(symbol)
    else:
        curr_price = state.get('current_price', 0)
        prev_close = curr_price # 정확한 전일종가 조회가 어려우므로 현재가로 대체 표시

    # 수치 추출 (DB 기반 - 웹소켓 클라이언트가 업데이트한 값)
    pool = state.get('pool', 0.0)
    if 'live_account' in st.session_state and st.session_state['live_account'].get('symbol') == symbol:
        shares = st.session_state['live_account'].get('shares', state.get('total_shares', 0.0))
        avg_price = st.session_state['live_account'].get('avg_price', state.get('avg_price', 0.0))
    else:
        shares = state.get('total_shares', 0.0)
        avg_price = state.get('avg_price', 0.0)
    
    # s_pool 계산: CA는 pool - (shares * avg_price), VR은 pool 그대로
    if strategy_choice == "CA":
        s_pool = pool - (shares * avg_price)
    else:
        s_pool = pool
    
    # 실시간 평가액 및 수익 계산
    eval_amt = shares * curr_price
    profit = eval_amt - (shares * avg_price)
    profit_pct = (profit / (shares * avg_price) * 100) if (shares * avg_price) > 0 else 0
    
    price_diff = curr_price - prev_close
    price_diff_pct = (price_diff / prev_close * 100) if prev_close > 0 else 0
    diff_fmt = f"{int(price_diff):+,}" if market_code == "KR" else f"{price_diff:+.2f}"
    delta_price = f"{diff_fmt} ({price_diff_pct:+.2f}%)"

    st.divider()
    if is_new_strategy:
        st.info("💡 등록된 전략 상태가 없습니다. 기본 정보(시세, 예수금)를 기반으로 임시 상태가 표시되고 있습니다. 신규전략 저장 및 실행 시 DB에 저장됩니다.")
    col_p1, col_p2 = st.columns(2)
    if strategy_choice == "VR":
        display_val = state.get('initial_budget', 0.0)
        label_name = f"💰 운용 자본금 ({currency_symbol})"
        help_text = "설정된 전체 운용 자본금(initial_budget)입니다."
    else:
        display_val = s_pool
        label_name = f"💰 전략 가용 예수금 ({currency_symbol})"
        help_text = "설정된 전체 예수금에서 현재 투입액을 차감한 실시간 가용 예수금(s_pool)입니다."

    col_p1.metric(label=label_name, value=f"{currency_symbol}{format_currency(display_val, market_code)}", help=help_text)
    col_p2.metric(label=f"🏦 거래소 총 예수금 ({currency_symbol})", value=f"{currency_symbol}{format_currency(broker_cash, market_code)}", help="증권사 계좌의 실제 주문 가능 원금입니다. 계좌 상태 조회 시 갱신됩니다.")

    st.subheader(f"보유 종목 현황: {format_ticker_display(symbol, market_code)}")
    c1, c2, c3, c4, c5 = st.columns(5)
    
    c1.metric(label=f"현재가 ({currency_symbol})", value=f"{currency_symbol}{format_currency(curr_price, market_code)}", delta=delta_price)
    c2.metric("보유 수량", f"{int(shares) if market_code == 'KR' else shares}주")
    c3.metric("평단가", f"{currency_symbol}{format_currency(avg_price, market_code)}")
    c4.metric("평가금액", f"{currency_symbol}{format_currency(eval_amt, market_code)}")
    c5.metric("추정 평가손익", f"{currency_symbol}{format_currency(profit, market_code)}", delta=f"{profit_pct:+.2f}%")
    
    st.caption(f"⏱️ 웹소켓 및 DB 연동 중 (5초 주기 자동 갱신) | DB 최종 갱신: {state.get('updated_at', 'N/A')}")

def render_market_tab(m_code):
    # 해당 시장의 종목 리스트 미리 로드 (명칭 표시용)
    tickers_map = get_market_tickers(m_code)
    states = get_all_states_db(market=m_code)
    if not states: # 해당 시장에 등록된 전략이 없으면
        st.info(f"{m_code} 시장에 등록된 전략이 없습니다.")
    else:
        for s in states:
            stype = s.get('strategy_type')
            sym = s.get('symbol')
            disp_name = s.get('strategy_name', '')
            with st.expander(f"[{stype}] {disp_name} - {format_ticker_display(sym, m_code)}"):
                is_active = s.get('is_active', True)
                ver = s.get('version', 'V2.2') if stype == "CA" else ""
                ver_text = f" ({stype} {ver})" if ver else ""
                status_icon = "🟢" if is_active else "⏸️"
                status_label = "운영 중" if is_active else "일시 정지됨"
                st.write(f"상태: {status_icon} **{status_label}**{ver_text}")

                cur_sym = "₩" if m_code == "KR" else "\\$"
                if stype == "CA":
                    st.markdown(
                        f"T: **{s.get('current_turn', 0):.1f}** / 평단: **{cur_sym}{format_currency(s.get('avg_price', 0), m_code)}** / 보유: **{s.get('total_shares', 0)}주**"
                    )
                    st.markdown(
                        f"할당 예수금: **{cur_sym}{format_currency(s.get('pool', 0), m_code)}** / 분할수: **{s.get('a_default', 40)}** / 1회매수금: **{cur_sym}{format_currency(s.get('unit_buy_amount', 0), m_code)}** / 목표수익률: **{s.get('target_profit_pct', 0.1)*100:.1f}%**"
                    )
                else:
                    initial_budget_val = s.get('initial_budget', 0.0)
                    cycle_V_val = s.get('cycle_V', 0.0)
                    pool_val = s.get('pool', 0.0)
                    if cycle_V_val == 0.0 and initial_budget_val > 0:
                        cycle_V_val = initial_budget_val
                    if pool_val == 0.0 and initial_budget_val > 0:
                        pool_val = initial_budget_val
                    band_pct = s.get('band_high_pct', 115.0) - 100.0
                    freq_val = s.get('freq', '격주 금요일 (2주)')
                    pool_limit_val = float(s.get('pool_limit_pct', 50.0))
                    accum_amt = s.get('periodic_accumulation', 0.0)
                    st.markdown(
                        f"목표V: **{cur_sym}{format_currency(cycle_V_val, m_code)}** / Pool: **{cur_sym}{format_currency(pool_val, m_code)}** / 풀 한도: **{pool_limit_val:.0f}%**"
                    )
                    st.markdown(
                        f"운용 자본금: **{cur_sym}{format_currency(initial_budget_val, m_code)}** / G값: **{s.get('G', 10)}** / 밴드: **{band_pct:.0f}%** / 주기: **{freq_val}** / 적립액: **{cur_sym}{format_currency(accum_amt, m_code)}**"
                    )

                # [ADD] 전략 선택 버튼 (사이드바 연동)
                if st.button("🎯 이 전략을 작업 대상으로 선택", key=f"sel_target_{m_code}_{stype}_{sym}_{disp_name}", width='stretch', type="primary"):
                    st.session_state["pending_market_selector_update"] = "미국 시장" if m_code == "US" else "한국 시장"
                    st.session_state["pending_strat_update"] = {"m_code": m_code, "strat": stype}
                    st.session_state["pending_symbol_update"] = {"m_code": m_code, "strat": stype, "symbol": sym}
                    st.session_state["pending_alias_update"] = {"m_code": m_code, "strat": stype, "alias": disp_name}
                    st.session_state["last_loaded_symbol"] = sym
                    st.session_state["last_loaded_alias"] = disp_name
                    st.rerun()

                col_t1, col_t2, col_t3 = st.columns(3)

                # 일시정지 / 다시 시작 버튼
                toggle_label = "⏸️ 전략 일시 정지" if is_active else "▶️ 전략 다시 시작"
                if col_t1.button(toggle_label, key=f"toggle_{m_code}_{stype}_{sym}_{disp_name}", width='stretch'):
                    raw_state = load_state_db(sym, stype, market=m_code, strategy_name=disp_name)
                    if raw_state:
                        raw_state['is_active'] = not is_active
                        state_obj = CAState(**raw_state) if stype == "CA" else VRState(**raw_state)
                        save_state_db(state_obj, market=m_code, strategy_name=disp_name)
                        st.rerun()

                # 전략 종료 버튼 (History로 이동)
                if col_t2.button(f"🏁 전략 종료", key=f"finish_{m_code}_{stype}_{sym}_{disp_name}", width='stretch', help="전략을 완료하고 이력 탭으로 이동시킵니다."):
                    # [ADD] 최종 리포트 생성 및 전송
                    try:
                        _, all_th_rows = get_detailed_trade_history_db(sym, market=m_code)
                        # 해당 별칭의 매도 내역 필터링
                        strat_sells = [r for r in all_th_rows if r[4] == disp_name and r[5] == 'SELL']
                        
                        total_profit = sum(float(r[14] or 0) for r in strat_sells)
                        sell_count = len(strat_sells)
                        
                        # 총 매수액 (간단히 매도된 원금 합산 또는 전체 매수 합산)
                        strat_buys = [r for r in all_th_rows if r[4] == disp_name and r[5] == 'BUY']
                        total_bought = sum(float(r[10] or 0) for r in strat_buys)
                        
                        report_msg = (
                            f"🏁 <b>[전략 종료 리포트]</b>\n"
                            f"종목: {sym} ({disp_name})\n"
                            f"시장: {m_code}\n"
                            f"전략: {stype}\n"
                            f"--------------------\n"
                            f"총 매도 횟수: {sell_count}회\n"
                            f"총 누적 수익: {cur_sym}{format_currency(total_profit, m_code)}\n"
                            f"총 투입 원금: {cur_sym}{format_currency(total_bought, m_code)}\n"
                            f"최종 수익률: {(total_profit/total_bought*100 if total_bought > 0 else 0):.2f}%"
                        )
                        send_telegram_message(report_msg)
                    except Exception as e:
                        logger.error(f"리포트 생성 실패: {e}")

                    finish_strategy_db(sym, stype, m_code, disp_name)
                    st.success(f"전략이 종료되었습니다: {disp_name}")
                    time.sleep(1)
                    st.rerun()

                # [ADD] 전략 이름 변경 버튼
                if col_t3.button("📝 이름 변경", key=f"rename_btn_{m_code}_{stype}_{sym}_{disp_name}", width='stretch'):
                    st.session_state[f"show_rename_{disp_name}"] = True

                if st.session_state.get(f"show_rename_{disp_name}", False):
                    with st.container(border=True):
                        new_name = st.text_input("새 전략 별칭 입력", value=disp_name, key=f"new_name_val_{disp_name}")
                        c_rn1, c_rn2 = st.columns(2)
                        if c_rn1.button("🚀 변경 확정", key=f"conf_rn_{disp_name}", type="primary", width='stretch'):
                            success, msg = rename_strategy_db(sym, stype, m_code, disp_name, new_name)
                            if success:
                                st.success(msg)
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(msg)
                        if c_rn2.button("취소", key=f"can_rn_{disp_name}", width='stretch'):
                            st.session_state[f"show_rename_{disp_name}"] = False
                            st.rerun()

                # 개별 전략 삭제 버튼
                if st.button(f"🗑️ 전략 영구 삭제", key=f"del_tab_{m_code}_{stype}_{sym}_{disp_name}", width='stretch'):
                    delete_strategy_db(sym, stype, market=m_code, strategy_name=disp_name)
                    st.success(f"성공적으로 삭제되었습니다: {sym} ({disp_name})")
                    time.sleep(1)
                    st.rerun()
                    
with tab_analysis:
    st.header("🔍 실현 손익 분석")
    st.caption("DB에 기록된 거래 내역을 기반으로 다양한 통계를 제공합니다.")
    
    # 1. 필터 구성
    col_f1, col_f2, col_f3 = st.columns(3)
    analysis_market = col_f1.selectbox("시장 선택", ["전체", "KR", "US"])
    analysis_range = col_f2.selectbox("분석 단위", ["일별", "주간별", "월간별", "년간별"])
    
    # 데이터 로드
    cols, rows = get_detailed_trade_history_db(None)
    if not rows:
        st.info("분석할 거래 내역이 없습니다.")
    else:
        usd_krw = float(get_config("USDKRW", "1350.00"))
        df_all = pd.DataFrame(rows, columns=cols)
        df_all['date'] = pd.to_datetime(df_all['date'], format='mixed')
        
        # 매도 내역만 필터링
        df_sells = df_all[df_all['side'] == 'SELL'].copy()
        
        # [ADD] "전체" 선택 시 환율 반영 로직
        if analysis_market == "전체":
            # US 시장의 수익금을 원화로 환산 (임시 계산용)
            df_sells.loc[df_sells['market'] == 'US', 'realized_profit'] *= usd_krw
            analysis_currency = "₩"
        else:
            analysis_currency = "₩" if analysis_market == "KR" else "$"

        if analysis_market != "전체":
            df_sells = df_sells[df_sells['market'] == analysis_market]
            
        if df_sells.empty:
            st.warning("선택한 조건의 매도(실현손익) 내역이 없습니다.")
        else:
            # 2. 리샘플링 (시계열 분석)
            freq_map = {"일별": "D", "주간별": "W", "월간별": "MS", "년간별": "Y"}
            df_resampled = df_sells.set_index('date').resample(freq_map[analysis_range])['realized_profit'].sum().reset_index()
            
            # 3. 그래프 시각화
            fig_profit = go.Figure()
            fig_profit.add_trace(go.Bar(
                x=df_resampled['date'], 
                y=df_resampled['realized_profit'],
                marker_color='royalblue',
                name='실현 손익'
            ))
            
            # 누적 손익 라인 추가
            df_resampled['cumulative_profit'] = df_resampled['realized_profit'].cumsum()
            fig_profit.add_trace(go.Scatter(
                x=df_resampled['date'], 
                y=df_resampled['cumulative_profit'],
                line=dict(color='firebrick', width=3),
                name='누적 손익',
                yaxis='y2'
            ))
            
            market_suffix = f" (환율 1$: ₩{usd_krw:,.2f} 반영)" if analysis_market == "전체" else ""
            fig_profit.update_layout(
                title=f"{analysis_range} 수익 추이{market_suffix}",
                xaxis_title="기간",
                yaxis_title=f"실현 손익 ({analysis_currency})",
                yaxis2=dict(title=f'누적 손익 ({analysis_currency})', overlaying='y', side='right'),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified"
            )
            st.plotly_chart(fig_profit, width='stretch')
            
            # 4. 종목별 비중 파이 차트
            st.divider()
            col_c1, col_c2 = st.columns(2)
            
            with col_c1:
                st.subheader("📦 종목별 수익 비중")
                # [수정] 종목 식별을 쉽게 하기 위해 코드 (종목명) 형태로 라벨 생성
                df_sells['display_name'] = df_sells.apply(lambda x: format_ticker_display(x['symbol'], x['market']), axis=1)
                df_symbol = df_sells.groupby('display_name')['realized_profit'].sum().reset_index()
                fig_pie = go.Figure(data=[go.Pie(labels=df_symbol['display_name'], values=df_symbol['realized_profit'], hole=.3)])
                st.plotly_chart(fig_pie, width='stretch')
            
            with col_c2:
                st.subheader("🏷️ 전략별 수익 비중")
                df_strat = df_sells.groupby('strategy')['realized_profit'].sum().reset_index()
                fig_strat = go.Figure(data=[go.Pie(labels=df_strat['strategy'], values=df_strat['realized_profit'], hole=.3)])
                st.plotly_chart(fig_strat, width='stretch')

def render_exchange_rate_expander(market_code: str = "US", key_suffix: str = ""):
    """미국 환율(USD/KRW) 일별 변동 추이 expander 렌더링"""
    if market_code != "US":
        return
    with st.expander("💹 미국 환율(USD/KRW) 일별 변동 추이", expanded=False):
        try:
            history = get_exchange_rate_history_db(days=60)
            if history:
                df_ex = pd.DataFrame(history)
                df_ex['trade_date_dt'] = pd.to_datetime(df_ex['trade_date'])
                df_ex = df_ex.sort_values('trade_date_dt')

                # 상단 최신 요약
                latest = history[-1]
                rec_time_str = latest.get("recorded_at", "")
                hhmm = rec_time_str[11:16] if len(rec_time_str) >= 16 else ""
                time_disp = f" ({hhmm} KST)" if hhmm else ""
                
                c_sum1, c_sum2, c_sum3 = st.columns([1.5, 1.5, 2])
                c_sum1.metric("최근 개장 환율", f"₩{latest['rate']:,.2f}", f"{latest['diff']:+.2f}원 ({latest['pct']:+.2f}%)")
                c_sum2.metric("기준일", f"{latest['trade_date']}{time_disp}")
                c_sum3.caption(f"출처: {latest.get('source', 'MERITZ')} | 전일 개장 환율: ₩{latest['base_rate']:,.2f}")

                # Plotly 인터랙티브 라인 차트
                fig_ex = go.Figure()
                fig_ex.add_trace(go.Scatter(
                    x=df_ex['trade_date'],
                    y=df_ex['rate'],
                    mode='lines+markers',
                    name='USD/KRW 개장 환율',
                    line=dict(color='#2E7D32', width=2.5),
                    marker=dict(size=6, color='#1B5E20'),
                    customdata=df_ex[['diff', 'pct', 'recorded_at', 'source']],
                    hovertemplate="<b>거래일: %{x}</b><br>환율: ₩%{y:,.2f}<br>전일대비: %{customdata[0]:+.2f}원 (%{customdata[1]:+.2f}%)<br>기록시각: %{customdata[2]}<br>출처: %{customdata[3]}<extra></extra>"
                ))
                fig_ex.update_layout(
                    title="미국 정규장 개장(09:30 ET) 기준 USD/KRW 일별 환율 추이",
                    xaxis_title="거래일",
                    yaxis_title="환율 (₩)",
                    hovermode="x unified",
                    margin=dict(l=40, r=40, t=40, b=40),
                    height=350
                )
                st.plotly_chart(fig_ex, width='stretch', key=f"plotly_fx_chart_{key_suffix}" if key_suffix else None)

                # 최근 상세 테이블
                with st.expander("📋 일별 개장 환율 상세 기록 (최근순)", expanded=False):
                    df_table = pd.DataFrame(reversed(history))
                    df_table = df_table[['trade_date', 'rate', 'base_rate', 'diff', 'pct', 'recorded_at', 'source']]
                    df_table.columns = ['미국 거래일', '개장 환율(₩)', '전일 개장 환율(₩)', '변동(원)', '등락률(%)', '기록 일시(KST)', '출처']
                    st.dataframe(df_table, width='stretch', hide_index=True)
            else:
                st.info("ℹ️ DB에 저장된 일별 환율 기록이 없습니다. 미국장 개장 시 자동으로 기록됩니다.")
        except Exception as e:
            st.caption(f"환율 추이를 불러올 수 없습니다: {e}")

def render_forex_tab():
    """메리츠 실시간 외환 환전 및 관리 탭 - 환전 DCA/CA 전략 및 시장 지표(DXY, 3개월 평균) 연동"""
    st.subheader("💱 메리츠 외환 및 실시간 환전 관리 (Forex Management)")

    # [이벤트 배너]
    st.markdown("""
    <div style="background: linear-gradient(90deg, #1e3c72 0%, #2a5298 100%); padding: 14px 18px; border-radius: 8px; color: white; margin-bottom: 1.2rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <div>
                <span style="font-size: 1.15rem; font-weight: 700;">🎉 메리츠증권 외환 환전 수수료 100% 우대 이벤트 진행 중</span><br>
                <span style="font-size: 0.88rem; opacity: 0.9;">기본 스프레드(13.34원/USD) 100% 면제 ➔ <b>스프레드 0.00원 (No Spread)</b>으로 최적의 환율로 실시간 환전합니다.</span>
            </div>
            <div style="background-color: rgba(255,255,255,0.22); padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 0.95rem; text-align: center;">
                환율 우대<br><span style="font-size: 1.25rem; color: #ffe600;">100% (No Spread)</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.info("🕒 **USD 실시간 환전 가능 시간**: 영업일 **09:00 ~ 다음 날 02:00** (단, 시스템 점검시간 **23:50 ~ 00:20**은 환전 불가)")

    # 1. 실시간 고시환율 & 주요 시장 지표 (USD/KRW, DXY, 3개월 평균)
    # 세션 상태 기반 환율 데이터 관리
    def fetch_latest_rates(force: bool = False):
        if force or "fx_rates_summary" not in st.session_state:
            with st.spinner("메리츠 실시간 환율을 조회 중입니다..."):
                try:
                    summary = forex_manager.get_rates_summary("USD")
                    st.session_state.fx_rates_summary = summary
                except Exception as e:
                    logger.error(f"[FX Tab] 실시간 환율 종합 조회 오류: {e}")
                    if "fx_rates_summary" not in st.session_state:
                        st.session_state.fx_rates_summary = {
                            "crcd": "USD",
                            "stnd_rate": 1335.0,
                            "deal_stnd_rate": 1335.0,
                            "buy_rate": 1335.0,
                            "sell_rate": 1335.0,
                            "spread": 0.0,
                            "dcrt": 100.0,
                            "exrt_stnd_time": datetime.now().strftime("%Y%m%d%H%M%S"),
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }

    # 초기 로드
    fetch_latest_rates(force=False)

    # 상단 환율 헤더 & 실시간 환율 조회 버튼
    col_hdr_title, col_hdr_btn = st.columns([3, 1])
    with col_hdr_title:
        st.markdown("#### 📊 실시간 환율 및 주요 시장 지표 (USD / KRW)")
    with col_hdr_btn:
        if st.button("🔄 실시간 환율 조회", key="btn_refresh_fx_rates", help="메리츠 OpenAPI로부터 최신 기준환율, 매수환율, 매도환율을 즉시 조회합니다.", width='stretch'):
            fetch_latest_rates(force=True)
            st.toast("✅ 메리츠 실시간 환율이 최신 상태로 갱신되었습니다!", icon="💱")

    fx_summary = st.session_state.get("fx_rates_summary", {})
    stnd_rate = float(fx_summary.get("stnd_rate", 1335.0))
    cur_rate = stnd_rate  # 이전 변수 참조(DCA 평가 등) 호환성 유지
    deal_stnd_rate = float(fx_summary.get("deal_stnd_rate", 1335.0))
    buy_rate = float(fx_summary.get("buy_rate", stnd_rate))
    sell_rate = float(fx_summary.get("sell_rate", stnd_rate))
    spread_val = float(fx_summary.get("spread", 0.0))
    dcrt_val = float(fx_summary.get("dcrt", 100.0))
    exrt_time = fx_summary.get("exrt_stnd_time", "")
    updated_at = fx_summary.get("timestamp", "")

    # 전일 매매기준환율 대비 변동폭
    diff_val = round(stnd_rate - deal_stnd_rate, 2)
    pct_val = round((diff_val / deal_stnd_rate * 100.0), 2) if deal_stnd_rate > 0 else 0.0

    dxy_val = forex_manager.get_dxy_index()
    usd_3m_avg = forex_manager.get_3m_avg_rate("USD")

    col_rate_u, col_rate_d, col_rate_avg = st.columns([1.4, 1.0, 1.0])

    with col_rate_u:
        with st.container(border=True):
            st.markdown("##### 🇺🇸 USD / KRW 실시간 환율")
            # 기준 환율 메트릭
            st.metric(
                label="기준 환율 (고시)",
                value=f"₩{stnd_rate:,.2f}",
                delta=f"{diff_val:+.2f}원 ({pct_val:+.2f}%)" if deal_stnd_rate > 0 else None
            )
            # 기준 환율 아래 매수 환율 및 매도 환율 명확히 표시
            st.markdown(
                f"""
                <div style="background-color: rgba(30, 60, 114, 0.08); border-left: 3px solid #1e3c72; padding: 8px 10px; border-radius: 4px; margin-top: 6px; font-size: 0.9rem;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 3px;">
                        <span>🛒 <b>매수 환율 (원화➔달러)</b>:</span>
                        <span style="color: #d9534f; font-weight: bold;">₩{buy_rate:,.2f}원</span>
                    </div>
                    <div style="display: flex; justify-content: space-between;">
                        <span>💰 <b>매도 환율 (달러➔원화)</b>:</span>
                        <span style="color: #0275d8; font-weight: bold;">₩{sell_rate:,.2f}원</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            st.caption(
                f"• 기준시각: {exrt_time or '실시간'} | 우대율: {dcrt_val:.0f}% (스프레드 {spread_val:,.2f}원)\n\n"
                f"• 전일 매매기준율: ₩{deal_stnd_rate:,.2f} | 갱신: {updated_at[-8:] if len(updated_at) >= 8 else updated_at}"
            )

    with col_rate_d:
        with st.container(border=True):
            st.markdown("##### 🌐 달러 인덱스 (DXY)")
            dxy_status = "저평가 구역 (≤98)" if dxy_val <= 98.0 else "정상/강세 구역 (>98)"
            st.metric("DXY Index", f"{dxy_val:.2f}", dxy_status)
            st.caption(
                f"• 기준치: **98.0** 이하 시 저가 분할매수 권장\n\n"
                f"• 상태: **{'매수 호조건' if dxy_val <= 98.0 else '관망/분할 대응'}**"
            )

    with col_rate_avg:
        with st.container(border=True):
            st.markdown("##### 📊 3개월 평균 환율 (USD)")
            diff_from_avg = stnd_rate - usd_3m_avg
            pct_from_avg = ((stnd_rate - usd_3m_avg) / usd_3m_avg * 100) if usd_3m_avg > 0 else 0.0
            st.metric(
                label="3개월 평균선",
                value=f"₩{usd_3m_avg:,.2f}",
                delta=f"{diff_from_avg:+.2f}원 ({pct_from_avg:+.2f}%)",
                delta_color="inverse"
            )
            st.caption(
                f"• 평균 대비: **{'평균 이하 (매수 유리)' if stnd_rate <= usd_3m_avg else '평균 이상 (보수적 분할)'}**"
            )

    st.divider()

    # 2. 계좌 예수금 현황
    col_bal1, col_bal2 = st.columns(2)
    krw_cash = 0.0
    usd_cash = 0.0
    frcr_krw_eval = 0.0
    try:
        from core.brokers.meritz_kr import MeritzKrBroker
        from core.brokers.meritz_us import MeritzUsBroker
        kb = MeritzKrBroker()
        krw_cash = kb.get_cash_pool()
    except Exception as e:
        logger.error(f"[FX Tab] 원화예수금 조회 오류: {e}")
    try:
        ub = MeritzUsBroker()
        usd_cash = ub.get_cash_pool()
    except Exception as e:
        logger.error(f"[FX Tab] 외화예수금 조회 오류: {e}")

    try:
        val_data, _ = fetch_meritz_account_data(force=False)
        if val_data:
            frcr_krw_eval = float(val_data.get("frcr_tfam", 0.0))
            if krw_cash <= 0:
                krw_cash = float(val_data.get("tfam", 0.0))
            if usd_cash <= 0 and frcr_krw_eval > 0 and stnd_rate > 0:
                usd_cash = round(frcr_krw_eval / stnd_rate, 2)
    except Exception as e:
        logger.error(f"[FX Tab] 자산평가 연동 오류: {e}")

    if frcr_krw_eval <= 0 and usd_cash > 0 and stnd_rate > 0:
        frcr_krw_eval = usd_cash * stnd_rate

    max_buy_usd = (krw_cash / buy_rate) if buy_rate > 0 else ((krw_cash / stnd_rate) if stnd_rate > 0 else 0)

    with col_bal1:
        with st.container(border=True):
            st.markdown("##### 🇰🇷 원화(KRW) 가용예수금")
            st.markdown(f"<h2 style='color:#1e3c72; margin:0;'>₩{int(krw_cash):,}원</h2>", unsafe_allow_html=True)
            st.caption(f"적용 매수환율(₩{buy_rate:,.2f}) 기준 최대 환전 가능: **${max_buy_usd:,.2f}**")

    with col_bal2:
        with st.container(border=True):
            st.markdown("##### 🇺🇸 외화(USD) 가용예수금")
            st.markdown(f"<h2 style='color:#2a5298; margin:0;'>${usd_cash:,.2f}</h2>", unsafe_allow_html=True)
            est_sell_krw_val = int(usd_cash * sell_rate) if sell_rate > 0 else int(frcr_krw_eval)
            st.caption(f"적용 매도환율(₩{sell_rate:,.2f}) 기준 원화 환산: **약 ₩{est_sell_krw_val:,}원**")

    # 3. 실시간 수동 환전 실행 영역
    st.markdown("---")
    st.subheader("⚡ 실시간 수동 환전 (Manual Exchange)")
    with st.container(border=True):
        col_fx_dir, col_fx_amt = st.columns([1.5, 2])
        with col_fx_dir:
            fx_direction = st.radio(
                "환전 방향 선택",
                ["원화 ➔ 외화 매수 (KRW → USD)", "외화 매도 ➔ 원화 회수 (USD → KRW)"],
                key="manual_fx_direction_choice"
            )
            is_buy = "외화 매수" in fx_direction

            # 방향별 실시간 적용 환율 배지
            active_rate = buy_rate if is_buy else sell_rate
            dir_tag = "외화 매수" if is_buy else "외화 매도"
            st.markdown(
                f"""
                <div style="margin-top: 10px; padding: 10px 14px; background-color: {'#eef7ed' if is_buy else '#e8f4fd'}; border: 1px solid {'#81c784' if is_buy else '#90caf9'}; border-radius: 6px;">
                    <div style="font-size: 0.85rem; color: #555;">실시간 적용 환율 ({dir_tag})</div>
                    <div style="font-size: 1.35rem; font-weight: bold; color: {'#2e7d32' if is_buy else '#1565c0'};">₩{active_rate:,.2f}원</div>
                    <div style="font-size: 0.8rem; color: #777;">(기준환율: ₩{stnd_rate:,.2f} | 우대율: {dcrt_val:.0f}%)</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with col_fx_amt:
            if is_buy:
                calc_mode = st.radio("입력 기준", ["달러($) 기준 입력", "원화(₩) 기준 입력"], horizontal=True, key="fx_input_mode_buy")
                if calc_mode == "달러($) 기준 입력":
                    input_usd = st.number_input("환전할 외화 금액 ($)", min_value=1.0, value=100.0, step=10.0, format="%.2f")
                    est_krw = int(input_usd * buy_rate)
                    st.info(f"💡 필요 원화 예상 금액: **약 {est_krw:,}원** (적용 매수환율 ₩{buy_rate:,.2f})")
                    if krw_cash > 0 and est_krw > krw_cash:
                        st.warning(f"⚠️ 현재 보유 가용 원화(₩{int(krw_cash):,}원)를 초과하는 금액입니다.")
                    req_usd, req_krw = input_usd, 0.0
                else:
                    input_krw = st.number_input("환전할 원화 금액 (₩)", min_value=10000, value=1000000, step=10000, format="%d")
                    est_usd = (input_krw / buy_rate) if buy_rate > 0 else 0
                    st.info(f"💡 수령 달러 예상 금액: **약 ${est_usd:,.2f}** (적용 매수환율 ₩{buy_rate:,.2f})")
                    if krw_cash > 0 and input_krw > krw_cash:
                        st.warning(f"⚠️ 현재 보유 가용 원화(₩{int(krw_cash):,}원)를 초과하는 금액이 입력되었습니다.")
                    req_usd, req_krw = 0.0, float(input_krw)
            else:
                default_sell_val = min(float(usd_cash), 100.0) if usd_cash >= 1.0 else (usd_cash if usd_cash > 0 else 1.0)
                input_usd_sell = st.number_input(
                    "환전(매도)할 외화 금액 ($)",
                    min_value=0.1 if usd_cash > 0 else 1.0,
                    value=default_sell_val,
                    step=10.0,
                    format="%.2f"
                )
                est_krw_sell = int(input_usd_sell * sell_rate)
                st.info(f"💡 원화 입금 예상 금액: **약 {est_krw_sell:,}원** (적용 매도환율 ₩{sell_rate:,.2f})")
                if usd_cash > 0 and input_usd_sell > usd_cash:
                    st.warning(f"⚠️ 현재 보유 외화 예수금(${usd_cash:,.2f})보다 큰 금액이 입력되었습니다.")
                req_usd, req_krw = input_usd_sell, 0.0

        st.caption("※ 실시간 환전 가능 시간: 영업일 09:00 ~ 다음 날 02:00 (전산 점검시간 23:50 ~ 00:20 제외). 실거래 시 메리츠 100% 우대 스프레드가 적용되어 고시된 적용환율 그대로 환전됩니다.")

        col_exec1, col_exec2 = st.columns([1, 2])
        with col_exec1:
            confirm_check = st.checkbox("환전 내용 확인 및 실행 동의", key="fx_confirm_chk")
        with col_exec2:
            if st.button("💱 실시간 환전 실행", type="primary", disabled=not confirm_check, width='stretch'):
                dir_param = "BUY" if is_buy else "SELL"
                dir_label = "원화 ➔ USD 외화매수" if is_buy else "USD ➔ 원화 외화매도"
                with st.spinner(f"메리츠 {dir_label} 환전 처리 중..."):
                    ok = forex_manager.execute_exchange(
                        direction=dir_param,
                        amount_usd=req_usd,
                        amount_krw=req_krw,
                        note="대시보드 수동 환전"
                    )
                    if ok:
                        st.success(f"✅ {dir_label} 환전이 성공적으로 완료되었습니다!")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("❌ 환전 요청이 실패하였습니다. 시스템 로그를 확인하세요.")

    # 4. 외환 조건부 분할 자동매매 (Forex DCA & Scalping / 환전 CA 전략)
    st.markdown("---")
    st.subheader("🤖 외환 조건부 분할 자동매매 (Forex DCA & Scalping Engine)")
    st.markdown(
        """
        <div style='background: rgba(30, 60, 114, 0.06); padding: 0.8rem 1rem; border-left: 4px solid #2a5298; border-radius: 4px; font-size: 0.88rem; margin-bottom: 1rem;'>
            <b>💡 외환 조건부 분할 매매(DCA) 운영 로직 (운영시간: 영업일 09:00 ~ 익일 02:00, 점검시간 제외)</b><br>
            • <b>진입 조건</b>: 3개월 평균 환율보다 낮거나 달러인덱스(DXY)가 98 이하일 때 1회차 자동 매수 시작<br>
            • <b>분할 매수</b>: 진입 후 직전 매수 환율 대비 <b>0.5%씩 하락할 때마다</b> 회차별 설정 금액 자동 추가 환전 매수<br>
            • <b>분할 익절</b>: 평균 매수 환율 대비 <b>+1% ~ +3% 상승 시 33%씩 순차 분할 매도</b> 또는 <b>목표 수익률 도달 시 전액 매도</b>
        </div>
        """,
        unsafe_allow_html=True
    )

    dca_state = forex_dca_engine.load_state()

    with st.container(border=True):
        st.markdown("#### ⚙️ 외환 자동매매 전략 파라미터 설정")
        col_dca_cfg1, col_dca_cfg2 = st.columns(2)

        with col_dca_cfg1:
            dca_active = st.toggle("외환 분할 자동매매 가동 (ACTIVE)", value=bool(dca_state.get("is_active", False)))
            st.caption("ℹ️ 스케줄러가 메리츠 실시간 환전 시간(영업일 09:00 ~ 익일 02:00, 점검시간 23:50~00:20 제외) 동안 10분마다 환율 조건을 감시하여 자동 환전 매수/익절을 수행합니다.")

            entry_opts = ["3개월 평균 환율 이하 진입 (3M_AVG)", "달러인덱스(DXY) 기준치 이하 진입 (DXY_BELOW)", "지정 목표 환율 이하 진입 (MANUAL_TARGET)"]
            cur_entry_type = dca_state.get("entry_condition_type", "3M_AVG")
            def_entry_idx = 0 if cur_entry_type == "3M_AVG" else (1 if cur_entry_type == "DXY_BELOW" else 2)
            sel_entry_str = st.selectbox("진입(트리거) 기준 조건", entry_opts, index=def_entry_idx)
            sel_entry_type = "3M_AVG" if "3M_AVG" in sel_entry_str else ("DXY_BELOW" if "DXY_BELOW" in sel_entry_str else "MANUAL_TARGET")

            if sel_entry_type == "DXY_BELOW":
                dxy_target = st.number_input("달러인덱스(DXY) 기준치 이하", min_value=80.0, max_value=120.0, value=float(dca_state.get("target_benchmark_val", 98.0)), step=0.5)
            elif sel_entry_type == "MANUAL_TARGET":
                dxy_target = st.number_input("지정 목표 환율 이하 (원)", min_value=500.0, max_value=2000.0, value=float(dca_state.get("target_benchmark_val", 1350.0)), step=5.0)
            else:
                dxy_target = 0.0
                st.caption(f"💡 현재 3개월 평균 환율: **₩{usd_3m_avg:,.2f}** (자동 추적 진입)")

        with col_dca_cfg2:
            buy_unit_val = float(dca_state.get("buy_unit_amount", 100.0))
            def_unit = buy_unit_val if buy_unit_val > 0 else 100.0
            inp_unit_amt = st.number_input("1회차 분할 매수 금액 ($)", min_value=10.0, value=def_unit, step=10.0, format="%.2f")
            inp_drop_step = st.number_input("추가 분할 매수 하락 간격 (%)", min_value=0.1, max_value=5.0, value=float(dca_state.get("drop_buy_step_pct", 0.5)), step=0.1)
            inp_max_rounds = st.number_input("최대 분할 매수 회차 (N회)", min_value=2, max_value=50, value=int(dca_state.get("max_buy_rounds", 10)), step=1)

            sell_strat_opts = ["3단계 분할 익절 (+1%, +2%, +3% 상승 시 33%씩)", "목표 수익률 일괄 전액 익절"]
            cur_sell_type = dca_state.get("sell_strategy_type", "SPLIT_3")
            def_sell_idx = 0 if cur_sell_type == "SPLIT_3" else 1
            sel_sell_str = st.selectbox("익절(매도) 전략 방식", sell_strat_opts, index=def_sell_idx)
            sel_sell_type = "SPLIT_3" if "3단계" in sel_sell_str else "FULL_TARGET"

            if sel_sell_type == "FULL_TARGET":
                target_profit_in = st.number_input("목표 수익률 (%)", min_value=0.5, max_value=20.0, value=float(dca_state.get("target_sell_profit_pct", 1.5)), step=0.1)
            else:
                target_profit_in = 1.5
                st.caption("💡 +1.0%에 33%, +2.0%에 33%, +3.0%에 잔여 전액 순차 분할 익절")

        col_save_dca1, col_save_dca2 = st.columns([1, 1])
        with col_save_dca1:
            if st.button("💾 외환 DCA 전략 설정 저장", type="primary", width='stretch'):
                dca_state["is_active"] = dca_active
                dca_state["currency"] = "USD"
                dca_state["entry_condition_type"] = sel_entry_type
                dca_state["target_benchmark_val"] = dxy_target
                dca_state["buy_unit_amount"] = inp_unit_amt
                dca_state["drop_buy_step_pct"] = inp_drop_step
                dca_state["max_buy_rounds"] = inp_max_rounds
                dca_state["sell_strategy_type"] = sel_sell_type
                dca_state["target_sell_profit_pct"] = target_profit_in
                forex_dca_engine.save_state(dca_state)
                st.success("✅ 외환 DCA 전략 설정이 성공적으로 저장되었습니다.")
                time.sleep(1)
                st.rerun()

        with col_save_dca2:
            if st.button("▶ 외환 조건 즉시 평가 및 1회 실행", width='stretch', help="현재 환율 및 지표 조건을 즉시 평가하여 조건 충족 시 주문을 실행합니다."):
                with st.spinner("외환 조건 평가 중..."):
                    res = forex_dca_engine.evaluate_tick()
                    action = res.get("action")
                    if action == "BUY":
                        st.success(f"🎉 [매수 체결] {res.get('round')}회차 매수 완료! (환율 ₩{res.get('rate'):,.2f})")
                    elif action == "SELL":
                        st.success(f"🎊 [익절 체결] {res.get('stage')}단계 매도 완료! (수익률 +{res.get('profit_pct'):.2f}%)")
                    else:
                        st.info(f"ℹ️ [조건 미충족] {res.get('reason')} - 현재 환율 ₩{cur_rate:,.2f}")
                    time.sleep(1.5)
                    st.rerun()

    # 외환 DCA 현재 진행 현황 모니터링 카드
    st.markdown("#### 📊 외환 분할 매매 현재 진행 상태")
    cur_rnd = int(dca_state.get("current_round", 0))
    max_rnd = int(dca_state.get("max_buy_rounds", 10))
    tot_f = float(dca_state.get("total_fiat_bought", 0.0))
    avg_p = float(dca_state.get("avg_buy_rate", 0.0))
    last_p = float(dca_state.get("last_buy_rate", 0.0))

    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
    with col_stat1:
        prog = min(cur_rnd / max_rnd, 1.0) if max_rnd > 0 else 0.0
        st.metric("분할 매수 회차", f"{cur_rnd} / {max_rnd} 회", f"{prog*100:.0f}% 진행")
        st.progress(prog)
    with col_stat2:
        st.metric("누적 보유 외화", f"${tot_f:,.2f}")
    with col_stat3:
        st.metric("평균 매수 환율", f"₩{avg_p:,.2f}" if avg_p > 0 else "미매수")
    with col_stat4:
        if avg_p > 0 and cur_rate > 0:
            unrealized_pct = ((cur_rate - avg_p) / avg_p) * 100.0
            st.metric("현재 평가 손익률", f"{unrealized_pct:+.2f}%", f"현재 ₩{cur_rate:,.2f}")
        else:
            st.metric("현재 평가 손익률", "0.00%")

    # 5. 스마트 자동 환전 (CAVR Auto-Funding) 운영 설정
    st.markdown("---")
    st.subheader("🤖 스마트 자동 환전 운영 정책 (CAVR Auto-Funding)")
    with st.container(border=True):
        col_set1, col_set2 = st.columns(2)
        with col_set1:
            cur_fx_auto = get_config("FX_MODE", "AUTO" if getattr(settings, "FX_AUTO_EXCHANGE", True) else "MANUAL") == "AUTO"
            toggle_auto_fx = st.toggle("미국 주식 매수 시 달러 부족분 자동 환전 (Auto-Funding)", value=cur_fx_auto)
            buf_usd = st.number_input("자동 충전 시 여유 버퍼 ($)", min_value=0.0, value=float(get_config("FX_BUFFER_USD", "10.0")), step=5.0)
        with col_set2:
            cur_harvest = get_config("FX_HARVEST_ENABLED", "true") == "true"
            toggle_harvest = st.toggle("미국 주식 익절 매도 후 원화 자동 회수 (Profit-Harvesting)", value=cur_harvest)
            harvest_ratio = st.slider("수익금 원화 환전 회수 비율 (%)", min_value=10, max_value=100, value=int(get_config("FX_HARVEST_RATIO", "100")), step=10)

        if st.button("💾 자동 환전 운영 정책 저장", type="primary"):
            new_mode_str = "AUTO" if toggle_auto_fx else "MANUAL"
            set_config("FX_MODE", new_mode_str)
            set_config("FX_BUFFER_USD", f"{buf_usd:.2f}")
            set_config("FX_HARVEST_ENABLED", "true" if toggle_harvest else "false")
            set_config("FX_HARVEST_RATIO", str(harvest_ratio))
            settings.FX_AUTO_EXCHANGE = toggle_auto_fx
            st.success("✅ 외환 운영 정책이 저장되었습니다.")
            time.sleep(1)
            st.rerun()

    # 6. 환전 체결 이력 테이블
    st.markdown("---")
    st.subheader("📜 실시간 환전 체결 기록 (Forex History)")
    forex_records = get_forex_history_db(limit=50)
    if not forex_records:
        st.info("💡 아직 환전 체결 기록이 없습니다. (자동 또는 수동 환전 시 실시간 기록됩니다)")
    else:
        df_fx = pd.DataFrame(forex_records)
        disp_cols = ["created_at", "direction", "applied_rate", "wncr_amt", "frcr_amt", "fee", "spread", "tr_srno", "note"]
        avail_cols = [c for c in disp_cols if c in df_fx.columns]
        df_fx_disp = df_fx[avail_cols].rename(columns={
            "created_at": "환전 일시",
            "direction": "구분",
            "applied_rate": "적용 환율(원)",
            "wncr_amt": "원화 금액",
            "frcr_amt": "외화 금액",
            "fee": "수수료",
            "spread": "스프레드",
            "tr_srno": "거래번호",
            "note": "비고"
        })
        st.dataframe(df_fx_disp, width='stretch')

with tab_us:
    render_market_tab("US")
with tab_kr:
    render_market_tab("KR")
with tab_forex:
    render_forex_tab()
with tab_finished:
    st.subheader("🏁 종료된 전략 이력 관리")
    finished_rows = get_finished_states_db()
    if not finished_rows:
        st.info("아직 종료된 전략이 없습니다.")
    else:
        f_data = []
        # 정확한 실현 손익 합산을 위해 전체 거래 내역을 로드합니다.
        _, all_th_rows = get_detailed_trade_history_db(None)

        for row in finished_rows:
            sym, stype, m_code, alias, s_json, f_at = row
            cur_sym = "₩" if m_code == "KR" else "$"
            
            # [ADD] 미국주식(US)인 경우 종료일시(UTC)를 한국 시간(KST)으로 변환하여 표시
            display_f_at = f_at
            if m_code == "US" and f_at:
                try:
                    import pytz
                    utc_dt = datetime.strptime(f_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.utc)
                    kst_dt = utc_dt.astimezone(pytz.timezone('Asia/Seoul'))
                    display_f_at = kst_dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            
            # 해당 전략 별칭(alias)에 해당하는 모든 매도(SELL) 거래의 실현 손익을 합산합니다.
            # r[1]: symbol, r[3]: market, r[4]: strategy_name, r[5]: side, r[14]: realized_profit
            strat_trades = [r for r in all_th_rows if r[1] == sym and r[3] == m_code and r[4] == alias]
            
            total_buy = sum(float(r[10] or 0) for r in strat_trades if r[5] == 'BUY')
            total_sell = sum(float(r[10] or 0) for r in strat_trades if r[5] == 'SELL')
            realized_sum = total_sell - total_buy
            
            p_rate = (realized_sum / total_buy * 100) if total_buy > 0 else 0
            
            profit_info = f"수익: {cur_sym}{format_currency(realized_sum, m_code)} ({p_rate:+.2f}%)"
            
            f_data.append({
                "종료일시": display_f_at, "시장": m_code, "종목": sym, "전략": stype, "별칭": alias, 
                "매수원금": total_buy, "매도금액": total_sell, "실현손익": realized_sum, "수익률": p_rate,
                "상태요약": profit_info,
                "s_json": s_json
            })
        
        df_fin = pd.DataFrame(f_data)
        st.dataframe(df_fin[["종료일시", "시장", "종목", "전략", "별칭", "상태요약"]], width='stretch')
        
        # 상세 내역 조회를 위한 선택기
        st.divider()
        st.subheader("🔍 종료된 전략 상세 내역 조회")
        target_fin = st.selectbox("조회할 종료된 전략 선택", 
                                  options=[f"{r['별칭']} ({r['종목']})" for r in f_data],
                                  key="fin_detail_selector")
        
        if target_fin:
            # 별칭 추출
            sel_alias = target_fin.split(" (")[0]
            sel_row = next(r for r in f_data if r['별칭'] == sel_alias)
            sel_sym = sel_row['종목']
            sel_m = sel_row['시장']
            
            # 실현 손익 및 거래 내역 표시
            st.info(f"📝 **{sel_alias}** 전략의 기록을 불러옵니다.")
            
            cols_h, rows_h = get_detailed_trade_history_db(sel_sym, market=sel_m)
            if rows_h:
                df_h = pd.DataFrame(rows_h, columns=cols_h)
                # 해당 별칭 내역만 필터링 (strategy_name 컬럼 기준)
                df_h_filtered = df_h[df_h['strategy_name'] == sel_alias].copy()
                
                # [상세 통계 제시]
                df_sells = df_h_filtered[df_h_filtered['side'] == 'SELL'].copy()
                df_buys = df_h_filtered[df_h_filtered['side'] == 'BUY']
                
                t_buy_amt = df_buys['total_amount'].sum()
                t_sell_amt = df_sells['total_amount'].sum()
                t_profit = t_sell_amt - t_buy_amt
                t_rate = (t_profit / t_buy_amt * 100) if t_buy_amt > 0 else 0
                t_max = df_h_filtered['turn'].max()
                
                # [신규] 실현 손익 기반 MDD 계산 (예산 + 누적 수익 곡선 활용)
                mdd_val = 0.0
                try:
                    state_dict = json.loads(sel_row['s_json'])
                    # 예산 정보 추출 (CA는 cycle_budget, VR은 initial_budget 사용)
                    budget = float(state_dict.get('cycle_budget') or state_dict.get('initial_budget') or 0)
                    if budget > 0 and not df_sells.empty:
                        # 날짜(date) 기준으로 정렬하여 실현 수익 곡선 생성 (timestamp 통합 반영)
                        df_s_sorted = df_sells.sort_values('date')
                        cum_profit = df_s_sorted['realized_profit'].cumsum()
                        equity_curve = budget + cum_profit
                        peak = equity_curve.cummax()
                        drawdown = (equity_curve - peak) / peak
                        mdd_val = drawdown.min() * 100
                except:
                    pass

                c_st1, c_st2, c_st3, c_st4, c_st5, c_st6 = st.columns(6)
                currency_unit = "₩" if sel_m == "KR" else "$"
                c_st1.metric("총 매수 금액", f"{currency_unit}{format_currency(t_buy_amt, sel_m)}")
                c_st2.metric("총 매도 금액", f"{currency_unit}{format_currency(t_sell_amt, sel_m)}")
                c_st3.metric("실현 수익금", f"{currency_unit}{format_currency(t_profit, sel_m)}", delta=f"{t_rate:+.2f}%")
                c_st4.metric("거래 횟수", f"{len(df_h_filtered)}회")
                if sel_row['전략'] == "CA":
                    c_st5.metric("최대 회차 (T_max)", f"{t_max:.1f}T")
                else:
                    # VR MDD 시뮬레이션 (단순화: 평가금 기반 MDD는 백테스트에서 수행하므로 여기선 실현손익 MDD 생략)
                    c_st5.metric("전략 유형", "VR")
                c_st6.metric("실현 MDD", f"{mdd_val:.2f}%")

                st.dataframe(df_h_filtered, width='stretch')
            else:
                st.caption("관련 거래 내역이 없습니다.")

with tab_settings:
    st.header("⚙️ 시스템 및 사용자 설정")
    
    with st.expander("👤 사용자 정보", expanded=True):
        default_user_display = get_config("user_name")
        if not default_user_display:
            default_user_display = st.session_state.get("username", "Investor")
        u_name = st.text_input("사용자 이름", value=default_user_display)
        if st.button("사용자 정보 저장"):
            set_config("user_name", u_name)
            try:
                import sqlite3
                conn = sqlite3.connect(os.path.join(PROJECT_ROOT, "data", "cavr.db"))
                cursor = conn.cursor()
                cursor.execute("UPDATE user_auth SET username=? WHERE email=?", (u_name, st.session_state.user_email))
                conn.commit()
                conn.close()
                st.session_state["username"] = u_name
            except Exception as u_err:
                logger.error(f"사용자 이름 업데이트 실패: {u_err}")
            st.success("사용자 정보가 저장되었습니다.")
            st.rerun()
            
    with st.expander("📧 이메일 알림 설정 (SMTP)"):
        st.caption("시스템 중요 알림 및 일일 보고서를 수신할 Zoho SMTP 설정을 관리합니다.")
        env_path = os.path.join(PROJECT_ROOT, "env", ".env")
        
        z_user = st.text_input("Zoho 계정 (Email)", value=os.getenv("ZOHO_SMTP_USER", ""))
        z_pass = st.text_input("Zoho 앱 비밀번호", value=os.getenv("ZOHO_SMTP_PASSWORD", ""), type="password")
        z_recv = st.text_input("수신용 이메일", value=os.getenv("ZOHO_RECEIVER_EMAIL", ""))

        if st.button("SMTP 설정 저장 (.env 업데이트)"):
            set_key(env_path, "ZOHO_SMTP_USER", z_user)
            set_key(env_path, "ZOHO_SMTP_PASSWORD", z_pass)
            set_key(env_path, "ZOHO_RECEIVER_EMAIL", z_recv)
            st.success("환경 변수 파일이 업데이트되었습니다. 시스템 재시작 후 반영됩니다.")
            load_dotenv(env_path, override=True)

    with st.expander("📜 종목 리스트 관리"):
        st.caption("ETF_list 파일을 직접 수정하거나 삭제합니다. (형식: 코드 \"종목명\")")
        m_list_choice = st.radio("시장 선택", ["KR", "US"], horizontal=True, key="m_list_edit_choice")
        list_file_name = f"ETF_list_{m_list_choice.lower()}.txt"
        list_file_path = os.path.join(PROJECT_ROOT, "env", list_file_name)
        
        if os.path.exists(list_file_path):
            # 파일 읽기 및 파싱
            with open(list_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            list_entries = []
            for line in lines:
                clean_line = line.split('#')[0].strip()
                if clean_line:
                    parts = clean_line.split(None, 1)
                    ticker_code = parts[0].upper()
                    ticker_name = parts[1].strip().strip('"') if len(parts) > 1 else ticker_code
                    list_entries.append({"Ticker": ticker_code, "Name": ticker_name})
            
            df_list_edit = pd.DataFrame(list_entries)
            
            # Data Editor (num_rows="dynamic"을 통해 추가/삭제 가능)
            edited_list_df = st.data_editor(
                df_list_edit,
                num_rows="dynamic",
                column_config={
                    "Ticker": st.column_config.TextColumn("종목 코드", required=True, help="예: 122630 또는 TQQQ"),
                    "Name": st.column_config.TextColumn("종목명", required=True),
                },
                hide_index=True,
                width='stretch',
                key=f"list_editor_widget_{m_list_choice}"
            )
            
            if st.button(f"💾 {m_list_choice} 리스트 변경 사항 저장", key=f"save_list_btn_{m_list_choice}", width='stretch', type="primary"):
                try:
                    with open(list_file_path, 'w', encoding='utf-8') as f:
                        for _, row in edited_list_df.iterrows():
                            t_val = str(row["Ticker"]).strip().upper()
                            n_val = str(row["Name"]).strip()
                            if t_val and n_val:
                                f.write(f'{t_val} "{n_val}"\n')
                    st.success(f"✅ {list_file_name}에 변경 사항이 저장되었습니다.")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"파일 저장 중 오류 발생: {e}")
        else:
            st.error(f"파일을 찾을 수 없습니다: {list_file_path}")

    with st.expander("📁 데이터베이스(cavr.db) 직접 확인"):
        db_path = os.path.join(PROJECT_ROOT, "data", "cavr.db")
        if os.path.exists(db_path):
            st.write(f"DB 경로: `{db_path}`")
            try:
                conn = sqlite3.connect(db_path)
                
                table_name = st.selectbox("테이블 선택", ["trade_history", "strategy_state", "order_history", "config"], key="db_table_sel")
                
                limit = st.number_input("조회 개수", value=50, step=10)
                query = f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT {limit}"
                df_raw = pd.read_sql_query(query, conn)
                st.dataframe(df_raw, width='stretch')
                conn.close()
            except Exception as e:
                st.error(f"DB 조회 중 오류: {e}")
        else:
            st.error(f"DB 파일을 찾을 수 없습니다: {db_path}")

    st.divider()
    st.subheader("⚠️ 시스템 관리")

    with st.expander("🛠️ 데이터 정합성 도구", expanded=False):
        st.write("동기화 오류로 인해 가격이나 수량이 0으로 표시되는 주문들을 정리합니다.")
        if st.button("🗑️ 불완전한 주문 내역(0원/0주) 강제 삭제", width='stretch'):
            count = cleanup_invalid_orders_db()
            if count > 0:
                st.success(f"✅ {count}개의 잘못된 주문 내역을 정리했습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.info("정리할 대상이 없습니다.")

        if st.button("🧹 중복 주문(이미 체결됨) 정리", width='stretch'):
            count = cleanup_processed_orders_db()
            if count > 0:
                st.success(f"✅ {count}개의 중복된 미체결 내역을 정리했습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.info("정리할 중복 내역이 없습니다.")

    with st.expander("🛠️ 실현 손익 데이터 복구 (Cleanup)", expanded=False):
        st.write("DB의 실현 손익이 0이거나 부정확한 경우, 거래 내역을 시간순으로 재추적하여 평단가와 이익을 재계산합니다.")
        target_recalc_sym = st.text_input("대상 종목 코드 (예: 122630)", value=symbol)
        if st.button(f"🔄 {target_recalc_sym} 손익 전체 재계산 실행", width='stretch', type="primary"):
            success, msg = recalculate_all_profits_db(target_recalc_sym, market_code)
            if success:
                st.success(msg)
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)

    st.warning("프로그램 수정 후 재시작이 필요한 경우 아래 버튼을 사용하여 안전하게 종료하세요.")
    
    if st.button("🛑 전체 시스템 종료 (Full Shutdown)", help="대시보드와 백그라운드 스케줄러를 모두 종료합니다.", width='stretch'):
        # 스케줄러 종료를 위한 DB 플래그 설정
        set_config("system_shutdown_flag", "true")
        st.error("시스템 종료 명령을 전송했습니다. 잠시 후 대시보드가 닫힙니다.")
        
        # 텔레그램 알림 전송 (선택 사항)
        send_telegram_message("🛑 <b>[시스템]</b> 사용자에 의해 시스템 종료 명령이 실행되었습니다.")
        
        time.sleep(3)
        os._exit(0)

st.divider()
st.subheader(f"🛠️ 현재 작업 대상: {active_market_display} / {format_ticker_display(symbol, market_code)} ({strategy_alias})")

# --- 실시간 시세 헤더 (프래그먼트) ---
@st.fragment(run_every=10)
def display_realtime_header():
    if mode == "실전 투자":
        is_active, now = check_market_active(market_code)
        if not is_active:
            st.info(f"😴 {market_code} 시장 운영 시간 외입니다. ({now.strftime('%H:%M')})")
            
            # [ADD] 미국 시장인 경우 운영 시간 외라도 환율 메트릭 및 환율 그래프 표시
            if market_code == "US":
                usd_krw = float(get_config("USDKRW", "0.00"))
                if usd_krw <= 0:
                    latest_rec = get_latest_exchange_rate_db()
                    if latest_rec and latest_rec.get("rate", 0) > 0:
                        usd_krw = float(latest_rec["rate"])
                        set_config("USDKRW", f"{usd_krw:.2f}")
                        set_config("USDKRW_DIFF", f"{latest_rec.get('diff', 0.0):+.2f}")
                        set_config("USDKRW_PCT", f"{latest_rec.get('pct', 0.0):+.2f}")
                        set_config("USDKRW_UPDATE_TIME", latest_rec.get("recorded_at", "N/A"))
                    else:
                        try:
                            live_fx = ActiveBroker.get_exchange_rate(force=True)
                            if live_fx and live_fx.get("rate", 0) > 0:
                                usd_krw = float(live_fx["rate"])
                                set_config("USDKRW", f"{usd_krw:.2f}")
                                set_config("USDKRW_DIFF", f"{live_fx.get('diff', 0.0):+.2f}")
                                set_config("USDKRW_PCT", f"{live_fx.get('pct', 0.0):+.2f}")
                                set_config("USDKRW_UPDATE_TIME", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        except Exception:
                            pass
                usd_diff = float(get_config("USDKRW_DIFF", "0.00"))
                usd_pct = float(get_config("USDKRW_PCT", "0.00"))
                delta_fx = f"{usd_diff:+.2f}원 ({usd_pct:+.2f}%)"
                fx_time = get_config("USDKRW_UPDATE_TIME", "N/A")
                
                col1, col2, col3 = st.columns([1.5, 1.5, 2])
                col1.metric(label="환율 (정규장 개장 09:30 ET 기준)", value=f"₩{usd_krw:,.2f}", delta=delta_fx)
                with col1:
                    st.caption(f"기준: 전일 개장 대비 | {fx_time}")
                    if st.button("🔄 지금 환율 조회", key="manual_fx_update_inactive", help="메리츠 실시간 적용환율을 즉시 조회하여 화면 및 시스템에 갱신합니다."):
                        with st.spinner("실시간 환율 조회 중..."):
                            live_info = ActiveBroker.get_exchange_rate(force=True)
                            cur_rate = float(live_info.get("rate", 0.0))
                            cur_diff = float(live_info.get("diff", 0.0))
                            cur_pct = float(live_info.get("pct", 0.0))
                            now_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if cur_rate > 0:
                                set_config("USDKRW", f"{cur_rate:.2f}")
                                set_config("USDKRW_DIFF", f"{cur_diff:+.2f}")
                                set_config("USDKRW_PCT", f"{cur_pct:+.2f}")
                                set_config("USDKRW_UPDATE_TIME", now_time_str)
                            st.session_state["manual_live_fx"] = {
                                "rate": cur_rate,
                                "diff": cur_diff,
                                "pct": cur_pct,
                                "time": live_info.get("time", datetime.now().strftime("%H:%M:%S")),
                                "source": live_info.get("source", "MERITZ")
                            }
                        st.rerun()
                col2.write("")
                col3.caption(f"⏱️ [{market_code}] 시장 운영 시간 외 | {datetime.now().strftime('%H:%M:%S')}")
                
                if "manual_live_fx" in st.session_state and st.session_state["manual_live_fx"].get("rate", 0) > 0:
                    lfx = st.session_state["manual_live_fx"]
                    st.info(f"🔍 **실시간 환율**: 1$ = **₩{lfx['rate']:,.2f}** ({lfx.get('diff', 0):+.2f}원, {lfx.get('pct', 0):+.2f}%) (기준 시각: {lfx['time']}, 출처: {lfx['source']})")

                # 환율 변동 추이 그래프 (Expander)
                render_exchange_rate_expander(market_code="US", key_suffix="inactive_header")
                st.divider()
            return
        try:
            broker = ActiveBroker
            price = broker.get_price(symbol)
            
            # [추가] 브로커 조회 실패 시 DB 캐시 확인
            if price is None or price <= 0:
                state = load_state_db(symbol, strategy_choice, market=market_code, strategy_name=strategy_alias)
                price = state.get('current_price', 0) if state else 0
                if price <= 0:
                    st.warning("⚠️ 현재가를 가져올 수 없습니다. (휴장 또는 통신 지연)")
                    return
                
            prev_close = broker.get_previous_close(symbol)
            if price > 0:
                diff = price - prev_close
                pct = (diff / prev_close * 100) if prev_close > 0 else 0
                
                diff_fmt = f"{int(diff):+,}" if market_code == "KR" else f"{diff:+.2f}"
                delta_val = f"{diff_fmt} ({pct:+.2f}%)"
                
                if market_code == "US":
                    usd_krw = float(get_config("USDKRW", "0.00"))
                    if usd_krw <= 0:
                        latest_rec = get_latest_exchange_rate_db()
                        if latest_rec and latest_rec.get("rate", 0) > 0:
                            usd_krw = float(latest_rec["rate"])
                            set_config("USDKRW", f"{usd_krw:.2f}")
                            set_config("USDKRW_DIFF", f"{latest_rec.get('diff', 0.0):+.2f}")
                            set_config("USDKRW_PCT", f"{latest_rec.get('pct', 0.0):+.2f}")
                            set_config("USDKRW_UPDATE_TIME", latest_rec.get("recorded_at", "N/A"))
                    usd_diff = float(get_config("USDKRW_DIFF", "0.00"))
                    usd_pct = float(get_config("USDKRW_PCT", "0.00"))
                    delta_fx = f"{usd_diff:+.2f}원 ({usd_pct:+.2f}%)"
                    fx_time = get_config("USDKRW_UPDATE_TIME", "N/A")
                    col1, col2, col3, col4 = st.columns([1.5, 1.5, 1, 2])
                    col1.metric(label=f"현재가 ({format_ticker_display(symbol, market_code)})", value=f"{currency_symbol}{format_currency(price, market_code)}", delta=delta_val)
                    col2.metric(label="환율 (정규장 개장 09:30 ET 기준)", value=f"₩{usd_krw:,.2f}", delta=delta_fx)
                    with col2:
                        st.caption(f"기준: 전일 개장 대비 | {fx_time}")
                        if st.button("🔄 지금 환율 조회", key="manual_fx_update", help="메리츠 실시간 적용환율을 즉시 조회하여 화면 및 시스템에 갱신합니다."):
                            with st.spinner("실시간 환율 조회 중..."):
                                live_info = ActiveBroker.get_exchange_rate(force=True)
                                cur_rate = float(live_info.get("rate", 0.0))
                                cur_diff = float(live_info.get("diff", 0.0))
                                cur_pct = float(live_info.get("pct", 0.0))
                                now_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                if cur_rate > 0:
                                    set_config("USDKRW", f"{cur_rate:.2f}")
                                    set_config("USDKRW_DIFF", f"{cur_diff:+.2f}")
                                    set_config("USDKRW_PCT", f"{cur_pct:+.2f}")
                                    set_config("USDKRW_UPDATE_TIME", now_time_str)
                                st.session_state["manual_live_fx"] = {
                                    "rate": cur_rate,
                                    "diff": cur_diff,
                                    "pct": cur_pct,
                                    "time": live_info.get("time", datetime.now().strftime("%H:%M:%S")),
                                    "source": live_info.get("source", "MERITZ")
                                }
                            st.rerun()
                    col3.write("") # 간격
                    col4.caption(f"⏱️ [{market_code}] 실시간 자동 갱신 중 (10초) | {datetime.now().strftime('%H:%M:%S')}")
                    
                    if "manual_live_fx" in st.session_state and st.session_state["manual_live_fx"].get("rate", 0) > 0:
                        lfx = st.session_state["manual_live_fx"]
                        st.info(f"🔍 **실시간 환율**: 1$ = **₩{lfx['rate']:,.2f}** ({lfx.get('diff', 0):+.2f}원, {lfx.get('pct', 0):+.2f}%) (기준 시각: {lfx['time']}, 출처: {lfx['source']})")

                    # [신규] 환율 변동 추이 그래프 (Expander)
                    render_exchange_rate_expander(market_code="US", key_suffix="live_header")
                else:
                    col1, col2, col3 = st.columns([1, 1, 2])
                    col1.metric(label=f"현재가 ({format_ticker_display(symbol, market_code)})", value=f"{currency_symbol}{format_currency(price, market_code)}", delta=delta_val)
                    col2.write("") 
                    col3.caption(f"⏱️ [{market_code}] 실시간 자동 갱신 중 (10초) | {datetime.now().strftime('%H:%M:%S')}")
                st.divider()
        except Exception as e:
            st.error(f"[{market_code}] 시세 갱신 오류: {e}")

if mode == "실전 투자":
    display_realtime_header()


if mode == "실전 투자":
    # === 실전 투자 화면 ===
    
    # 1. 계좌 조회 버튼 및 결과
    col_act, col_msg = st.columns([1, 2])
    with col_act:
        if st.button("🔄 현재 계좌 상태 조회 (갱신)", width='stretch', type="primary"):
            with st.spinner(f"[{market_code}] 메리츠 API 조회 중..."):
                if isinstance(symbol, str) and "(" in symbol:
                    symbol = symbol.split('(')[0].strip()
                broker = ActiveBroker
                
                # 정보 조회
                pool = broker.get_cash_pool()
                equity_res = broker.get_account_equity(symbol)
                if equity_res is None:
                    st.error("잔고 조회 실패 (API 응답 에러)")
                    st.stop()
                shares, avg_price, eval_amt = equity_res
                current_price = broker.get_price(symbol)
                prev_close = broker.get_previous_close(symbol)
                
                # DB 상태 동기화: 사이드바 요약 및 전략 로직 일관성을 위해 DB 업데이트
                state_data = load_state_db(symbol, strategy_choice, market=market_code, strategy_name=strategy_alias)
                if state_data:
                    if strategy_choice == "CA":
                        state_obj = CAState(**state_data)
                        state_obj.avg_price = avg_price
                        state_obj.total_shares = shares
                        # T값 재계산 (현재 누적액 기준, 기준분할매수금 분모 사용)
                        a_def = float(getattr(state_obj, 'a_default', 40) or 40)
                        c_budget = float(getattr(state_obj, 'cycle_budget', 0.0) or 0.0)
                        base_unit_buy = (c_budget / a_def) if (c_budget > 0 and a_def > 0) else float(state_obj.unit_buy_amount or 0)
                        if base_unit_buy > 0:
                            invested = avg_price * shares
                            state_obj.current_turn = math.ceil((invested / base_unit_buy) * 10) / 10.0
                        save_state_db(state_obj, market=market_code, strategy_name=strategy_alias) # strategy_name도 함께 저장
                    elif strategy_choice == "VR":
                        import dataclasses
                        db_avg_price = state_data.get('avg_price', 0.0)
                        if db_avg_price > 0.0:
                            valid_keys = {f.name for f in dataclasses.fields(VRState)}
                            filtered_data = {k: v for k, v in state_data.items() if k in valid_keys}
                            state_obj = VRState(**filtered_data)
                            state_obj.total_shares = shares
                            state_obj.avg_price = avg_price
                            save_state_db(state_obj, market=market_code, strategy_name=strategy_alias)

                # 세션 상태에 저장 (화면 리프레시 대응)
                st.session_state['live_account'] = {
                    'pool': state_data.get('pool', pool) if state_data else pool,
                    'broker_cash': pool,
                    'shares': shares,
                    'avg_price': avg_price,
                    'eval_amt': eval_amt,
                    'current_price': current_price,
                    'prev_close': prev_close,
                    'symbol': symbol,
                    'market_code': market_code,
                    'time': time.strftime("%H:%M:%S")
                }

                # [개선] 거래 내역 동기화 쿨다운 적용 (60초)
                last_sync_key = f"last_sync_{market_code}_{symbol}"
                now_ts = time.time()
                sync_period = 7 # 기본 동기화 범위를 7일로 확대
                if now_ts - st.session_state.get(last_sync_key, 0) > 60:
                    from core.database import sync_trade_history_db
                    start_date_sync = (datetime.now() - timedelta(days=sync_period)).strftime("%Y%m%d")
                    end_date_sync = datetime.now().strftime("%Y%m%d")
                    logger.info(f"🔍 [Dash] {symbol} {market_code} 체결 내역 동기화 시도 ({sync_period}일)...")
                    execs = broker.fetch_execution_history(symbol, start_date_sync, end_date_sync)
                    sync_trade_history_db(symbol, execs, strategy=strategy_choice, market=market_code, strategy_name=strategy_alias)
                    st.session_state[last_sync_key] = now_ts
                else:
                    st.caption("ℹ️ 최근 1분 이내에 동기화를 완료했습니다. (로그 생략)")
                
                st.rerun()

        # [요청 반영] 과거 1주일 강제 동기화 버튼
        if st.button("📅 과거 1주일 내역 강제 동기화", width='stretch', help="쿨다운을 무시하고 최근 7일간의 모든 체결 내역을 다시 불러옵니다."):
            with st.spinner(f"[{market_code}] 과거 1주일 내역 조회 중..."):
                broker = ActiveBroker
                from core.database import sync_trade_history_db
                start_date_sync = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
                end_date_sync = datetime.now().strftime("%Y%m%d")
                
                logger.info(f"🔍 [DeepSync] {symbol} {market_code} 1주일 체결 내역 강제 동기화 시작...")
                execs = broker.fetch_execution_history(symbol, start_date_sync, end_date_sync)
                
                logger.info(f"📥 [DeepSync] API로부터 {len(execs)}건의 데이터를 수신했습니다.")
                
                sync_trade_history_db(symbol, execs, strategy=strategy_choice, market=market_code, strategy_name=strategy_alias)
                
                # 강제동기화 완료 후에도 세션을 새로고침한다.
                pool = broker.get_cash_pool()
                equity_res = broker.get_account_equity(symbol)
                if equity_res is None:
                    st.error("잔고 조회 실패 (API 응답 에러)")
                    st.stop()
                shares, avg_price, eval_amt = equity_res
                current_price = broker.get_price(symbol)
                prev_close = broker.get_previous_close(symbol)
                
                st.session_state['live_account'] = {
                    'pool': pool,
                    'broker_cash': pool,
                    'shares': shares,
                    'avg_price': avg_price,
                    'eval_amt': eval_amt,
                    'current_price': current_price,
                    'prev_close': prev_close,
                    'symbol': symbol,
                    'market_code': market_code,
                    'time': time.strftime("%H:%M:%S")
                }
                st.success(f"✅ 최근 1주일 내역 동기화가 완료되었습니다. 하단 시스템 로그를 확인하세요.")
                time.sleep(1)
                st.rerun()
    
    # --- [수정] 보유 종목 현황 실시간 업데이트를 위한 프래그먼트 호출 ---
    display_holdings_metrics_live(symbol, strategy_choice, market_code, strategy_alias, currency_symbol, ActiveBroker)

    # === [신규] 주문 내역 실시간 동기화 (Sync with Meritz) ===
    is_active, _ = check_market_active(market_code)
    if is_active:
        last_order_sync_key = f"last_order_sync_{market_code}_{symbol}"
        now_ts = time.time()
        if now_ts - st.session_state.get(last_order_sync_key, 0) > 60:
            try:
                logger.info(f"🔄 [Dash] {symbol} 주문 내역 동기화 시작...")
                broker = ActiveBroker
                open_orders = broker.fetch_open_orders(symbol)
                logger.debug(f"Meritz API raw open orders response for {symbol}: {open_orders}")
                # DB와 메리츠 서버 실시간 동기화
                sync_open_orders_db(symbol, open_orders)
                st.session_state[last_order_sync_key] = now_ts
                logger.info(f"✅ [Dash] {symbol} 주문 내역 동기화 완료")
                
                # 만약 DB에는 없는데 메리츠에는 있는 주문이 있다면 (수동 주문 등), 
                # 필요시 여기서 log_order_db를 호출하여 추가할 수도 있습니다.
            except Exception as e:
                logger.error(f"주문 내역 동기화 실패: {e}")

    # === [신규] 주문 계획 확인 및 실행 영역 ===
    if st.session_state.planned_orders:
        st.divider()
        st.subheader("📋 주문 계획 확인 및 수정 (Pending Orders)")
        st.info("아래 테이블에서 **가격/수량을 수정**하거나 **체크박스로 실행할 주문을 선택**하세요.")
        
        # DataFrame 변환 및 표시
        df_plan = pd.DataFrame(st.session_state.planned_orders)
        
        if not df_plan.empty:
            # 'selected' 컬럼 추가 (기본값 True)
            if "selected" not in df_plan.columns:
                df_plan.insert(0, "selected", False) # [수정] 기본값 False로 변경

            # 표시할 컬럼 순서 정의
            cols_order = ["selected", "symbol", "strategy", "side", "qty", "price", "type", "desc"]
            
            # [수정] 시장별로 주문 유형 옵션을 다르게 제공
            # ORDER_TYPE_MAP을 직접 사용
            df_plan["type_display"] = df_plan["type"].map(lambda x: ORDER_TYPE_MAP.get(x, x))
            
            # 주문 제출 시 원래 코드로 역변환하기 위한 맵
            reverse_type_map = {v: k for k, v in ORDER_TYPE_MAP.items()}

            # Data Editor로 표시 (수정 가능)
            edited_df = st.data_editor(
                df_plan[["selected", "symbol", "strategy", "side", "qty", "price", "type", "type_display", "desc"]],
                column_config={
                    "selected": st.column_config.CheckboxColumn("실행", default=True),
                    "symbol": None, # 데이터는 유지하되 화면에서는 숨김
                    "type": None,   # 주문 제출에 필요한 원본 코드는 숨김
                    "price": st.column_config.NumberColumn(
                        f"가격 ({currency_symbol})",
                        min_value=0.0, 
                        format="₩%d" if market_code == "KR" else "$%.4f",
                        help="CAP 조건: 평단가 또는 현재가+15% 중 작은 가격으로 자동 계산됩니다."
                    ),
                    "qty": st.column_config.NumberColumn("수량", min_value=1, step=1), # type: ignore
                    "strategy": st.column_config.TextColumn("전략", disabled=True),
                    "side": st.column_config.TextColumn("구분", disabled=True),
                    "type_display": st.column_config.SelectboxColumn( # [수정] 유형 수정 가능하도록 변경
                        "유형", 
                        options=list(ORDER_TYPE_MAP.values()), # 시장별 옵션 사용
                        required=True
                    ),
                    "desc": st.column_config.TextColumn("설명", disabled=True),
                },
                hide_index=True,
                width='stretch',
                key="plan_editor"
            )
            
            # [수정] 주문 실행 및 취소 버튼을 나란히 배치하도록 변경
            col_p_btn1, col_p_btn2 = st.columns(2)
            
            if col_p_btn1.button("🚀 선택된 주문 실행 (Confirm)", type="primary", width='stretch'):
                with st.spinner("주문을 전송하고 있습니다..."):
                    # 선택된 행만 필터링
                    orders_to_run = edited_df[edited_df["selected"] == True]
                    
                    if orders_to_run.empty:
                        st.warning("선택된 주문이 없습니다.")
                    else:
                        try:
                            broker = ActiveBroker  # ActiveBroker는 이미 인스턴스입니다.
                            success_count = 0
                            
                            for _, row in orders_to_run.iterrows():
                                # Broker 인스턴스를 통해 직접 주문 전송 (수정된 값 반영)
                                submitted_price_type = reverse_type_map.get(row['type'], row['type'])
                                broker.place_order( # type: ignore
                                    symbol=row['symbol'], 
                                    price=float(row['price']), 
                                    qty=int(row['qty']), 
                                    order_type=row['side'],
                                    price_type=submitted_price_type,
                                    strategy=row['strategy'] # 현재 활성화된 전략(CA/VR)을 따르도록 수정
                                )
                                success_count += 1
                                time.sleep(0.2) # API Rate Limit
                                
                            st.success(f"총 {success_count}건의 주문 요청이 완료되었습니다. (로그 확인)")
                            # 계획 초기화 및 리로드
                            st.session_state.planned_orders = []
                            time.sleep(2)
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"주문 실행 중 오류 발생: {e}")
            
            if col_p_btn2.button("✖️ 주문 계획 취소 (Cancel)", width='stretch'):
                st.session_state.planned_orders = []
                st.info("📝 생성된 주문 계획이 삭제되었습니다.")
                st.rerun()
        else:
            st.write("주문 계획 데이터가 비어있습니다.")

    # === 매매 실행 상세 (CA 전략 전용) ===
    if strategy_choice == "CA":
        st.divider()
        st.subheader(f"📈 실전 매매 운영: {format_ticker_display(symbol, market_code)} (CA)")
        
        # 1. DB에서 상태 로드 시도
        state_data = load_state_db(symbol, "CA", market=market_code, strategy_name=strategy_alias)
        
        if state_data:
            # === 진행 중인 전략이 있는 경우 ===
            try:
                
                # 계산을 위한 변수 추출
                avg_price = state_data.get('avg_price', 0.0)
                current_t = state_data.get('current_turn', 0.0)
                unit_buy = state_data.get('unit_buy_amount', 0.0)
                total_shares = state_data.get('total_shares', 0.0)
                
                # [중요] 사이드바의 임시 값이 아닌 DB에 저장된 확정 파라미터 사용
                db_target_profit = state_data.get('target_profit_pct', target_profit)
                db_a_default = state_data.get('a_default', a_default)
                # Pool 잔고도 DB 상태 활용
                db_pool = state_data.get('pool', 0.0)

                # [Live Data Overlay] 실시간 계좌 정보가 있다면 화면 표시용 변수를 최신화
                # (DB 상태가 아직 업데이트되지 않았거나 초기화 상태일 경우를 대비)
                if 'live_account' in st.session_state and st.session_state['live_account'].get('symbol') == symbol:
                    live_info = st.session_state['live_account']
                    live_shares_val = live_info.get('shares', 0.0)
                    if live_shares_val > 0:
                        # 평단과 수량을 실시간 데이터로 대체하여 표시
                        avg_price = live_info.get('avg_price', 0.0)
                        total_shares = live_shares_val
                        
                        # T값이 0이거나 실제 잔고와 차이가 클 경우 재추정하여 표시 (기준분할매수금 분모 사용)
                        a_def = float(state_data.get('a_default', db_a_default) or db_a_default or 40)
                        c_budget = float(state_data.get('cycle_budget', 0.0) or 0.0)
                        base_unit_buy = (c_budget / a_def) if (c_budget > 0 and a_def > 0) else unit_buy
                        if base_unit_buy > 0:
                            invested_amt = avg_price * total_shares
                            est_t = math.ceil((invested_amt / base_unit_buy) * 10) / 10.0
                            if current_t == 0 or abs(current_t - est_t) > 0.5:
                                current_t = est_t
                
                # Star% 계산 (CostAveragingEngine 로직 재사용 또는 직접 계산)
                # Star% = Target - (T/2 * (T_def/a_def))/100
                # 여기서는 Config 값을 알 수 없으므로 사이드바 입력을 사용
                # (주의: 사이드바 입력과 실제 실행 설정이 다를 수 있음)
                
                star_pct = db_target_profit * (1.0 - (current_t / 20.0) * (40.0 / db_a_default))
                star_pct = round(star_pct, 9)
                star_pct = math.ceil(star_pct * 10000) / 10000.0
                cur_sym = currency_symbol
                
                st.write(f"현재 T: **{current_t:.1f}** | Star%: **{star_pct*100:.2f}%** | 1회 매수금: **{cur_sym}{format_currency(unit_buy, market_code)}**")

                c1, c2 = st.columns(2)
                
                # 1. 매수 조건표
                with c1:
                    st.markdown(f"##### ✅ 매수 조건표 (0.5T 씩)")
                    buy_rows = []
                    
                    # 한국 시장은 LOC 모사 주문으로 표시
                    buy_label_1 = "LOC 모사 평단" if market_code == "KR" else "LOC 평단"
                    buy_label_2 = "LOC 모사 Star%" if market_code == "KR" else "LOC Star%"

                    # LOC 평단 매수
                    if avg_price > 0:
                        qty_avg = int((unit_buy * 0.5) / avg_price)
                        # [개선] 예산 범위 내에서 최소 1주 보장 표시
                        if qty_avg <= 0 and unit_buy > 0 and db_pool >= avg_price:
                            qty_avg = 1 # 최소 1주 매수
                        buy_rows.append({"구분": buy_label_1, f"가격 ({cur_sym})": format_currency(avg_price, market_code), "수량 (주)": qty_avg})
                    
                    # LOC Star% 매수 (자전거래 방지 상한선 max_buy_allowed 적용)
                    if avg_price > 0:
                        loc_offset = -10 if market_code == "KR" else -0.01
                        loc_sell_ref = ActiveBroker.adjust_price_by_tick(symbol, avg_price * (1 + star_pct), "SELL")
                        max_buy_allowed = ActiveBroker.adjust_price_by_tick(symbol, loc_sell_ref + loc_offset, "BUY")
                        price_star_raw = (avg_price * (1 + star_pct)) + loc_offset
                        star_buy_price = ActiveBroker.adjust_price_by_tick(symbol, price_star_raw, "BUY")
                        price_star = min(star_buy_price, max_buy_allowed)
                        if price_star > 0:
                            qty_star = int((unit_buy * 0.5) / price_star)
                            if qty_star <= 0 and unit_buy > 0 and db_pool >= price_star:
                                qty_star = 1
                            buy_rows.append({"구분": buy_label_2, f"가격 ({cur_sym})": format_currency(price_star, market_code), "수량 (주)": qty_star})
                    
                    st.table(pd.DataFrame(buy_rows))

                # 2. 매도 조건표
                with c2:
                    st.markdown("##### ⛔ 매도 조건표")
                    sell_rows = []
                    
                    # 한국 시장은 LOC 모사 주문으로 표시
                    sell_label_1 = "LOC 모사 Star% (25%)" if market_code == "KR" else "LOC Star% (25%)"

                    if total_shares > 0:
                        # [수정] 수량 분할 로직: 25% 버림 후 나머지 75% 할당
                        qty_sell_25 = int(total_shares * 0.25)
                        qty_sell_75 = total_shares - qty_sell_25

                        # Star% 매도 (호가 보정)
                        price_sell_loc = ActiveBroker.adjust_price_by_tick(symbol, avg_price * (1 + star_pct), "SELL")
                        sell_rows.append({"구분": sell_label_1, f"가격 ({cur_sym})": format_currency(price_sell_loc, market_code), "수량 (주)": qty_sell_25})
                        
                        # 지정가 목표수익률 매도 (호가 보정)
                        price_sell_limit = ActiveBroker.adjust_price_by_tick(symbol, avg_price * (1 + db_target_profit), "SELL")
                        sell_rows.append({"구분": f"지정가 {db_target_profit*100:.0f}% (75%)", f"가격 ({cur_sym})": format_currency(price_sell_limit, market_code), "수량 (주)": int(qty_sell_75)})
                        
                    st.table(pd.DataFrame(sell_rows))

                # === 주문 내역 조회 (Order History) ===
                st.markdown("##### 📑 주문 내역 조회 (Submitted Orders)")
                cols_ord, rows_ord = get_order_history_db(symbol)
                if rows_ord:
                    df_orders = pd.DataFrame(rows_ord, columns=cols_ord)
                    # 주문유형 코드 변환 및 컬럼명 변경
                    df_orders['주문유형'] = df_orders['type'].map(lambda x: ORDER_TYPE_MAP.get(x, x))
                    # 가격 컬럼을 소수점 4자리 문자열로 변환하여 확인 가능하게 함
                    if market_code == "KR":
                        df_orders['가격'] = df_orders['price'].map(lambda x: f"{int(safe_float(x)):,}")
                    else:
                        df_orders['가격'] = df_orders['price'].map(lambda x: f"{safe_float(x):.4f}")
                    df_orders = df_orders.rename(columns={'strategy_name': '별칭'}) # Rename strategy_name to 별칭
                    disp_cols = ['timestamp', 'symbol', '별칭', 'side', '가격', 'qty', '주문유형', 'status', 'odno']
                    df_orders = df_orders[disp_cols].rename(columns={'timestamp': '시간', 'symbol': 'Ticker', 'side': '구분', 'qty': '수량'})
                    # [KR] Ticker 표시 포맷팅
                    df_orders['Ticker'] = df_orders['Ticker'].apply(lambda x: format_ticker_display(x, market_code))
                    st.dataframe(df_orders, width='stretch')
                else:
                    st.caption("최근 제출된 주문 내역이 없습니다.")

                # --- [ADD] 전략 필터 정의 (이익 요약 및 거래 내역 공용) ---
                hist_filter_ca = st.selectbox("전략 필터", ["전체", "CA", "VR"], index=1, key=f"hist_filter_ca_{symbol}")
                target_strat_ca = None if hist_filter_ca == "전체" else hist_filter_ca

                # --- [ADD] 실현 손익 요약 및 별칭별 합계 (CA) ---
                st.markdown("##### 💰 실현 손익 현황 (Realized Profit)")
                logger.debug(f"[Debug] Trade History Query: Symbol={symbol}, Strategy={target_strat_ca}, Market={market_code}")
                cols, rows = get_detailed_trade_history_db(symbol, strategy=target_strat_ca, market=market_code)
                if rows:
                    df_all = pd.DataFrame(rows, columns=cols)
                    df_sells = df_all[df_all['side'] == 'SELL'].copy()
                    
                    if not df_sells.empty:
                        # [요청 반영] 별칭별 실현손익 합계 요약 (정렬 및 상세 지표 추가)
                        st.markdown("###### 💹 별칭별 실현손익 합계 (차수 역순 정렬)")
                        
                        alias_summary = []
                        # df_all을 사용하여 매수/매도 합계를 구함
                        for name, group in df_all.groupby('strategy_name'):
                            buys = group[group['side'] == 'BUY']['total_amount'].sum()
                            sells = group[group['side'] == 'SELL']['total_amount'].sum()
                            realized = group[group['side'] == 'SELL']['realized_profit'].sum()
                            rate = (realized / buys * 100) if buys > 0 else 0
                            
                            # 차수 추출 (정렬용: '이름_3차' -> 3)
                            m = re.search(r'(\d+)차', str(name))
                            turn_num = int(m.group(1)) if m else 0
                            
                            alias_summary.append({
                                '전략 별칭': name,
                                '총 매수액': buys,
                                '총 매도액': sells,
                                f'실현손익 ({currency_symbol})': realized,
                                '이익률(%)': rate,
                                '_turn_num': turn_num
                            })
                        
                        summary_df = pd.DataFrame(alias_summary)
                        if not summary_df.empty:
                            summary_df = summary_df.sort_values('_turn_num', ascending=False).drop('_turn_num', axis=1)
                            st.dataframe(summary_df.style.format({
                                '총 매수액': lambda x: format_currency(x, market_code),
                                '총 매도액': lambda x: format_currency(x, market_code),
                                f'실현손익 ({currency_symbol})': lambda x: format_currency(x, market_code),
                                '이익률(%)': '{:+.2f}%'
                            }), width='stretch', hide_index=True)

                        st.markdown("###### 📝 세부 매도 내역 (최신 시간순)")
                        # 사용자 요청 컬럼명으로 변환 및 포맷팅
                        df_sells['Ticker'] = df_sells['symbol'].apply(lambda x: format_ticker_display(x, market_code))
                        df_sells = df_sells.rename(columns={
                            'date': '매도시간', 'strategy_name': '전략 별칭', 'price': '매도단가', 
                            'qty': '매도수량', 'fee': '수수료', 'total_amount': '매도금액', 
                            'avg_price': '평단가', 'realized_profit': '이익', 'realized_profit_rate': '이익률(%)'
                        })
                        
                        disp_sell_cols = ['매도시간', '전략 별칭', 'Ticker', '매도단가', '매도수량', '수수료', '매도금액', '평단가', '이익', '이익률(%)']
                        st.dataframe(df_sells[disp_sell_cols].sort_values('매도시간', ascending=False), width='stretch')
                    else:
                        st.caption("최근 실현된 매도 수익 내역이 없습니다.")
                        
                # 3. 거래 내역표
                st.markdown("##### 📜 거래 내역 (Detailed Trade History)")

                col_sync_btn, col_sync_info = st.columns([1, 2])
                with col_sync_btn:
                    if st.button("🔄 실시간 계좌 거래내역 동기화", key=f"sync_trade_btn_ca_{symbol}", help="증권사 API로부터 최근 체결 내역 및 잔고를 가져와 DB와 동기화합니다."):
                        with st.spinner(f"[{market_code}] 증권사 API 체결 내역 및 잔고 동기화 중..."):
                            broker = ActiveBroker
                            start_date_sync = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
                            end_date_sync = datetime.now().strftime("%Y%m%d")
                            execs = broker.fetch_execution_history(symbol, start_date_sync, end_date_sync)
                            sync_trade_history_db(symbol, execs, strategy="CA", market=market_code, strategy_name=strategy_alias)
                            
                            # 잔고 및 예수금 동기화
                            pool = broker.get_cash_pool()
                            equity_res = broker.get_account_equity(symbol)
                            if equity_res is not None:
                                shares_live, avg_price_live, eval_amt_live = equity_res
                                current_price_live = broker.get_price(symbol)
                                prev_close_live = broker.get_previous_close(symbol)
                                st.session_state['live_account'] = {
                                    'pool': pool,
                                    'broker_cash': pool,
                                    'shares': shares_live,
                                    'avg_price': avg_price_live,
                                    'eval_amt': eval_amt_live,
                                    'current_price': current_price_live,
                                    'prev_close': prev_close_live,
                                    'symbol': symbol,
                                    'market_code': market_code,
                                    'time': time.strftime("%H:%M:%S")
                                }
                            st.success("✅ 거래 내역 및 계좌 잔고가 증권사 API와 동기화되었습니다.")
                            time.sleep(1)
                            st.rerun()
                with col_sync_info:
                    st.caption("💡 증권사 API와 DB 간 체결 내역/잔고 차이가 있을 때 동기화 버튼을 누르세요.")
                
                # 위에서 가져온 rows를 재사용하여 상세 내역 표시
                if rows:
                    df_log = pd.DataFrame(rows, columns=cols)
                    # 시장 및 별칭 컬럼 가시성 확보를 위해 컬럼명 변경
                    df_log = df_log.rename(columns={'market': '시장', 'strategy_name': '별칭'})
                    # [KR] 종목 표시 포맷팅
                    df_log['symbol'] = df_log['symbol'].apply(lambda x: format_ticker_display(x, market_code))
                    
                    # 별칭(Alias) 필터링 기능 추가
                    unique_aliases = sorted([str(a) if a else "N/A" for a in df_log['별칭'].unique()])
                    selected_aliases = st.multiselect("별칭 필터 (Alias Filter)", options=unique_aliases, default=unique_aliases, key=f"alias_filter_ca_{symbol}")
                    df_log = df_log[df_log['별칭'].fillna("N/A").astype(str).isin(selected_aliases)]

                    st.dataframe(df_log, width='stretch')
                else:
                    st.info(f"💡 '{symbol}' ({strategy_alias})의 {market_code} 거래 내역이 DB에 없습니다.")
                    st.write("상단의 **'🔄 현재 계좌 상태 조회 (갱신)'** 버튼을 눌러 최근 5일간의 체결 내역을 동기화해보세요.")
                    if st.button("🔍 DB 전체 검색 (필터 없이)", key=f"raw_search_{symbol}"):
                        _, raw_rows = get_detailed_trade_history_db(None)
                        if raw_rows:
                            st.write("DB에 존재하는 전체 거래 내역 (디버깅용):")
                            st.dataframe(pd.DataFrame(raw_rows), width='stretch')
                        else:
                            st.error("DB의 trade_history 테이블이 완전히 비어 있습니다.")

            except Exception as e:
                st.error(f"전략 데이터 처리 중 오류: {e}")
                
        else:
            # === 신규 진입 또는 재시작 (상태 데이터 없음) ===
            st.warning(f"'{symbol}'에 대한 진행 중인 CA 전략이 없습니다.")
            
            if 'live_account' in st.session_state and st.session_state['live_account'].get('symbol') == symbol:
                # 계좌 정보 기반 T값 역산 및 초기화 제안
                info = st.session_state['live_account']
                current_shares = info.get('shares', 0.0)
                current_avg_price = info.get('avg_price', 0.0)
                
                # 사용자 입력값(사이드바) 가져오기
                input_unit_buy = unit_buy
                if input_unit_buy <= 0 and a_default > 0:
                     # unit_buy가 0이면 초기자본/분할수로 계산해야 하나, 초기자본을 명확히 알 수 없으므로
                     # 여기서는 사이드바 입력을 필수로 하거나, 추정해야 함.
                     # 편의상 입력값이 있어야 정확하다고 안내.
                     st.error("정확한 T값 계산을 위해 사이드바에서 '1회 매수 금액'을 설정해주세요.")
                
                elif input_unit_buy > 0:
                    invested_amount = current_shares * current_avg_price
                    estimated_t = 0.0
                    if invested_amount > 0:
                        raw_t = invested_amount / input_unit_buy
                        estimated_t = math.ceil(raw_t * 10) / 10.0
                    
                    st.info(f"현재 잔고를 바탕으로 **회차(T)**를 추정했습니다.")
                    
                    col_init1, col_init2 = st.columns(2)
                    with col_init1:
                        st.markdown(f"""
                        **현재 상황**
                        - 보유 수량: {current_shares} 주
                        - 평단가: {currency_symbol}{format_currency(current_avg_price, market_code)}
                        - 총 매수금액: {currency_symbol}{format_currency(invested_amount, market_code)}
                        """)
                    with col_init2:
                        st.markdown(f"""
                        **설정 및 추정**
                        - 1회 매수금: {currency_symbol}{format_currency(input_unit_buy, market_code)}
                        - **추정 회차 (T): {estimated_t:.1f}**
                        """)
                    
                    st.markdown("위 내용으로 실전 투자를 시작하시겠습니까?")
                    
                    if st.button("✅ 네, 이 상태로 실전 투자 시작 (DB 저장)", type="primary"):
                        # 초기 상태 생성 및 DB 저장
                        from core.cavr import CAState
                        new_state = CAState(
                            symbol=symbol,
                            strategy_type="CA",
                            strategy_name=strategy_alias,
                            market=market_code,
                            avg_price=current_avg_price,
                            total_shares=current_shares,
                            pool=info['pool'], # [추가] 초기 예수금 저장
                            current_turn=estimated_t,
                            cycle_budget=initial_cash, # 사이드바 초기자본 값 사용 (참고용)
                            total_profit=0.0,
                            unit_buy_amount=input_unit_buy,
                            daily_bought_amount=0.0,
                            last_intraday_level=0,
                            last_check_date="",
                            mode="NORMAL"
                        )
                        save_state_db(new_state, market=market_code, strategy_name=strategy_alias)
                        st.success(f"**{symbol}** 전략 초기화 완료! 화면을 갱신합니다.")
                        time.sleep(1)
                        st.rerun()
            else:
                st.info("먼저 상단의 '🔄 현재 계좌 상태 조회' 버튼을 눌러 잔고 정보를 가져오세요.")

    # === 매매 실행 상세 (VR 전략 전용) ===
    elif strategy_choice == "VR":
        st.divider()
        st.subheader(f"📈 실전 매매 운영: {format_ticker_display(symbol, market_code)} (VR)")
        
        state_data = load_state_db(symbol, "VR", market=market_code, strategy_name=strategy_alias)
        
        if state_data:
            try:
                # 상태 변수 추출
                initial_budget_val = state_data.get('initial_budget', 0.0)
                current_v = state_data.get('cycle_V', 0.0) # 이번 사이클 목표 V
                last_pool = state_data.get('pool', 0.0)    # 직전 Pool
                if current_v == 0.0 and initial_budget_val > 0:
                    current_v = initial_budget_val
                if last_pool == 0.0 and initial_budget_val > 0:
                    last_pool = initial_budget_val
                current_shares = state_data.get('total_shares', 0.0)
                # VRState에는 shares가 없고 Pool과 V만 관리됨. Shares는 실시간 잔고로 파악해야 함.
                
                # Live 정보가 있으면 그것을 우선 사용
                db_shares = state_data.get('total_shares', 0.0)
                if 'live_account' in st.session_state and st.session_state['live_account'].get('symbol') == symbol:
                    live_shares = st.session_state['live_account'].get('shares', db_shares)
                    live_pool = last_pool
                    current_price = st.session_state['live_account'].get('current_price', 0.0)
                else:
                    live_shares = db_shares
                    live_pool = last_pool
                    current_price = 0.0

                # 밴드 계산 (사이드바 설정값 사용 - 주의: DB에 저장된 설정이 아님)
                # 실제로는 Config도 DB에 저장하거나 해야 하지만, 여기선 사이드바 값 사용
                low_band = current_v * (1 - (vr_band_pct / 100.0))
                high_band = current_v * (1 + (vr_band_pct / 100.0))
                
                # 현재 평가금 (E) - [공식 수정] 공식문서(strategy_formula.md 105라인) 기준 E는 주식 평가액 단독입니다.
                current_eval = (live_shares * current_price)

                mode_val = state_data.get('mode', 'RUNNING')
                
                # 구버전 호환용 (bootstrap_days 필드가 없거나 0 인데 mode가 BOOTSTRAP 인 구버전 잔재 자가 치유)
                if mode_val == 'BOOTSTRAP' and state_data.get('bootstrap_days', 0) == 0:
                    from core.database import save_state_db
                    from core.cavr import VRState
                    import math
                    
                    state_data['mode'] = 'RUNNING'
                    G_val = state_data.get('G', 10.0)
                    if G_val <= 0: G_val = 10.0
                    E_val = state_data.get('total_shares', 0.0) * state_data.get('avg_price', 0.0)
                    init_pool = state_data.get('pool', initial_budget_val)
                    
                    new_V = (init_pool / G_val) + (E_val / (2.0 * math.sqrt(G_val)))
                    state_data['V'] = new_V
                    state_data['cycle_V'] = new_V
                    state_data['cycle_start_pool'] = init_pool
                    state_data['last_E'] = E_val
                    
                    recovered_state = VRState(**state_data)
                    save_state_db(recovered_state, market=market_code, strategy_name=strategy_alias)
                    st.toast("🔧 [Self-Healing] 구버전 BOOTSTRAP 전략이 RUNNING 모드로 자동 복구 및 즉시 전환되었습니다.")
                    time.sleep(1)
                    st.rerun()

                if mode_val == 'BOOTSTRAP':
                    # === 신버전 초기 빌드업 (Bootstrap) 전용 뷰 렌더링 ===
                    b_days = state_data.get('bootstrap_days', 10)
                    b_count = state_data.get('bootstrap_day_count', 0)
                    b_order_amt = state_data.get('bootstrap_order_amount', 0.0)
                    
                    st.info(f"⏳ **현재 초기 빌드업(Bootstrap) 단계 진행 중입니다.** ({b_count} / {b_days}일 완료)")
                    
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        st.markdown(f"""
                        **📊 빌드업 현황**
                        - 현재 상태: ⏳ **초기 빌드업 (Bootstrap)**
                        - 진행 카운트: **{b_count}일** / 총 **{b_days}일**
                        - 가용 예수금: **{currency_symbol}{format_currency(live_pool, market_code)}**
                        - 설정 자본금: **{currency_symbol}{format_currency(initial_budget_val, market_code)}**
                        """)
                    with col_b2:
                        qty_est = int(b_order_amt / current_price) if current_price > 0 else 0
                        st.markdown(f"""
                        **🛒 일일 시장가 매수 계획**
                        - 1일 목표 매수액: **{currency_symbol}{format_currency(b_order_amt, market_code)}**
                        - 예상 매수 가격: **{currency_symbol}{format_currency(current_price, market_code)}**
                        - 예상 매수 수량: **{qty_est}주** (장 시작 30분 후 시장가 제출)
                        """)
                        
                    pct_done = min(100.0, float(b_count) / float(b_days) * 100.0) if b_days > 0 else 100.0
                    st.progress(pct_done / 100.0, text=f"빌드업 진행률 {pct_done:.1f}%")
                    st.caption("※ 초기 빌드업 기간 동안에는 목표 V 및 실시간 평가금 E는 계산되지만, 밴드 리밸런싱 지정가 매수/매도 주문 대신 매일 정규장 개장 30분 후 시장가로 매수 주문이 자동으로 집행됩니다.")
                else:
                    col_vr1, col_vr2 = st.columns(2)
                    with col_vr1:
                        st.markdown(f"""
                        **현재 상태 (Running)**
                        - 목표 밸류 (V): **{currency_symbol}{format_currency(current_v, market_code)}**
                        - 현재 평가금 (E): **{currency_symbol}{format_currency(current_eval, market_code)}**
                        - 밴드 범위: ({vr_band_pct}%) ***{currency_symbol}{format_currency(low_band, market_code)} ~ {currency_symbol}{format_currency(high_band, market_code)}***
                        """)
                    with col_vr2:
                        # 밴드 위치 시각화
                        if current_v > 0:
                            pos_pct = (current_eval - current_v) / current_v * 100
                            st.metric("밴드 위치 (E vs V)", f"{pos_pct:+.2f}%", 
                                      delta="범위 벗어남" if abs(pos_pct) > vr_band_pct else "범위 안에 있음")
                
                # [ADD] VR 실력공식 구성 요소 시각화
                import math
                g_coeff = state_data.get('G', 10.0)
                if g_coeff <= 0: g_coeff = 10.0
                p_accum = state_data.get('periodic_accumulation', 0.0)
                
                # V1 기준값 산출: BOOTSTRAP 모드이거나 V1이 초기 원금 대비 비정상적으로 왜곡된 경우 초기 투자금으로 보정
                v1_base = current_v
                ib_val = state_data.get('initial_budget', 0.0)
                if ib_val > 0 and (mode_val == 'BOOTSTRAP' or v1_base <= 0 or v1_base < ib_val * 0.4):
                    v1_base = ib_val

                # 다음 사이클 예상 목표 V (V2) 계산 시뮬레이션
                term1_val = live_pool / g_coeff
                term2_val = (current_eval - v1_base) / (2.0 * math.sqrt(g_coeff))
                v2_val = v1_base + term1_val + term2_val + p_accum
                
                st.markdown("##### 🧮 VR 실력공식 구성 변수 (Skill Formula Components)")
                formula_df = {
                    "구분": [
                        "이전 사이클 목표 밸류 (V1)",
                        "현재 가용 예수금 (Pool)",
                        "기울기 계수 (G)",
                        "현재 주식 평가액 (E)",
                        "주기별 적립/인출금",
                        "계산된 다음 목표 밸류 (V2)"
                    ],
                    "변수명": ["V1", "Pool", "G", "E", "Contribution", "V2"],
                    "값 / 수치": [
                        f"{currency_symbol}{format_currency(v1_base, market_code)}",
                        f"{currency_symbol}{format_currency(live_pool, market_code)}",
                        f"{g_coeff:.0f}",
                        f"{currency_symbol}{format_currency(current_eval, market_code)}",
                        f"{currency_symbol}{format_currency(p_accum, market_code)}",
                        f"{currency_symbol}{format_currency(v2_val, market_code)}"
                    ],
                    "수식 기여분": [
                        "기준값",
                        f"+{currency_symbol}{format_currency(term1_val, market_code)}",
                        "수축/이완 조절",
                        f"{'+' if term2_val >= 0 else ''}{currency_symbol}{format_currency(term2_val, market_code)}",
                        f"+{currency_symbol}{format_currency(p_accum, market_code)}",
                        "다음 사이클 시작 시 갱신값"
                    ]
                }
                st.table(formula_df)
                
                if mode_val == 'BOOTSTRAP':
                    st.markdown("##### ⏳ 초기 분할매수모드 (Bootstrap) 상세 정보")
                    b_days = state_data.get('bootstrap_days', 10)
                    b_count = state_data.get('bootstrap_day_count', 0)
                    b_order_amt = state_data.get('bootstrap_order_amount', 0.0)
                    
                    bootstrap_info = {
                        "설정 항목": ["진행 상태", "총 목표 일수", "누적 진행 일수", "일일 매수 계획 금액", "가용 풀 사용 한도 (%)"],
                        "값 / 수치": [
                            "⏳ 진행 중 (BOOTSTRAP)",
                            f"{b_days}일",
                            f"{b_count}일",
                            f"{currency_symbol}{format_currency(b_order_amt, market_code)}",
                            f"{state_data.get('pool_limit_pct', 50.0):.1f}%"
                        ]
                    }
                    st.table(pd.DataFrame(bootstrap_info))
                
                if mode_val in ['RUNNING', 'BOOTSTRAP']:
                    st.divider()
                    st.markdown("##### 🛒 예약 주문 가이드 (Limit Orders)")
                    if mode_val == 'BOOTSTRAP':
                        b_days = state_data.get('bootstrap_days', 10)
                        b_count = state_data.get('bootstrap_day_count', 0)
                        b_order_amt = state_data.get('bootstrap_order_amount', 0.0)
                        qty_est = int(b_order_amt / current_price) if current_price > 0 else 0
                        
                        st.warning(
                            f"⏳ **초기 분할매수모드(Bootstrap) 진행 상황**: "
                            f"**{b_days}회 중 {b_count + 1}회차 매수 예정** (현재 {b_count}회 완료)  \n"
                            f"💰 **일일 매수 금액**: **{currency_symbol}{format_currency(b_order_amt, market_code)}** | "
                            f"📦 **예상 매수가능 수량**: **{qty_est}주** (현재가 {currency_symbol}{format_currency(current_price, market_code)} 기준)  \n"
                            f"⚠️ *Bootstrap 기간에는 매일 개장 30분 후에 시장가 주문이 자동으로 제출됩니다. 아래 지정가 예약은 참고용이며 자동 제출되지 않습니다.*"
                        )
                    # 당일 주문 제출 시점의 고정 기준값 사용 (장중 체결로 인한 실시간 변동 방지)
                    guide_v = state_data.get('cycle_V') or state_data.get('V') or current_v
                    guide_pool = state_data.get('cycle_start_pool') or state_data.get('pool') or live_pool
                    guide_shares = state_data.get('cycle_start_shares')
                    if guide_shares is None or guide_shares <= 0:
                        guide_shares = state_data.get('total_shares') or live_shares
                    guide_date = state_data.get('last_order_date') or state_data.get('last_v_update_date') or datetime.now().strftime('%Y-%m-%d')
                    
                    guide_low_band = guide_v * (1 - (vr_band_pct / 100.0))
                    guide_high_band = guide_v * (1 + (vr_band_pct / 100.0))

                    st.caption(
                        f"📌 **당일 발주 기준 상태** | "
                        f"목표 V: **{currency_symbol}{format_currency(guide_v, market_code)}** "
                        f"(Band: {currency_symbol}{format_currency(guide_low_band, market_code)} ~ {currency_symbol}{format_currency(guide_high_band, market_code)}) | "
                        f"기준 Pool: **{currency_symbol}{format_currency(guide_pool, market_code)}** | "
                        f"기준 수량: **{guide_shares:.0f}주** | "
                        f"산출 기준일: **{guide_date}**"
                    )

                    c1, c2 = st.columns(2)
                    
                    # 1. 매수 주문 (Low Band)
                    with c1:
                        st.markdown("**📉 매수 예약 (지정가)**")
                        buy_orders = []
                        pool_limit_ratio = state_data.get('pool_limit_pct')
                        if pool_limit_ratio is not None:
                            pool_limit_ratio = pool_limit_ratio / 100.0
                        else:
                            pool_limit_ratio = 0.5 # Default
                            if "적립" in vr_invest_type_disp: pool_limit_ratio = 0.75
                            elif "인출" in vr_invest_type_disp: pool_limit_ratio = 0.25
                        
                        max_use_pool = guide_pool * pool_limit_ratio
                        used_pool = 0.0
                        
                        target_val_buy = guide_low_band - guide_pool
                        if target_val_buy > 0:
                            for n in range(1, 6): # 5호가 정도만 보여줌
                                limit_price = target_val_buy / (guide_shares + n)
                                if limit_price > 0 and used_pool + limit_price <= max_use_pool:
                                    buy_orders.append({"구분": f"매수 {n}차", f"가격 ({currency_symbol})": format_currency(limit_price, market_code), "수량": "1주"})
                                    used_pool += limit_price
                            if buy_orders:
                                st.table(pd.DataFrame(buy_orders))
                            else:
                                st.info("사용 한도를 초과해 표시할 매수 주문이 없습니다.")
                        else:
                            st.info("현재 현금이 Low Band보다 많아 추가 매수가 불필요하거나 불가능합니다.")

                    # 2. 매도 주문 (High Band)
                    with c2:
                        st.markdown("**📈 매도 예약 (지정가)**")
                        sell_orders = []
                        target_val_sell = guide_high_band - guide_pool
                        
                        if target_val_sell > 0 and guide_shares > 0:
                            for n in range(0, min(5, int(guide_shares))):
                                if (guide_shares - n) > 0:
                                    limit_price = target_val_sell / (guide_shares - n)
                                    sell_orders.append({"구분": f"매도 {n+1}차", f"가격 ({currency_symbol})": format_currency(limit_price, market_code), "수량": "1주"})
                            if sell_orders:
                                st.table(pd.DataFrame(sell_orders))
                            else:
                                st.info("보유 수량이 부족합니다.")
                        elif target_val_sell <= 0:
                             st.warning("현재 현금이 이미 High Band를 초과했습니다. 즉시 리밸런싱(매도)이 필요할 수 있습니다.")
                        else:
                            st.info("보유 수량이 없습니다.")

                # === 주문 내역 조회 (Order History) ===
                st.divider()
                st.markdown("##### 📑 주문 내역 조회 (Submitted Orders)") # type: ignore
                cols_ord, rows_ord = get_order_history_db(symbol)
                if rows_ord:
                    df_orders = pd.DataFrame(rows_ord, columns=cols_ord)
                    df_orders['주문유형'] = df_orders['type'].map(lambda x: ORDER_TYPE_MAP.get(x, x))
                    # 가격 컬럼을 소수점 4자리 문자열로 변환하여 확인 가능하게 함
                    if market_code == "KR":
                        df_orders['가격'] = df_orders['price'].map(lambda x: f"{int(safe_float(x)):,}")
                    else:
                        df_orders['가격'] = df_orders['price'].map(lambda x: f"{safe_float(x):.4f}")
                    df_orders = df_orders.rename(columns={'strategy_name': '별칭'}) # Rename strategy_name to 별칭
                    disp_cols = ['timestamp', 'symbol', '별칭', 'side', '가격', 'qty', '주문유형', 'status', 'odno']
                    df_orders = df_orders[disp_cols].rename(columns={'timestamp': '시간', 'symbol': 'Ticker', 'side': '구분', 'qty': '수량'})
                    st.dataframe(df_orders, width='stretch')
                else:
                    st.caption("최근 제출된 주문 내역이 없습니다.")

                # --- [ADD] 전략 필터 정의 (VR) ---
                hist_filter_vr = st.selectbox("전략 필터", ["전체", "CA", "VR"], index=2, key=f"hist_filter_vr_{symbol}")
                target_strat_vr = None if hist_filter_vr == "전체" else hist_filter_vr

                # --- [ADD] 실현 손익 요약 및 별칭별 합계 (VR) ---
                st.markdown("##### 💰 실현 손익 현황 (Realized Profit)")
                logger.debug(f"[Debug] Trade History Query: Symbol={symbol}, Strategy={target_strat_vr}, Market={market_code}")
                cols, rows = get_detailed_trade_history_db(symbol, strategy=target_strat_vr, market=market_code)
                if rows:
                    df_all = pd.DataFrame(rows, columns=cols)
                    df_sells = df_all[df_all['side'] == 'SELL'].copy()
                    
                    if not df_sells.empty:
                        # [요청 반영] 별칭별 실현손익 합계 요약 (VR)
                        st.markdown("###### 💹 별칭별 실현손익 합계 (차수 역순 정렬)")
                        alias_summary_vr = []
                        for name, group in df_all.groupby('strategy_name'):
                            buys = group[group['side'] == 'BUY']['total_amount'].sum()
                            sells = group[group['side'] == 'SELL']['total_amount'].sum()
                            realized = group[group['side'] == 'SELL']['realized_profit'].sum()
                            rate = (realized / buys * 100) if buys > 0 else 0
                            
                            m = re.search(r'(\d+)차', str(name))
                            turn_num = int(m.group(1)) if m else 0
                            
                            alias_summary_vr.append({
                                '전략 별칭': name,
                                '총 매수액': buys,
                                '총 매도액': sells,
                                f'실현손익 ({currency_symbol})': realized,
                                '이익률(%)': rate,
                                '_turn_num': turn_num
                            })
                        
                        summary_df_vr = pd.DataFrame(alias_summary_vr)
                        if not summary_df_vr.empty:
                            summary_df_vr = summary_df_vr.sort_values('_turn_num', ascending=False).drop('_turn_num', axis=1)
                            st.dataframe(summary_df_vr.style.format({
                                '총 매수액': lambda x: format_currency(x, market_code),
                                '총 매도액': lambda x: format_currency(x, market_code),
                                f'실현손익 ({currency_symbol})': lambda x: format_currency(x, market_code),
                                '이익률(%)': '{:+.2f}%'
                            }), width='stretch', hide_index=True)

                        st.markdown("###### 📝 세부 매도 내역 (최신 시간순)")
                        df_sells['Ticker'] = df_sells['symbol'].apply(lambda x: format_ticker_display(x, market_code))
                        df_sells = df_sells.rename(columns={
                            'date': '매도시간', 'strategy_name': '전략 별칭', 'price': '매도단가', 
                            'qty': '매도수량', 'fee': '수수료', 'total_amount': '매도금액', 
                            'avg_price': '평단가', 'realized_profit': '이익', 'realized_profit_rate': '이익률(%)'
                        })
                        disp_sell_cols = ['매도시간', '전략 별칭', 'Ticker', '매도단가', '매도수량', '수수료', '매도금액', '평단가', '이익', '이익률(%)']
                        st.dataframe(df_sells[disp_sell_cols].sort_values('매도시간', ascending=False), width='stretch')
                    else:
                        st.caption("최근 실현된 매도 수익 내역이 없습니다.")

                # 3. 거래 내역표
                st.markdown("##### 📜 거래 내역 (Detailed Trade History)")

                col_sync_btn_vr, col_sync_info_vr = st.columns([1, 2])
                with col_sync_btn_vr:
                    if st.button("🔄 실시간 계좌 거래내역 동기화", key=f"sync_trade_btn_vr_{symbol}", help="증권사 API로부터 최근 체결 내역 및 잔고를 가져와 DB와 동기화합니다."):
                        with st.spinner(f"[{market_code}] 증권사 API 체결 내역 및 잔고 동기화 중..."):
                            broker = ActiveBroker
                            start_date_sync = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
                            end_date_sync = datetime.now().strftime("%Y%m%d")
                            execs = broker.fetch_execution_history(symbol, start_date_sync, end_date_sync)
                            sync_trade_history_db(symbol, execs, strategy="VR", market=market_code, strategy_name=strategy_alias)
                            
                            # 잔고 및 예수금 동기화
                            pool = broker.get_cash_pool()
                            equity_res = broker.get_account_equity(symbol)
                            if equity_res is not None:
                                shares_live, avg_price_live, eval_amt_live = equity_res
                                current_price_live = broker.get_price(symbol)
                                prev_close_live = broker.get_previous_close(symbol)
                                st.session_state['live_account'] = {
                                    'pool': pool,
                                    'broker_cash': pool,
                                    'shares': shares_live,
                                    'avg_price': avg_price_live,
                                    'eval_amt': eval_amt_live,
                                    'current_price': current_price_live,
                                    'prev_close': prev_close_live,
                                    'symbol': symbol,
                                    'market_code': market_code,
                                    'time': time.strftime("%H:%M:%S")
                                }
                            st.success("✅ 거래 내역 및 계좌 잔고가 증권사 API와 동기화되었습니다.")
                            time.sleep(1)
                            st.rerun()
                with col_sync_info_vr:
                    st.caption("💡 증권사 API와 DB 간 체결 내역/잔고 차이가 있을 때 동기화 버튼을 누르세요.")

                # 위에서 가져온 rows를 재사용하여 상세 내역 표시
                if rows:
                    df_log = pd.DataFrame(rows, columns=cols)
                    # 시장 및 별칭 컬럼 가시성 확보를 위해 컬럼명 변경
                    df_log = df_log.rename(columns={'market': '시장', 'strategy_name': '별칭'})
                    
                    # 별칭(Alias) 필터링 기능 추가
                    unique_aliases = sorted([str(a) if a else "N/A" for a in df_log['별칭'].unique()])
                    selected_aliases = st.multiselect("별칭 필터 (Alias Filter)", options=unique_aliases, default=unique_aliases, key=f"alias_filter_vr_{symbol}")
                    df_log = df_log[df_log['별칭'].fillna("N/A").astype(str).isin(selected_aliases)]

                    st.dataframe(df_log, width='stretch')
                else:
                    st.info("아직 거래 내역이 없습니다. (실시간 체결 시 자동 기록됩니다)")

            except Exception as e:
                st.error(f"VR 상태 표시 중 오류: {e}")
        
        else:
            # === 신규 진입 (VR) ===
            st.warning(f"'{symbol}'에 대한 진행 중인 VR 전략이 없습니다.")
            if 'live_account' in st.session_state and st.session_state['live_account'].get('symbol') == symbol:
                info = st.session_state['live_account']
                init_v = (info.get('shares', 0.0) * info.get('current_price', 0.0)) + info.get('pool', 0.0)
                
                st.info(f"현재 자산 기준으로 **초기 V값**을 설정합니다.")
                st.write(f"- 총 평가 자산 (Equity + Pool): **{currency_symbol}{format_currency(init_v, market_code)}**")
                
                if st.button("✅ VR 전략 초기화 및 시작 (DB 저장)", type="primary"):
                    from core.cavr import VRState
                    # 이미 주식을 보유중이라면 RUNNING 모드로 바로 시작
                    mode = "RUNNING" if info.get('shares', 0.0) > 0 else "BOOTSTRAP"
                    
                    new_state = VRState(
                        symbol=symbol,
                        strategy_type="VR",
                        strategy_name=strategy_alias,
                        market=market_code,
                        V=init_v,
                        pool=info.get('pool', 0.0),
                        last_E=init_v,
                        mode=mode,
                        bootstrap_day_count=0,
                        cycle_V=init_v,
                        cycle_start_pool=info.get('pool', 0.0)
                    )
                    save_state_db(new_state, market=market_code, strategy_name=strategy_alias)
                    st.success(f"**{symbol}** VR 전략 ({mode}) 초기화 완료! 화면을 갱신합니다.")
                    time.sleep(1)
                    st.rerun()
            else:
                st.info("상단의 '🔄 현재 계좌 상태 조회'를 먼저 실행해주세요.")

elif mode == "백테스트":
    # === 백테스트 화면 ===
    if 'run_state' not in st.session_state:
        st.session_state.run_state = 'idle'

    csv_path = os.path.join("data", f"{symbol}.csv")
    file_exists = os.path.exists(csv_path)

    # 1. 현재 설정 상태를 메인 영역에 요약하여 보여줌
    st.markdown("### ⚙️ 백테스트 설정 요약")
    
    col_set1, col_set2 = st.columns(2)
    with col_set1:
        st.markdown(f"""
        - **대상 종목**: `{symbol}`
        - **전략 유형**: **{strategy_choice}** (`{strategy_alias}`)
        - **데이터 기간**: `{fetch_days} 일`
        - **초기 자본금**: `{currency_symbol}{format_currency(initial_cash, market_code)}`
        - **백테스트 수수료**: `{fee_rate * 100:.4f} %`
        - **매도 세금**: `{tax_rate * 100:.4f} %`
        """)
    with col_set2:
        if strategy_choice == "CA":
            st.markdown(f"""
            - **CA 버전**: `{ca_version}`
            - **1회 매수 금액**: `{currency_symbol}{format_currency(unit_buy, market_code)}`
            - **목표 수익률**: `{target_profit * 100:.1f} %`
            - **분할 횟수 (a)**: `{a_default} 회`
            - **쿼터 손절 사용**: `{'ON' if use_quarter_stop else 'OFF'}`
            """)
        else: # VR
            st.markdown(f"""
            - **VR 투자 방식**: `{vr_invest_type_disp}`
            - **G 값 (밸류 성장률)**: `{vr_g_value} %`
            - **밴드 범위**: `±{vr_band_pct} %`
            - **주기별 적립/인출액**: `{currency_symbol}{format_currency(vr_periodic_amt, market_code)}`
            - **적립/인출 주기**: `{vr_freq}`
            """)
            
    st.markdown("---")

    # 2. 백테스트 실행/재실행 버튼 (st.session_state.run_state와 상관없이 항상 렌더링하여 재실행 가능하도록 변경)
    st.markdown("### 🏁 백테스트 시뮬레이션 실행")
    
    if file_exists:
        st.info(f"💾 로컬에 저장된 **'{symbol}.csv'** 파일이 존재합니다. (최근 백테스트 데이터 활용 가능)")
    else:
        st.warning(f"⚠️ **'{symbol}.csv'** 파일이 로컬에 존재하지 않습니다. 먼저 데이터를 수집해야 합니다.")

    col1, col2 = st.columns(2)
    with col1:
        if file_exists:
            if st.button("🔄 기존 데이터로 백테스트 실행", width='stretch', key="bt_run_existing_always"):
                st.session_state.run_state = 'run_with_existing'
                st.rerun()
        else:
            if st.button("🚀 데이터 수집 및 백테스트 실행", type="primary", width='stretch', key="bt_run_new_first_always"):
                st.session_state.run_state = 'run_with_new'
                st.rerun()
    with col2:
        if file_exists:
            if st.button("⚡ 최신 데이터 새로 수집 후 실행", type="primary", width='stretch', key="bt_run_new_force_always"):
                st.session_state.run_state = 'run_with_new'
                st.rerun()

    # 실행 로직
    if st.session_state.run_state in ['run_with_existing', 'run_with_new']:
        # 1. 데이터 수집
        if st.session_state.run_state == 'run_with_new':
            with st.spinner(f'{symbol} 데이터 수집 중...'):
                success, msg = update_ticker_data(symbol, days=int(fetch_days), market=market_code)
            if not success:
                st.error(msg)
                st.session_state.run_state = 'idle'
                st.stop()
            else:
                st.success(msg)

        # 2. 백테스트 실행
        with st.spinner('시뮬레이션 중...'):
            # 공통 파라미터
            backtest_kwargs = {
                "strategy_type": strategy_choice,
                "symbol": symbol,
                "file_path": csv_path,
                "initial_cash": float(initial_cash),
                "fee_rate": float(fee_rate),
                "market": market_code,
                "tax_rate": float(tax_rate if 'tax_rate' in locals() else 0.0)
            }
            
            # 전략별 파라미터 주입
            if strategy_choice == "CA":
                backtest_kwargs.update({
                    "unit_buy_amount": float(unit_buy),
                    "target_profit_pct": target_profit,
                    "a_default": int(a_default),
                    "use_quarter_stop": use_quarter_stop,
                })
            elif strategy_choice == "VR":
                backtest_kwargs.update({
                    "G": float(vr_g_value),
                    "band_low_pct": 100.0 - vr_band_pct,
                    "band_high_pct": 100.0 + vr_band_pct,
                    "initial_budget": float(initial_cash),
                    "periodic_accumulation": float(vr_periodic_amt),
                    "contribution_frequency": vr_freq,
                    "investment_type": vr_investment_type,
                    "pool_limit_pct": float(active_settings.get("pool_limit_pct", 50.0))
                })

            result_text, result_df, trade_history_df = run_backtest(**backtest_kwargs)
            
            # 텔레그램으로 백테스트 결과 요약 전송
            if result_text:
                send_telegram_message(f"🧪 <b>[{symbol} 백테스트 완료]</b>\n<pre>{html.escape(result_text)}</pre>")
        
        # 3. 결과 표시
        st.text_area("결과 요약", value=result_text, height=200)
        
        if not result_df.empty:
            from plotly.subplots import make_subplots
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            # 1. 자산 변동 (좌축) - 시장별 통화 기호 적용
            fig.add_trace(go.Scatter(x=result_df['Date'], y=result_df['TotalEquity'], mode='lines', name=f'Total Equity ({currency_symbol})'), secondary_y=False)
            
            # 2. 주가 변동 (우축)
            fig.add_trace(go.Scatter(x=result_df['Date'], y=result_df['Close'], mode='lines', name='Close Price', line=dict(dash='dot', color='grey', width=1)), secondary_y=True)
            
            # VR 정보 표시 (Target V, Pool, Bands)
            if 'Target_V' in result_df.columns:
                # Target V
                fig.add_trace(go.Scatter(
                    x=result_df['Date'], y=result_df['Target_V'], name=f'Target V ({currency_symbol})',
                    mode='lines',
                    line=dict(dash='dash', color='orange')
                ), secondary_y=False)
                
                # Cash Pool (현금) 표시
                if 'Pool' in result_df.columns:
                    fig.add_trace(go.Scatter(
                        x=result_df['Date'], y=result_df['Pool'], name=f'Cash Pool ({currency_symbol})',
                        mode='lines',
                        line=dict(color='cyan', width=1, dash='dot')
                    ), secondary_y=False)

                # Bands Calculation
                # 슬라이더 값(vr_band_pct)을 가져오거나 기본값 사용
                vr_band_val = locals().get('vr_band_pct', 15)
                band_val = vr_band_val / 100.0
                upper_band = result_df['Target_V'] * (1 + band_val)
                lower_band = result_df['Target_V'] * (1 - band_val)
                
                # Band Area (Low ~ High)
                fig.add_trace(go.Scatter(
                    x=result_df['Date'], y=lower_band,
                    mode='lines', line=dict(width=0), showlegend=False,
                ), secondary_y=False)
                fig.add_trace(go.Scatter(
                    x=result_df['Date'], y=upper_band,
                    mode='lines', name=f'Band (±{vr_band_val}%)',
                    line=dict(width=0),
                    fill='tonexty', fillcolor='rgba(255, 165, 0, 0.1)'
                ), secondary_y=False)

            # 3. 매매 마커 (우축 - 주가 위에 표시)
            if not trade_history_df.empty:
                buys = trade_history_df[trade_history_df['type'] == 'BUY']
                sells = trade_history_df[trade_history_df['type'] == 'SELL']
                
                if not buys.empty:
                    fig.add_trace(go.Scatter(
                        x=buys['Date'], y=buys['price'], mode='markers', name='Buy',
                        marker=dict(color='green', size=8, symbol='triangle-up')), secondary_y=True)
                
                if not sells.empty:
                    fig.add_trace(go.Scatter(
                        x=sells['Date'], y=sells['price'], mode='markers', name='Sell',
                        marker=dict(color='red', size=8, symbol='triangle-down')), secondary_y=True)

            fig.update_yaxes(title_text=f"Total Equity ({currency_symbol})", secondary_y=False)
            fig.update_yaxes(title_text=f"Close Price ({currency_symbol})", secondary_y=True)
            st.plotly_chart(fig, width='stretch')
            
            with st.expander("상세 데이터"):
                st.dataframe(result_df)
        
        st.session_state.run_state = 'idle'

# --- 하단 로그 영역 ---
st.divider()

# 로그 영역을 5초마다 자동 갱신하는 프래그먼트
@st.fragment(run_every=5)
def display_logs_area():
    st.subheader("📋 시스템 로그")
    msg_log_path = os.path.join(PROJECT_ROOT, "logs", "message_log.txt")
    if os.path.exists(msg_log_path):
        with open(msg_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            log_text = "".join(lines[-100:][::-1]) # 최근 100줄 역순 표시
            st.text_area("Live Logs", value=log_text, height=400, help="dashboard 및 scheduler의 주요 메시지를 실시간으로 표시합니다.")
    else:
        st.info("로그 파일이 존재하지 않습니다.")

    st.divider()
    st.subheader("📡 스케줄러 로그 (Background Scheduler)")
    scheduler_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "scheduler.log")
    if os.path.exists(scheduler_log_path):
        with open(scheduler_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            last_logs = "".join(lines[-100:][::-1]) # 최신 로그가 위로 오도록 역순 표시
            st.text_area("Scheduler Logs", value=last_logs, height=400, key="scheduler_logs_live", help="core/scheduler.py 실행 로그입니다.")
    else:
        st.info("스케줄러 로그 파일이 아직 생성되지 않았습니다.")

display_logs_area()
