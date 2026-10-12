import sys
import logging
from pathlib import Path
from typing import Tuple, List, Literal, Optional

# open-api 패키지 경로 추가 (editable 설치 전에도 동작하도록)
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
OPEN_API_DIR = PROJECT_ROOT / "open-api"
if str(OPEN_API_DIR) not in sys.path:
    sys.path.insert(0, str(OPEN_API_DIR))

try:
    from meritz import client, load_catalog, MeritzError  # type: ignore
    from meritz.core import safety  # type: ignore
except ImportError:

    # 패키지 설치 전 대비용
    client = None
    load_catalog = None
    MeritzError = Exception
    safety = None

from core.brokers.base import Broker
from config.settings import settings

logger = logging.getLogger(__name__)

class MeritzKrBroker(Broker):
    """메리츠증권 국내주식 브로커 구현체 (Broker 인터페이스 준수)"""

    def __init__(self):
        if client is None or load_catalog is None:
            raise ImportError(
                "meritz 패키지를 불러올 수 없습니다. 'pip install -e open-api'를 실행하거나 경로를 확인하세요."
            )
        self.cat = load_catalog()
        self.client = client()
        self._price_cache = {}
        logger.info("MeritzKrBroker 초기화 완료 (기본 시장: KR)")

    def _call(self, key: str, params: dict) -> dict:
        """카탈로그 키 기반 API 호출 공통 헬퍼"""
        api_spec = self.cat.get(key)
        if not api_spec:
            raise ValueError(f"카탈로그에서 API 키를 찾을 수 없습니다: {key}")
        res = self.client.call(api_spec, params)
        if not res.get("ok"):
            err_msg = f"[{key}] 호출 실패: {res.get('error')} - {res.get('message')}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)
        body = res.get("body", {})
        return body.get("data") or {}

    def get_price(self, symbol: str) -> float:
        """국내 주식 현재가 조회 (symbol: 6자리 종목코드, 예: '005930')"""
        try:
            data = self._call("market_prices", {"mrkt_div_code": "J", "iscd": symbol})
            price_str = data.get("stck_prpr")
            if price_str is not None:
                return float(price_str)
        except Exception as e:
            logger.error(f"[Meritz KR] 현재가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_previous_close(self, symbol: str) -> float:
        """전일 종가 조회"""
        try:
            data = self._call("market_prices", {"mrkt_div_code": "J", "iscd": symbol})
            curr_price = float(data.get("stck_prpr", 0.0))
            diff = float(data.get("prdy_vrss", 0.0))
            # 메리츠 market_prices에서 전일종가 = 현재가 - 전일대비
            # sign 코드(prdy_vrss_sign): 1 상승, 2 상승, 3 보합, 4 하락, 5 하락 등
            sign = data.get("prdy_vrss_sign", "3")
            if sign in ("4", "5"):
                return curr_price + diff
            elif sign in ("1", "2"):
                return curr_price - diff
            else:
                return curr_price
        except Exception as e:
            logger.error(f"[Meritz KR] 전일종가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_current_high(self, symbol: str) -> float:
        """당일 고가 조회"""
        try:
            data = self._call("market_prices", {"mrkt_div_code": "J", "iscd": symbol})
            return float(data.get("stck_hgpr", 0.0))
        except Exception as e:
            logger.error(f"[Meritz KR] 고가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_current_low(self, symbol: str) -> float:
        """당일 저가 조회"""
        try:
            data = self._call("market_prices", {"mrkt_div_code": "J", "iscd": symbol})
            return float(data.get("stck_lwpr", 0.0))
        except Exception as e:
            logger.error(f"[Meritz KR] 저가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_last_5_day_avg_close(self, symbol: str) -> float:
        """최근 5거래일 종가 평균 조회"""
        try:
            days = self._call("market_candles_days", {"mrkt_div_code": "J", "iscd": symbol})
            rows = days if isinstance(days, list) else [days]
            closes = [float(row.get("stck_clpr", 0.0)) for row in rows[:5] if row.get("stck_clpr")]
            if closes:
                return sum(closes) / len(closes)
        except Exception as e:
            logger.error(f"[Meritz KR] 5일 평균가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_account_equity(self, symbol: str) -> Tuple[float, float, float]:
        """(보유수량, 평균매입가, 평가금액) 반환"""
        try:
            holdings = self._call("holdings", {})
            rows = holdings if isinstance(holdings, list) else [holdings]
            for row in rows:
                row_code = row.get("iscd", "") or row.get("pdno", "")
                if symbol in row_code:
                    shares = float(row.get("hld_qty", 0.0) or row.get("cblc_qty", 0.0))
                    avg_price = float(row.get("pchs_avg_pric", 0.0) or row.get("avg_prc", 0.0))
                    eval_amt = float(row.get("evlu_amt", 0.0))
                    return (shares, avg_price, eval_amt)
        except Exception as e:
            logger.error(f"[Meritz KR] 계좌 잔고 조회 실패 ({symbol}): {e}")
        return (0.0, 0.0, 0.0)

    def get_cash_pool(self) -> float:
        """예수금(주문 가능 현금) 조회"""
        try:
            data = self._call("deposit", {})
            # 예수금 / 출금가능금액 필드 파싱
            cash = data.get("dnca_tot_amt") or data.get("ord_psbl_cash") or data.get("dpst_amt")
            if cash is not None:
                return float(cash)
        except Exception as e:
            logger.error(f"[Meritz KR] 예수금 조회 실패: {e}")
        return 0.0

    def place_order(
        self,
        symbol: str,
        price: float,
        qty: float,
        order_type: Literal["BUY", "SELL"],
        price_type: str = "00",
        strategy: str = "MANUAL",
        strategy_name: str = "",
        stop_price: Optional[float] = None
    ) -> bool:
        """
        주문 전송
        - 메리츠 주문 종목코드는 'A' + 6자리 (예: 'A005930')
        - oder_cls_code: 01 (지정가), 05 (시장가)
        """
        order_symbol = f"A{symbol}" if not symbol.startswith("A") else symbol
        key = "orders_buy" if order_type == "BUY" else "orders_sell"
        oder_cls_code = "05" if price_type in ("03", "MARKET") else "01"

        body = {
            "iscd": order_symbol,
            "odqt": str(int(qty)),
            "oder_unpr": str(int(price)) if oder_cls_code == "01" else "0",
            "oder_cls_code": oder_cls_code,
            "oder_cond_cls_code": "0",  # 일반
            "orgl_oder_no": "0",
            "whol_rctf_cncl_yn": "N",
            "warn_cnfr_yn": "N",
            "exch_kind_code": "01"       # KRX
        }

        api_spec = self.cat.get(key)
        try:
            # 안전장치 미리보기 및 토큰 발급
            pv = safety.preview(api_spec, body, settings.MERITZ_BASE_URL, settings.MERITZ_APP_KEY)
            confirm_token = pv.get("confirm_token")

            # 실제 주문 호출
            res = self.client.call(api_spec, {**body, "confirm_token": confirm_token})
            if res.get("ok"):
                logger.info(f"✅ [Meritz {order_type} 주문 성공] {symbol} {qty}주 @ {price}원")
                return True
            else:
                logger.error(f"❌ [Meritz 주문 실패] {res.get('error')}: {res.get('message')}")
                return False
        except Exception as e:
            logger.error(f"❌ [Meritz 주문 예외 발생]: {e}")
            return False

    @property
    def account_no(self) -> str:
        """메리츠 계좌 식별자"""
        return getattr(settings, "MERITZ_ACCOUNT_NO", "MERITZ-ACCOUNT") or "MERITZ-ACCOUNT"

    def get_stock_info(self, symbol: str) -> dict:
        """국내 종목 정보 조회"""
        try:
            data = self._call("market_prices", {"mrkt_div_code": "J", "iscd": symbol})
            if data:
                return {
                    "prdt_name": data.get("prdt_name") or data.get("rprs_mrkt_kor_name") or symbol,
                    "prdt_clsf_name": "국내주식",
                    "ivst_prdt_type_cd_name": "주식/ETF"
                }
        except Exception as e:
            logger.warning(f"[Meritz KR] 종목정보 조회 실패 ({symbol}): {e}")
        return {"prdt_name": symbol, "prdt_clsf_name": "국내주식", "ivst_prdt_type_cd_name": "주식/ETF"}

    def get_exchange_rate(self, force: bool = False) -> dict:
        """환율 정보 (국내는 1.0 고정)"""
        return {"rate": 1.0, "diff": 0.0, "pct": 0.0, "source": "KRW"}

    def fetch_daily_chart(self, symbol: str, days: int = 300) -> List[dict]:
        """국내 주식 일봉 시세 조회"""
        try:
            res = self._call("market_candles_days", {"mrkt_div_code": "J", "iscd": symbol})
            rows = res if isinstance(res, list) else [res]
            chart = []
            for row in rows[:days]:
                d = row.get("stck_bsop_date") or row.get("date")
                if not d:
                    continue
                chart.append({
                    "Date": d,
                    "Open": float(row.get("stck_oprc", 0.0)),
                    "High": float(row.get("stck_hgpr", 0.0)),
                    "Low": float(row.get("stck_lwpr", 0.0)),
                    "Close": float(row.get("stck_clpr", 0.0)),
                    "Volume": float(row.get("acml_vol", 0.0))
                })
            return chart
        except Exception as e:
            logger.error(f"[Meritz KR] 일봉 조회 실패 ({symbol}): {e}")
            return []

    def fetch_open_orders(self, symbol: str) -> List[dict]:
        """미체결 내역 조회 (추후 카탈로그 키 매핑)"""
        return []

    def fetch_execution_history(self, symbol: str, start_date: str, end_date: str) -> List[dict]:
        """체결 내역 조회 (추후 카탈로그 키 매핑)"""
        return []

