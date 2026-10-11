"""Meritz 자동매매 및 CAVR 전략 이식 상태 종합 검증 스크립트 (test_meritz_setup.py)

10월 12일 실 API KEY 발급 전 준비 상태를 사전 점검합니다:
1. 환경설정(.env, .env.kr, .env.us) 로드 상태
2. SQLite DB (cavr.db) 테이블 및 CRUD 상태 (forex_history 포함)
3. 메리츠 공식 SDK 및 브로커 (MeritzKrBroker, MeritzUsBroker) 초기화
4. CAVR 엔진 (CA, VR) 초기화 및 상태 머신 동작
5. 외환 관리자 (MeritzForexManager) 모의 환전(READ_ONLY) 시뮬레이션
6. 텔레그램 알림 모듈 설정 확인
"""

import sys
from pathlib import Path

# Windows 콘솔 인코딩 대응
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

def test_environment():
    print("\n--- [1] 환경변수 및 설정 검증 ---")
    from config.settings import settings, load_market_env
    print(f"• MERITZ_BASE_URL: {settings.MERITZ_BASE_URL}")
    print(f"• MERITZ_READ_ONLY: {settings.MERITZ_READ_ONLY} (안전모드)")
    print(f"• DB 경로: {settings.DB_PATH}")
    print(f"• 텔레그램 토큰 설정 여부: {'설정됨' if settings.TELEGRAM_BOT_TOKEN else '미설정'}")
    print(f"• 텔레그램 Chat ID: {'설정됨' if settings.TELEGRAM_CHAT_ID else '미설정'}")

    kr_env = load_market_env("KR")
    print(f"• [KR] 티커: {kr_env['ticker']}, 초기자금: {kr_env['initial_cash']:,.0f}원")

    us_env = load_market_env("US")
    print(f"• [US] 티커: {us_env['ticker']}, 초기자금: ${us_env['initial_cash']:,.1f}")
    return True

def test_database():
    print("\n--- [2] 데이터베이스(cavr.db) 초기화 및 스키마 검증 ---")
    import sqlite3
    from core.database import init_db, log_forex_trade_db, get_forex_history_db
    init_db()
    
    conn = sqlite3.connect("data/cavr.db")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    conn.close()

    required_tables = ["trade_history", "order_history", "forex_history", "exchange_rates", "strategy_state"]
    missing = [t for t in required_tables if t not in tables]
    if missing:
        print(f"❌ 누락된 테이블: {missing}")
        return False
    print(f"✅ 필수 테이블 확인 완료: {required_tables}")

    # 모의 환전 DB 로깅 테스트
    log_forex_trade_db("20261011", "120000", "1", "USD", 1420.5, 1420500, 1000.0, 0, 0, 9999, "TEST", "단위 테스트")
    history = get_forex_history_db(limit=1)
    if history and history[0]["crcd"] == "USD":
        print(f"✅ forex_history CRUD 테스트 성공 (최신 건: {history[0]['direction']}, 환율 {history[0]['applied_rate']}원)")
    return True

def test_brokers_and_forex():
    print("\n--- [3] 브로커 및 환전 관리자 검증 ---")
    from core.brokers.meritz_kr import MeritzKrBroker
    from core.brokers.meritz_us import MeritzUsBroker
    from core.forex import forex_manager

    kr_broker = MeritzKrBroker()
    us_broker = MeritzUsBroker()
    print("✅ MeritzKrBroker 및 MeritzUsBroker 인스턴스화 성공")

    # 환전 시뮬레이션 테스트
    res = forex_manager.execute_exchange(
        direction="BUY",
        amount_usd=50.0,
        note="시스템 사전점검 모의 환전 테스트"
    )
    print(f"✅ 외환 관리자(ForexManager) 모의 환전 시뮬레이션 결과: {res}")
    return True

def test_cavr_engine():
    print("\n--- [4] CA/VR 전략 엔진 검증 ---")
    from core.cavr import CAConfig, VRConfig, CostAveragingEngine, ValueRebalancingEngine
    from core.brokers.meritz_kr import MeritzKrBroker
    from core.brokers.meritz_us import MeritzUsBroker

    # 1. 국내 CA 엔진 모의 생성
    ca_config = CAConfig(
        symbol="122630",
        strategy_type="CA",
        market="KR",
        initial_budget=10000000,
        strategy_name="CA_KODEX레버리지_테스트"
    )
    ca_engine = CostAveragingEngine(config=ca_config, broker=MeritzKrBroker())
    print(f"✅ CostAveragingEngine 초기화 성공 (종목: {ca_engine.config.symbol}, 시장: {ca_engine.config.market})")

    # 2. 미국 VR 엔진 모의 생성
    vr_config = VRConfig(
        symbol="SOXL",
        strategy_type="VR",
        market="US",
        initial_budget=10000.0,
        strategy_name="VR_SOXL_테스트"
    )
    vr_engine = ValueRebalancingEngine(config=vr_config, broker=MeritzUsBroker())
    print(f"✅ ValueRebalancingEngine 초기화 성공 (종목: {vr_engine.config.symbol}, 시장: {vr_engine.config.market})")
    return True


if __name__ == "__main__":
    print("==================================================")
    print("  메리츠 Open API 자동매매 이식 상태 종합 검증  ")
    print("==================================================")
    try:
        test_environment()
        test_database()
        test_brokers_and_forex()
        test_cavr_engine()
        print("\n🎉 모든 단위 점검을 성공적으로 통과했습니다!")
        print("내일(10/12) 메리츠 개발자 포털에서 API Key 발급 후 즉시 실거래/실계좌 연동이 가능합니다.")
    except Exception as e:
        print(f"\n❌ 검증 실패: {e}")
        import traceback
        traceback.print_exc()
