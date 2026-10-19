"""메리츠증권 미국(해외)주식 브로커 구현체 (Broker 인터페이스 준수)

- 현재가 조회: GET /market/v1/overseas/prices (ovs_market_prices)
- 일봉 시세 조회: GET /market/v1/overseas/candles/days (ovs_market_candles_days)
- 해외주식 주문: POST /trading/v1/overseas/orders/buy / sell (ovs_orders_buy, ovs_orders_sell)
- 잔고 조회: GET /accounts/v1/me/overseas/holdings (ovs_holdings)
- 외화예수금 조회: GET /accounts/v1/me/overseas/currencies (ovs_currencies)
- 환전 연계: USD 부족 시 MeritzForexManager를 통한 자동 환전 지원
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple, List, Literal, Optional, Dict

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent
OPEN_API_DIR = PROJECT_ROOT / "open-api"
if str(OPEN_API_DIR) not in sys.path:
    sys.path.insert(0, str(OPEN_API_DIR))

try:
    from meritz import client, load_catalog, MeritzError  # type: ignore
    from meritz.core import safety  # type: ignore
except ImportError:

    client = None
    load_catalog = None
    MeritzError = Exception
    safety = None

from core.brokers.base import Broker
from config.settings import settings
from core.notifier import send_telegram_message

logger = logging.getLogger(__name__)

# 거래소 코드 기본 매핑 (티커별 거래소)
# 메리츠 해외 거래소 코드: OQ(나스닥), NY(뉴욕), AX(아멕스/Arca)
EXCHANGE_CODE_MAP = {
    "SOXL": ("AX", "AMEX"),
    "TQQQ": ("OQ", "NASD"),
    "UPRO": ("AX", "AMEX"),
    "SPY":  ("AX", "AMEX"),
    "QQQ":  ("OQ", "NASD"),
    "AAPL": ("OQ", "NASD"),
    "NVDA": ("OQ", "NASD"),
    "TSLA": ("OQ", "NASD"),
}


def is_meritz_maintenance_time() -> bool:
    """메리츠증권 계좌 원장 일일 정산 점검 시간 (23:50 ~ 00:20 KST) 여부"""
    from datetime import datetime, time as dtime
    import pytz
    kr_now = datetime.now(pytz.timezone("Asia/Seoul"))
    t = kr_now.time()
    return t >= dtime(23, 50) or t < dtime(0, 20)


class MeritzUsBroker(Broker):
    """메리츠증권 해외주식(미국) 브로커 구현체"""

    def __init__(self):
        if client is None or load_catalog is None:
            raise ImportError(
                "meritz 패키지를 불러올 수 없습니다. 'pip install -e open-api'를 확인하세요."
            )
        self.cat = load_catalog()
        self.client = client()
        self._price_cache: Dict[str, dict] = {}
        logger.info("🇺🇸 MeritzUsBroker 초기화 완료 (기본 시장: US)")

    def _resolve_exchange(self, symbol: str) -> Tuple[str, str]:
        """티커에 따른 (mrkt_cls_code, ovrs_exch_vndr_idno) 반환 (기본: 나스닥 'OQ', 'NASD')"""
        symbol_upper = symbol.upper()
        return EXCHANGE_CODE_MAP.get(symbol_upper, ("OQ", "NASD"))

    def _call(self, key: str, params: dict) -> dict:
        """카탈로그 키 기반 API 호출 공통 헬퍼"""
        # 점검 시간대에 계좌/주문 관련 API 호출 시도 시 조용히 처리
        if is_meritz_maintenance_time() and key in ("ovs_holdings", "ovs_currencies", "ovs_orders_estimate", "valuation", "deposit", "orders_buy", "orders_sell"):
            logger.warning(f"⚠️ [Meritz US] 일일 전산 점검 시간 (23:50 ~ 00:15) 중이므로 [{key}] 호출을 건너뜁니다.")
            return {}

        api_spec = self.cat.get(key)
        if not api_spec:
            raise ValueError(f"카탈로그에서 해외 API 키를 찾을 수 없습니다: {key}")
        res = self.client.call(api_spec, params)
        if not res.get("ok"):
            err_msg = f"[{key}] 호출 실패: {res.get('error')} - {res.get('message')}"
            if "서비스 가능시간이 아닙니다" in str(res.get("message")):
                logger.warning(f"⚠️ [Meritz US] 증권사 점검 시간 (23:50 ~ 00:15): {res.get('message')}")
            else:
                logger.error(err_msg)
            raise RuntimeError(err_msg)
        body = res.get("body", {})
        return body.get("data") or {}

    def get_price(self, symbol: str) -> float:
        """미국 주식 현재가 조회 (symbol: 티커, 예: 'SOXL', 'AAPL')"""
        symbol = symbol.upper()
        mrkt_cls_code, _ = self._resolve_exchange(symbol)
        try:
            params = {
                "mrkt_div_code": "OV",
                "mrkt_cls_code": mrkt_cls_code,
                "iscd": symbol,
                "dely_rltm_cls_code": "0"  # 실시간
            }
            data = self._call("ovs_market_prices", params)
            price_str = data.get("prpr") or data.get("stck_prpr")
            if price_str is not None:
                price = float(price_str)
                self._price_cache[symbol] = data
                return price
        except Exception as e:
            logger.error(f"[Meritz US] 현재가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_previous_close(self, symbol: str) -> float:
        """전일 종가 조회"""
        symbol = symbol.upper()
        if symbol in self._price_cache:
            data = self._price_cache[symbol]
        else:
            mrkt_cls_code, _ = self._resolve_exchange(symbol)
            try:
                data = self._call("ovs_market_prices", {
                    "mrkt_div_code": "OV",
                    "mrkt_cls_code": mrkt_cls_code,
                    "iscd": symbol,
                    "dely_rltm_cls_code": "0"
                })
            except Exception as e:
                logger.error(f"[Meritz US] 전일종가 조회 실패 ({symbol}): {e}")
                return 0.0

        try:
            curr_price = float(data.get("prpr", 0.0))
            diff = float(data.get("diff", 0.0) or data.get("prdy_vrss", 0.0))
            sign = str(data.get("sign", "") or data.get("prdy_vrss_sign", ""))
            # sign: 4, 5 (하락)이면 전일종가 = 현재가 + diff, 1, 2(상승)이면 현재가 - diff
            if sign in ("4", "5", "-"):
                return curr_price + diff
            elif sign in ("1", "2", "+"):
                return curr_price - diff
            elif "base_pric" in data and data["base_pric"]:
                return float(data["base_pric"])
            return curr_price
        except Exception as e:
            logger.error(f"[Meritz US] 전일종가 계산 오류 ({symbol}): {e}")
            return 0.0

    def get_current_high(self, symbol: str) -> float:
        """당일 고가 조회"""
        symbol = symbol.upper()
        try:
            mrkt_cls_code, _ = self._resolve_exchange(symbol)
            data = self._call("ovs_market_prices", {
                "mrkt_div_code": "OV",
                "mrkt_cls_code": mrkt_cls_code,
                "iscd": symbol,
                "dely_rltm_cls_code": "0"
            })
            return float(data.get("hgpr", 0.0) or data.get("stck_hgpr", 0.0))
        except Exception as e:
            logger.error(f"[Meritz US] 고가 조회 실패 ({symbol}): {e}")
            return 0.0

    def get_current_low(self, symbol: str) -> float:
        """당일 저가 조회"""
        symbol = symbol.upper()
        try:
            mrkt_cls_code, _ = self._resolve_exchange(symbol)
            data = self._call("ovs_market_prices", {
                "mrkt_div_code": "OV",
                "mrkt_cls_code": mrkt_cls_code,
                "iscd": symbol,
                "dely_rltm_cls_code": "0"
            })
            return float(data.get("lwpr", 0.0) or data.get("stck_lwpr", 0.0))
        except Exception as e:
            logger.error(f"[Meritz US] 저가 조회 실패 ({symbol}): {e}")
            return 0.0

    def get_last_5_day_avg_close(self, symbol: str) -> float:
        """최근 5거래일 종가 평균 조회 (일봉)"""
        symbol = symbol.upper()
        mrkt_cls_code, _ = self._resolve_exchange(symbol)
        try:
            days = self._call("ovs_market_candles_days", {
                "mrkt_div_code": "OV",
                "mrkt_cls_code": mrkt_cls_code,
                "iscd": symbol,
                "dely_rltm_cls_code": "0",
                "mod_stpr_cls_code": "0"
            })
            rows = days if isinstance(days, list) else [days]
            closes = [
                float(row.get("prpr") or row.get("clos_pric") or row.get("stck_clpr") or 0.0)
                for row in rows[:5]
                if row.get("prpr") or row.get("clos_pric") or row.get("stck_clpr")
            ]
            if closes:
                return sum(closes) / len(closes)
        except Exception as e:
            logger.error(f"[Meritz US] 5일 평균가 조회 실패 ({symbol}): {e}")
        return 0.0

    def get_account_equity(self, symbol: str) -> Tuple[float, float, float]:
        """(보유수량, 평균매입가, 평가금액) 반환 (단위: USD)"""
        symbol = symbol.upper()
        try:
            holdings = self._call("ovs_holdings", {})
            rows = holdings if isinstance(holdings, list) else [holdings]
            for row in rows:
                row_symbol = (row.get("ovrs_stck_symb_iscd") or row.get("iscd") or "").upper()
                if row_symbol == symbol:
                    shares = float(row.get("ovrs_cblc_qty", 0.0) or row.get("hld_qty", 0.0))
                    avg_price = float(row.get("pchs_avg_pric", 0.0) or row.get("avg_prc", 0.0))
                    eval_amt = float(row.get("frcr_evlu_amt", 0.0) or row.get("evlu_amt", 0.0))
                    return (shares, avg_price, eval_amt)
        except Exception as e:
            logger.error(f"[Meritz US] 잔고 조회 실패 ({symbol}): {e}")
        return (0.0, 0.0, 0.0)

    def get_cash_pool(self) -> float:
        """외화(USD) 주문가능 예수금 조회"""
        try:
            # 1. 외화통화별 예수금 조회 (ovs_currencies)
            currencies = self._call("ovs_currencies", {})
            rows = currencies if isinstance(currencies, list) else [currencies]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                crcd = (row.get("crcd") or row.get("crnc_code") or "").upper()
                if crcd == "USD":
                    cash = row.get("frcr_amt") or row.get("estm_frcr_amt") or row.get("stnd_deps_camt") or row.get("frcr_dncl_amt") or row.get("ord_psbl_frcr_amt")
                    if cash is not None:
                        val = float(cash)
                        if val > 0:
                            return val

            # 2. 폴백: 주문가능금액 조회 (ovs_orders_estimate)
            est = self._call("ovs_orders_estimate", {"intg_marg_iqry_yn": "N"})
            est_rows = est if isinstance(est, list) else ([est] if isinstance(est, dict) else [])
            for er in est_rows:
                if not isinstance(er, dict):
                    continue
                crcd = (er.get("crcd") or "").upper()
                if crcd in ("USD", ""):
                    cash = er.get("oder_crnc_oder_able_camt") or er.get("frcr_amt") or er.get("stnd_deps_camt") or er.get("ord_psbl_frcr_amt")
                    if cash is not None:
                        val = float(cash)
                        if val > 0:
                            return val

            # 3. 폴백: 자산평가(valuation)의 frcr_tfam (원화 환산액) -> 환율 역산
            val_data = self._call("valuation", {})
            if isinstance(val_data, dict):
                frcr_tfam = float(val_data.get("frcr_tfam", 0.0))
                if frcr_tfam > 0:
                    exrt = 1348.5  # 기본 환율
                    for r in rows:
                        if isinstance(r, dict) and r.get("vltn_exrt"):
                            exrt = float(r["vltn_exrt"])
                            break
                    return round(frcr_tfam / exrt, 2)
        except Exception as e:
            logger.error(f"[Meritz US] 외화예수금 조회 실패: {e}")
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
        미국 주식 주문 전송
        - ovrs_stck_symb_iscd: 티커 (예: 'SOXL')
        - oder_cls_code: 00 (지정가), 01 (시장가)
        """
        symbol = symbol.upper()
        _, exch_vndr = self._resolve_exchange(symbol)
        key = "ovs_orders_buy" if order_type == "BUY" else "ovs_orders_sell"
        oder_cls_code = "01" if price_type in ("03", "MARKET") else "00"

        # 가격 보정 (미국 소수점 2자리)
        order_price = f"{price:.2f}" if oder_cls_code == "00" else "0"

        body = {
            "ovrs_stck_symb_iscd": symbol,
            "ovrs_exch_vndr_idno": exch_vndr,
            "oder_cls_code": oder_cls_code,
            "oder_cond_cls_code": "0",  # 일반
            "odqt": str(int(qty)),
            "ovrs_stck_oder_prc": order_price,
            "warn_cnfr_yn": "N"
        }

        api_spec = self.cat.get(key)
        try:
            # 안전장치 확인 (confirm_token 발급)
            pv = safety.preview(api_spec, body, settings.MERITZ_BASE_URL, settings.MERITZ_APP_KEY)
            confirm_token = pv.get("confirm_token")

            # 실제 주문 호출
            res = self.client.call(api_spec, {**body, "confirm_token": confirm_token})
            if res.get("ok"):
                msg = f"✅ [Meritz US {order_type} 주문 성공] {symbol} {qty}주 @ ${order_price} ({strategy}/{strategy_name})"
                logger.info(msg)
                send_telegram_message(msg)
                return True
            else:
                err = f"❌ [Meritz US 주문 실패] {res.get('error')}: {res.get('message')}"
                logger.error(err)
                send_telegram_message(err)
                return False
        except Exception as e:
            err = f"❌ [Meritz US 주문 예외]: {e}"
            logger.error(err)
            send_telegram_message(err)
            return False

    @property
    def account_no(self) -> str:
        """메리츠 계좌 식별자 (환경설정 또는 기본값)"""
        return getattr(settings, "MERITZ_ACCOUNT_NO", "MERITZ-ACCOUNT") or "MERITZ-ACCOUNT"

    def get_stock_info(self, symbol: str) -> dict:
        """종목 상세 정보 조회 (UI 검색용)"""
        symbol = symbol.upper()
        try:
            mrkt_cls_code, _ = self._resolve_exchange(symbol)
            data = self._call("ovs_market_prices", {
                "mrkt_div_code": "OV",
                "mrkt_cls_code": mrkt_cls_code,
                "iscd": symbol,
                "dely_rltm_cls_code": "0"
            })
            if data:
                return {
                    "prdt_name": data.get("prdt_name") or data.get("stck_shrn_iscd") or symbol,
                    "prdt_clsf_name": "해외(미국)주식",
                    "ivst_prdt_type_cd_name": "ETF/주식"
                }
        except Exception as e:
            logger.warning(f"[Meritz US] 종목정보 조회 실패 ({symbol}): {e}")
        return {"prdt_name": symbol, "prdt_clsf_name": "해외(미국)주식", "ivst_prdt_type_cd_name": "ETF/주식"}

    def get_exchange_rate(self, force: bool = False) -> dict:
        """실시간 고시환율/적용환율 조회 (MeritzForexManager 연계)"""
        try:
            from core.forex import forex_manager
            from core.database import get_previous_exchange_rate_db, get_latest_exchange_rate_db

            # 1. 실시간 적용환율 (외화매수 기준, 최신 시각 반영) 우선 조회
            quote = forex_manager.get_applied_rate(direction="BUY", symbol="USD")
            if quote and quote.get("applied_rate", 0) > 0:
                market_rate = float(quote["applied_rate"])
                trade_date = quote.get("pros_date", datetime.now().strftime("%Y%m%d"))
                prev_record = get_previous_exchange_rate_db(trade_date)
                if prev_record and prev_record.get("rate"):
                    base_rate = float(prev_record["rate"])
                else:
                    # DB에 전일 레코드가 없으면 market_rate 또는 고시 매매기준율 사용
                    market_info = forex_manager.get_market_rate(symbol="USD", force_refresh=force)
                    base_rate = float(market_info.get("deal_stnd_exrt", 0.0)) if market_info else market_rate
                    if base_rate <= 0:
                        base_rate = market_rate

                diff = market_rate - base_rate
                pct = (diff / base_rate * 100.0) if base_rate > 0 else 0.0
                return {
                    "rate": market_rate,
                    "base_rate": base_rate,
                    "diff": diff,
                    "pct": pct,
                    "time": quote.get("exrt_stnd_time", datetime.now().strftime("%H:%M:%S")),
                    "source": "MERITZ_APPLIED"
                }

            # 2. 고시환율 조회 fallback (당일 기준환율 stnd_exrt 우선)
            rate_info = forex_manager.get_market_rate(symbol="USD", force_refresh=force)
            if rate_info:
                stnd_exrt = float(rate_info.get("stnd_exrt", 0.0))
                deal_stnd_exrt = float(rate_info.get("deal_stnd_exrt", 0.0))
                market_rate = stnd_exrt if stnd_exrt > 0 else deal_stnd_exrt
                
                if market_rate > 0:
                    trade_date = rate_info.get("date", datetime.now().strftime("%Y%m%d"))
                    prev_record = get_previous_exchange_rate_db(trade_date)
                    base_rate = float(prev_record["rate"]) if prev_record and prev_record.get("rate") else (deal_stnd_exrt if deal_stnd_exrt > 0 else market_rate)
                    diff = market_rate - base_rate
                    pct = (diff / base_rate * 100.0) if base_rate > 0 else 0.0
                    return {
                        "rate": market_rate,
                        "base_rate": base_rate,
                        "diff": diff,
                        "pct": pct,
                        "time": rate_info.get("hour", datetime.now().strftime("%H:%M:%S")),
                        "source": "MERITZ_FOREX"
                    }
        except Exception as e:
            logger.error(f"[Meritz US] 환율 조회 실패: {e}")
        return {"rate": 1334.95, "diff": 0.0, "pct": 0.0, "source": "FALLBACK"}

    def fetch_daily_chart(self, symbol: str, days: int = 300) -> List[dict]:
        """미국 주식 일봉 시세 조회 (ovs_market_candles_days)"""
        symbol = symbol.upper()
        mrkt_cls_code, _ = self._resolve_exchange(symbol)
        try:
            # days 거래일을 커버하기 위해 약 1.6배 일수 역산하여 시작일자 산출
            end_dt = datetime.now().strftime("%Y%m%d")
            start_dt = (datetime.now() - timedelta(days=int(days * 1.6) + 30)).strftime("%Y%m%d")

            params = {
                "mrkt_div_code": "OV",
                "mrkt_cls_code": mrkt_cls_code,
                "iscd": symbol,
                "dely_rltm_cls_code": "0",  # 필수: 0(실시간), 1(지연)
                "mod_stpr_cls_code": "0",   # 필수: 0(수정주가 보정 주가), 1(보정 전 원래 주가)
                "from": start_dt,
                "to": end_dt
            }
            res = self._call("ovs_market_candles_days", params)
            rows = res if isinstance(res, list) else [res]
            chart = []
            for row in rows[:days]:
                d = row.get("date") or row.get("stck_bsop_date")
                if not d:
                    continue
                # 필드 매핑: oprc(시가), hprc(고가), lprc(저가), prpr(종가), acml_vol(거래량)
                open_p = float(row.get("oprc") or row.get("open_pric") or row.get("stck_oprc") or 0.0)
                high_p = float(row.get("hprc") or row.get("high_pric") or row.get("stck_hgpr") or 0.0)
                low_p = float(row.get("lprc") or row.get("low_pric") or row.get("stck_lwpr") or 0.0)
                close_p = float(row.get("prpr") or row.get("clos_pric") or row.get("stck_clpr") or 0.0)
                vol = float(row.get("acml_vol") or 0.0)

                chart.append({
                    "Date": d,
                    "Open": open_p,
                    "High": high_p,
                    "Low": low_p,
                    "Close": close_p,
                    "Volume": vol
                })
            return chart
        except Exception as e:
            logger.error(f"[Meritz US] 일봉 조회 실패 ({symbol}): {e}")
            return []

    def fetch_open_orders(self, symbol: str) -> List[dict]:
        """미체결 내역 조회 (ovs_orders_history / ovs_orders_today 필터)"""
        return []

    def fetch_execution_history(self, symbol: str, start_date: str, end_date: str) -> List[dict]:
        """체결 내역 조회 (ovs_orders_history)"""
        return []

