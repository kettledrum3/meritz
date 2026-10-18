"""Meritz Open API 환율 조회 및 환전 관리 모듈 (MeritzForexManager)

- 고시환율 조회: GET /forex/v1/rates (fx_rates)
- 환전 적용환율 조회: GET /forex/v1/rates/applied (fx_rates_applied)
- 실시간 환전신청: POST /forex/v1/exchanges (fx_exchanges)
- 환전 내역 조회: GET /forex/v1/exchanges/history (fx_exchanges_history)
- CAVR 연계 스마트 환전 지원 (USD 부족 시 자동 충전, 익절 달러 원화 회수)
"""

import sys
import time
import requests
import logging
from pathlib import Path
from datetime import datetime, date, timedelta, time as dtime
from typing import Optional, Dict, Any, List, Tuple
import pytz

# open-api 패키지 경로 추가
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
OPEN_API_DIR = PROJECT_ROOT / "open-api"
if str(OPEN_API_DIR) not in sys.path:
    sys.path.insert(0, str(OPEN_API_DIR))

try:
    from meritz import client, load_catalog, MeritzError  # type: ignore
except ImportError:
    client = None
    load_catalog = None
    MeritzError = Exception

from config.settings import settings
from core.database import (
    log_forex_trade_db, get_forex_history_db, save_exchange_rate_db,
    save_forex_strategy_state_db, load_forex_strategy_state_db
)
from core.notifier import send_telegram_message

logger = logging.getLogger(__name__)


def is_forex_available_time(now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    메리츠증권 USD 실시간 환전 가능 시간 여부 판별 (2026.08.24 개정 기준)
    - 실시간 환전 가능 시간: 영업일 09:00 ~ 다음 날 02:00
    - 점검시간: 23:50 ~ 00:20 (환전 불가)
    :return: (is_available: bool, reason: str)
    """
    if now_dt is None:
        now_dt = datetime.now(pytz.timezone("Asia/Seoul"))

    weekday = now_dt.weekday()  # 0:월, 1:화, ..., 4:금, 5:토, 6:일
    cur_time = now_dt.time()

    # 1. 일일 전산 점검 시간 (23:50 ~ 00:20)
    if cur_time >= dtime(23, 50) or cur_time < dtime(0, 20):
        return False, "전산 점검시간 (23:50 ~ 00:20) 환전 불가"

    # 2. 새벽 00:20 ~ 02:00 (전일 영업일의 연장 세션)
    # 화(1)~토(5) 새벽 00:20~02:00 허용 (월~금 영업일의 익일 새벽)
    if dtime(0, 20) <= cur_time < dtime(2, 0):
        if 1 <= weekday <= 5:
            return True, "실시간 환전 가능 (익일 연장 세션 00:20 ~ 02:00)"
        else:
            return False, "주말/휴일 새벽 환전 불가"

    # 3. 주간 및 야간 09:00 ~ 23:50 (당일 영업일 정규 세션)
    # 월(0)~금(4) 09:00~23:50 허용
    if dtime(9, 0) <= cur_time < dtime(23, 50):
        if 0 <= weekday <= 4:
            return True, "실시간 환전 가능 (영업일 정규 세션 09:00 ~ 23:50)"
        else:
            return False, "주말/휴일 환전 불가"

    # 4. 그 외 시간대 (02:00 ~ 09:00, 주말 등)
    return False, "실시간 환전 가능 시간 아님 (영업일 09:00 ~ 다음 날 02:00)"


class MeritzForexManager:
    """메리츠증권 외환(FX) 및 환전 통합 관리자"""

    def __init__(self):
        if client is None or load_catalog is None:
            raise ImportError(
                "meritz 패키지를 불러올 수 없습니다. 'pip install -e open-api' 또는 경로를 확인하세요."
            )
        self.cat = load_catalog()
        self.client = client()
        self._dxy_cache: Tuple[float, float] = (0.0, 0.0)  # (timestamp, dxy_value)
        self._3m_avg_cache: Dict[str, Tuple[float, float]] = {}  # symbol -> (timestamp, avg_val)
        logger.info("💱 MeritzForexManager 초기화 완료")

    def _call(self, key: str, params: dict) -> dict:
        """카탈로그 키 기반 API 호출 공통 헬퍼"""
        api_spec = self.cat.get(key)
        if not api_spec:
            raise ValueError(f"카탈로그에서 외환 API 키를 찾을 수 없습니다: {key}")
        res = self.client.call(api_spec, params)
        if not res.get("ok"):
            err_msg = f"[{key}] 호출 실패: {res.get('error')} - {res.get('message')}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)
        body = res.get("body", {})
        return body.get("data") or {}

    def get_market_rate(self, symbol: str = "USD", target_date: Optional[str] = None, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        고시환율 조회 (기본: 오늘 일자, USD)
        :param symbol: 통화 코드 (대문자 3자리, 기본 'USD')
        :param target_date: 조회일자 YYYYMMDD (None이면 오늘)
        :param force_refresh: 캐시 무시 강제 갱신 여부
        :return: 기준환율, 전신환 매도/매입환율, 매매기준환율 등 딕셔너리
        """
        stnd_date = target_date or datetime.now().strftime("%Y%m%d")
        symbol = symbol.upper()
        try:
            data = self._call("fx_rates", {"stnd_date": stnd_date, "crcd": symbol})
            rows = data if isinstance(data, list) else [data]
            for row in rows:
                if row.get("crcd") == symbol:
                    stnd_exrt = float(row.get("stnd_exrt", 0.0))
                    deal_stnd_exrt = float(row.get("deal_stnd_exrt", 0.0))
                    # 당일 실제 기준환율은 stnd_exrt(실시간 고시). deal_stnd_exrt는 전일 매매기준환율(전일 장마감 기준)
                    effective_rate = stnd_exrt if stnd_exrt > 0 else deal_stnd_exrt
                    rate_info = {
                        "date": row.get("tr_date", stnd_date),
                        "crcd": symbol,
                        "name": row.get("crcd_kor_name", "미국 달러"),
                        "stnd_exrt": stnd_exrt,                  # 당일 고시 기준환율 (실시간)
                        "deal_stnd_exrt": deal_stnd_exrt,        # 전일 매매기준환율
                        "effective_rate": effective_rate,        # 유효 실시간 환율
                        "tltr_byrt": float(row.get("tltr_byrt", 0.0)),         # 전신환 매입율
                        "tltr_slrt": float(row.get("tltr_slrt", 0.0)),         # 전신환 매도율
                        "hour": row.get("pros_hour", "")
                    }
                    if symbol == "USD" and effective_rate > 0:
                        save_exchange_rate_db(
                            trade_date=rate_info["date"],
                            recorded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            rate=effective_rate,
                            base_rate=deal_stnd_exrt if deal_stnd_exrt > 0 else effective_rate,
                            diff=round(effective_rate - (deal_stnd_exrt if deal_stnd_exrt > 0 else effective_rate), 2),
                            pct=round(((effective_rate - deal_stnd_exrt) / deal_stnd_exrt * 100.0) if deal_stnd_exrt > 0 else 0.0, 2),
                            source="MERITZ"
                        )
                    return rate_info
        except Exception as e:
            logger.debug(f"[FX] {stnd_date} 당일 고시환율 조회 대기: {e}")

        # 당일 데이터가 아직 없는 경우(새벽 시간 등) 최대 5일 전까지 역추적하여 직전 고시환율을 조회
        if target_date is None:
            now_dt = datetime.now()
            for delta in range(1, 6):
                prev_date = (now_dt - timedelta(days=delta)).strftime("%Y%m%d")
                try:
                    data = self._call("fx_rates", {"stnd_date": prev_date, "crcd": symbol})
                    rows = data if isinstance(data, list) else [data]
                    for row in rows:
                        if row.get("crcd") == symbol:
                            stnd_exrt = float(row.get("stnd_exrt", 0.0))
                            deal_stnd_exrt = float(row.get("deal_stnd_exrt", 0.0))
                            effective_rate = stnd_exrt if stnd_exrt > 0 else deal_stnd_exrt
                            rate_info = {
                                "date": row.get("tr_date", prev_date),
                                "crcd": symbol,
                                "name": row.get("crcd_kor_name", "미국 달러"),
                                "stnd_exrt": stnd_exrt,
                                "deal_stnd_exrt": deal_stnd_exrt,
                                "effective_rate": effective_rate,
                                "tltr_byrt": float(row.get("tltr_byrt", 0.0)),
                                "tltr_slrt": float(row.get("tltr_slrt", 0.0)),
                                "hour": row.get("pros_hour", "")
                            }
                            logger.info(f"[FX] 오늘 고시 전이므로 직전 고시환율({prev_date} 기준 {effective_rate:,.2f}원)을 사용합니다.")
                            return rate_info
                except Exception:
                    continue

        logger.warning(f"[FX] {stnd_date} 기준 {symbol} 고시환율 데이터를 찾을 수 없습니다.")
        return None

    def get_applied_rate(self, direction: str = "BUY", symbol: str = "USD") -> Optional[Dict[str, Any]]:
        """
        환전 적용환율(실제 고객 우대/스프레드가 반영된 견적) 조회
        :param direction: 'BUY' (원화->외화, 외화매수) 또는 'SELL' (외화->원화, 외화매도)
        :param symbol: 통화 코드 ('USD')
        :return: 적용환율, 기준시각, 스프레드, 할인율 등 견적 정보
        """
        mnec_clcd = "1" if direction.upper() in ("BUY", "1", "KRW_TO_USD") else "2"
        symbol = symbol.upper()
        try:
            data = self._call("fx_rates_applied", {"crcd": symbol, "mnec_clcd": mnec_clcd})
            if isinstance(data, list):
                data = data[0] if data else {}
            
            # 외화 매수는 tltr_aply_byrt, 외화 매도는 tltr_aply_slrt 가 실제 적용환율
            by_rate = float(data.get("tltr_aply_byrt", 0.0))
            sl_rate = float(data.get("tltr_aply_slrt", 0.0))
            effective_rate = by_rate if mnec_clcd == "1" else sl_rate

            quote = {
                "pros_date": data.get("pros_date", ""),
                "crcd": symbol,
                "direction": "외화매수(KRW→USD)" if mnec_clcd == "1" else "외화매도(USD→KRW)",
                "mnec_clcd": mnec_clcd,
                "applied_rate": effective_rate,
                "exrt_stnd_time": data.get("exrt_stnd_time", ""), # 환전 실행 시 필수 전달값
                "spread": float(data.get("spead", 0.0)),
                "dcrt": float(data.get("dcrt", 0.0)),             # 우대 할인율(%)
                "cust_grade": data.get("cust_grad_code_name", ""),
                "by_rate": by_rate,
                "sl_rate": sl_rate
            }
            logger.info(f"💱 [FX 견적] {symbol} {quote['direction']}: 적용환율 {effective_rate:,.4f}원 (기준시각: {quote['exrt_stnd_time']}, 우대율: {quote['dcrt']}%)")
            return quote
        except Exception as e:
            logger.error(f"[FX] 환전 적용환율 조회 오류: {e}")
            return None

    def execute_exchange(
        self,
        direction: str = "BUY",
        amount_usd: float = 0.0,
        amount_krw: float = 0.0,
        symbol: str = "USD",
        note: str = ""
    ) -> bool:
        """
        실시간 환전 실행 (자금 이동)
        :param direction: 'BUY' (원화 -> USD 외화매수) 또는 'SELL' (USD -> 원화 외화매도)
        :param amount_usd: 외화 기준 환전금액 (외화 기준이면 > 0, 원화 기준이면 0)
        :param amount_krw: 원화 기준 환전금액 (원화 기준이면 > 0, 외화 기준이면 0)
        :param symbol: 통화 코드 (기본 'USD')
        :param note: 비고 (예: 'CAVR US 매수 자금 충전')
        :return: 성공 여부
        """
        mnec_clcd = "1" if direction.upper() in ("BUY", "1", "KRW_TO_USD") else "2"
        symbol = symbol.upper()

        if amount_usd <= 0 and amount_krw <= 0:
            logger.error("❌ [FX] 환전 금액이 지정되지 않았습니다. (amount_usd 또는 amount_krw 필요)")
            return False

        # 1. 최신 적용환율 견적 조회
        quote = self.get_applied_rate(direction=direction, symbol=symbol)
        if not quote or not quote.get("exrt_stnd_time") or quote.get("applied_rate", 0) <= 0:
            if settings.MERITZ_READ_ONLY:
                logger.warning("⚠️ [FX] 실서버 견적 조회 실패 - READ_ONLY 모드이므로 모의 시뮬레이션 환율(1,420.0원)을 적용합니다.")
                now_str = datetime.now().strftime("%Y%m%d%H%M%S")
                quote = {
                    "applied_rate": 1420.0,
                    "exrt_stnd_time": now_str,
                    "spread": 0.0,
                    "dcrt": 100.0,
                    "direction": "모의환전"
                }
            else:
                logger.error("❌ [FX] 유효한 적용환율 견적을 가져오지 못해 환전을 중단합니다.")
                return False

        applied_rate = quote["applied_rate"]
        exrt_stnd_time = quote["exrt_stnd_time"]


        # 외화 금액 또는 원화 금액 산출
        if amount_usd > 0:
            frcr_amt = round(amount_usd, 3)
            wncr_amt = 0 # 외화 기준일 때는 0 전달
            est_krw = int(frcr_amt * applied_rate)
        else:
            wncr_amt = int(amount_krw)
            frcr_amt = 0 # 원화 기준일 때는 0 전달
            est_krw = wncr_amt

        dir_text = "원화 ➔ 외화(USD)" if mnec_clcd == "1" else "외화(USD) ➔ 원화"

        # 2. 안전장치 (MERITZ_READ_ONLY) 점검
        if settings.MERITZ_READ_ONLY:
            msg = (
                f"🛡️ [FX 모의 시뮬레이션 - READ_ONLY 활성화됨]\n"
                f"• 방향: {dir_text}\n"
                f"• 환율: {applied_rate:,.4f} KRW/USD\n"
                f"• 요청: 외화 ${amount_usd:,.2f} / 원화 {est_krw:,.0f}원\n"
                f"• 사유: {note or '안전 테스트'}\n"
                f"※ 실제 자금 이동은 수행되지 않았습니다."
            )
            logger.info(msg)
            send_telegram_message(msg)
            # 모의 기록 DB 저장
            now = datetime.now()
            log_forex_trade_db(
                trade_date=now.strftime("%Y%m%d"),
                trade_time=now.strftime("%H%M%S"),
                mnec_clcd=mnec_clcd,
                crcd=symbol,
                applied_rate=applied_rate,
                wncr_amt=est_krw,
                frcr_amt=amount_usd if amount_usd > 0 else (wncr_amt / applied_rate),
                fee=0.0,
                spread=quote.get("spread", 0.0),
                tr_srno=0,
                channel="SIMULATOR",
                note=f"[SIMULATION] {note}"
            )
            return True

        # 3. 실거래 환전 API 호출
        body = {
            "crcd": symbol,
            "mnec_clcd": mnec_clcd,
            "frcr_amt": frcr_amt,
            "wncr_amt": wncr_amt,
            "exrt_stnd_time": exrt_stnd_time,
            "iqry_exrt": f"{applied_rate:.4f}"
        }

        try:
            api_spec = self.cat.get("fx_exchanges")
            res = self.client.call(api_spec, body)
            if not res.get("ok"):
                err = f"❌ [FX 환전 실패] {res.get('error')}: {res.get('message')}"
                logger.error(err)
                send_telegram_message(err)
                return False

            res_data = (res.get("body", {}) or {}).get("data", {})
            real_tr_amt = float(res_data.get("tr_amt", est_krw))
            real_frcr_amt = float(res_data.get("frcr_tr_amt", amount_usd))
            real_rate = float(res_data.get("aply_exrt", applied_rate))
            tr_srno = int(res_data.get("tr_srno", 0))

            now = datetime.now()
            log_forex_trade_db(
                trade_date=now.strftime("%Y%m%d"),
                trade_time=now.strftime("%H%M%S"),
                mnec_clcd=mnec_clcd,
                crcd=symbol,
                applied_rate=real_rate,
                wncr_amt=real_tr_amt,
                frcr_amt=real_frcr_amt,
                fee=float(res_data.get("fee", 0.0)),
                spread=float(res_data.get("basc_spead", quote.get("spread", 0.0))),
                tr_srno=tr_srno,
                channel="120",
                note=note
            )

            success_msg = (
                f"✅ <b>[메리츠 환전 체결 완료]</b>\n"
                f"• 방향: <b>{dir_text}</b>\n"
                f"• 적용환율: <b>{real_rate:,.4f}원</b>\n"
                f"• 거래금액: 원화 {real_tr_amt:,.0f}원 ↔ 외화 ${real_frcr_amt:,.2f}\n"
                f"• 거래번호: #{tr_srno}\n"
                f"• 비고: {note or '정상 환전'}"
            )
            logger.info(success_msg)
            send_telegram_message(success_msg)
            return True

        except Exception as e:
            logger.error(f"❌ [FX 환전 예외 발생]: {e}")
            send_telegram_message(f"❌ [FX 환전 에러] {e}")
            return False

    def get_history(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """메리츠 서버에서 환전 체결 이력 조회 (fx_exchanges_history)"""
        try:
            data = self._call("fx_exchanges_history", {
                "iqry_sta_date": start_date,
                "iqry_fin_date": end_date
            })
            rows = data if isinstance(data, list) else [data]
            return rows
        except Exception as e:
            logger.error(f"[FX] 환전 내역 조회 오류: {e}")
            return []

    # ==========================================================================
    # CAVR 전략 연계 스마트 환전 기능
    # ==========================================================================

    def ensure_usd_balance(
        self,
        current_usd: float,
        required_usd: float,
        buffer_usd: float = 10.0,
        strategy_name: str = ""
    ) -> bool:
        """
        [CAVR 연계 - Auto Funding]
        미국 주식 매수 주문에 필요한 USD 잔고가 부족할 경우, 부족분만큼 원화에서 USD로 자동 환전
        :param current_usd: 현재 외화 예수금(USD)
        :param required_usd: 매수 주문 실행에 필요한 USD
        :param buffer_usd: 여유 버퍼 금액 ($10 기본)
        :param strategy_name: 전략명 (로깅용)
        """
        if current_usd >= required_usd:
            logger.info(f"💵 [FX Auto-Funding] USD 잔고 충분 (${current_usd:,.2f} >= 필요 ${required_usd:,.2f})")
            return True

        deficit_usd = (required_usd - current_usd) + buffer_usd
        deficit_usd = round(deficit_usd, 2)
        logger.info(
            f"🔄 [FX Auto-Funding] USD 부족 감지! (현재: ${current_usd:,.2f}, 필요: ${required_usd:,.2f}) ➔ ${deficit_usd:,.2f} 자동 환전 실행"
        )

        return self.execute_exchange(
            direction="BUY",
            amount_usd=deficit_usd,
            note=f"[Auto-Funding] {strategy_name} 매수 자금 자동 충전"
        )

    def harvest_usd_profit(
        self,
        sell_proceeds_usd: float,
        harvest_ratio: float = 1.0,
        strategy_name: str = ""
    ) -> bool:
        """
        [CAVR 연계 - Profit Harvesting]
        미국 주식 익절 매도 후 발생한 달러 대금을 원화로 자동 환전하여 수익 확정
        :param sell_proceeds_usd: 매도 체결 총 달러 금액
        :param harvest_ratio: 환전 비율 (0.0 ~ 1.0, 1.0은 100% 전액 환전)
        :param strategy_name: 전략명
        """
        if sell_proceeds_usd <= 0 or harvest_ratio <= 0:
            return True

        target_usd = round(sell_proceeds_usd * harvest_ratio, 2)
        if target_usd < 1.0:
            logger.debug(f"[FX Profit-Harvesting] 환전 금액이 너무 작음 (${target_usd})")
            return True

        logger.info(
            f"💰 [FX Profit-Harvesting] {strategy_name} 익절금 ${target_usd:,.2f} 원화로 자동 환전 실행 (비율: {harvest_ratio*100:.0f}%)"
        )

        return self.execute_exchange(
            direction="SELL",
            amount_usd=target_usd,
            note=f"[Profit-Harvesting] {strategy_name} 익절 수익 원화 회수"
        )


    def get_dxy_index(self) -> float:
        """달러 인덱스 (DXY) 실시간/최근 종가 조회 (야후 파이낸스)"""
        now = time.time()
        if now - self._dxy_cache[0] < 120.0 and self._dxy_cache[1] > 0:
            return self._dxy_cache[1]

        url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=5d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
                dxy = float(meta.get("regularMarketPrice", 0.0))
                if dxy > 50:
                    self._dxy_cache = (now, round(dxy, 2))
                    return round(dxy, 2)
        except Exception as e:
            logger.debug(f"[Forex] DXY 인덱스 수신 오류: {e}")

        # 캐시된 값 없으면 99.5 기본값
        return self._dxy_cache[1] if self._dxy_cache[1] > 0 else 99.5

    def get_3m_avg_rate(self, currency: str = "USD") -> float:
        """3개월(약 60영업일) 평균 환율 산출 (야후 파이낸스)"""
        currency = currency.upper()
        now = time.time()
        if currency in self._3m_avg_cache:
            cache_time, val = self._3m_avg_cache[currency]
            if now - cache_time < 300.0:  # 5분 캐시
                return val

        symbol = "KRW=X" if currency == "USD" else "JPYKRW=X"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                closes = data["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
                valid_closes = [c for c in closes if c is not None and c > 0]
                if valid_closes:
                    avg_val = sum(valid_closes) / len(valid_closes)
                    if currency == "JPY" and avg_val < 50.0:
                        avg_val *= 100.0
                    avg_res = round(avg_val, 2)
                    self._3m_avg_cache[currency] = (now, avg_res)
                    return avg_res
        except Exception as e:
            logger.debug(f"[Forex] 3개월 평균 환율 조회 오류: {e}")

        # Fallback: 현재 환율 기준으로 근사치 반환
        cur_info = self.get_market_rate(currency)
        base = cur_info.get("effective_rate", 1380.0 if currency == "USD" else 910.0) if cur_info else 1380.0
        return round(float(base), 2)

    def get_account_balances(self) -> dict:
        """
        메리츠 계좌 실시간 가용 예수금(KRW, USD) 조회
        """
        krw_cash = 0.0
        usd_cash = 0.0
        total_asset = 0.0
        source = "API"

        try:
            from core.brokers.meritz_kr import MeritzKrBroker
            kb = MeritzKrBroker()
            krw_cash = float(kb.get_cash_pool() or 0.0)
        except Exception as e:
            logger.debug(f"[ForexManager] KRW 예수금 조회 예외: {e}")

        try:
            from core.brokers.meritz_us import MeritzUsBroker
            ub = MeritzUsBroker()
            usd_cash = float(ub.get_cash_pool() or 0.0)
        except Exception as e:
            logger.debug(f"[ForexManager] USD 예수금 조회 예외: {e}")

        # 자산평가 데이터 연동 시도
        try:
            from dashboard import fetch_meritz_account_data
            val_data, _ = fetch_meritz_account_data(force=False)
            if val_data:
                frcr_eval = float(val_data.get("frcr_tfam", 0.0))
                if krw_cash <= 0:
                    krw_cash = float(val_data.get("tfam", 0.0))
                if usd_cash <= 0 and frcr_eval > 0:
                    r_info = self.get_market_rate("USD")
                    r_val = float(r_info.get("effective_rate", 1380.0)) if r_info else 1380.0
                    if r_val > 0:
                        usd_cash = round(frcr_eval / r_val, 2)
                total_asset = float(val_data.get("tot_aset_amt", 0.0))
                if total_asset <= 0:
                    total_asset = krw_cash + frcr_eval
        except Exception:
            pass

        if total_asset <= 0:
            rate_info = self.get_market_rate("USD")
            r = float(rate_info.get("effective_rate", 1380.0)) if rate_info else 1380.0
            total_asset = krw_cash + (usd_cash * r)

        return {
            "KRW": krw_cash,
            "USD": usd_cash,
            "total_asset": total_asset,
            "source": source
        }


# =============================================================================
# 4. 외환 조건부 분할 자동매매 엔진 (Forex DCA & Scalping)
# =============================================================================

class ForexDcaEngine:
    """
    환전 조건부 자동매매 (Dollar Cost Averaging & Scalping Engine)
    - 진입 조건: 3개월 평균 환율 대비 낮을 때 or 달러인덱스(DXY) 기준치(예: 98 이하) 이하 or 지정 목표환율 이하
    - 분할 매수: 진입 후 직전 매수가 대비 -0.5% 하락할 때마다 일정 금액씩 추가 환전 매수 (최대 N회차)
    - 분할 매도: 평균 매수 환율 대비 +1.0% ~ +3.0% 상승 시 33%씩 순차 분할 매도 (SPLIT_3) 또는 목표 수익률 도달 시 일괄 전액 매도 (FULL_TARGET)
    """

    STRATEGY_ID = "FOREX_DCA_DEFAULT"

    def __init__(self, manager: Optional[MeritzForexManager] = None):
        self.mgr = manager or forex_manager

    def load_state(self) -> dict:
        return load_forex_strategy_state_db(self.STRATEGY_ID)

    def save_state(self, state: dict) -> bool:
        return save_forex_strategy_state_db(self.STRATEGY_ID, state)

    def evaluate_tick(self, check_time: bool = True) -> dict:
        """
        스케줄러 주기 작업에서 호출하는 외환 DCA 조건 평가 및 자동 매매 트리거
        :param check_time: True인 경우 메리츠 실시간 환전 가능 시간(영업일 09:00~익일 02:00, 점검시간 제외) 여부 확인
        """
        state = self.load_state()
        if not state.get("is_active", False):
            return {"action": "NONE", "reason": "STRATEGY_INACTIVE", "state": state}

        if check_time:
            is_avail, fx_reason = is_forex_available_time()
            if not is_avail:
                return {"action": "NONE", "reason": f"FOREX_CLOSED ({fx_reason})", "state": state}

        currency = state.get("currency", "USD").upper()
        market_info = self.mgr.get_market_rate(currency)
        if not market_info:
            return {"action": "NONE", "reason": "RATE_NOT_AVAILABLE", "state": state}

        cur_rate = float(market_info.get("effective_rate") or market_info.get("stnd_exrt") or 0.0)
        if cur_rate <= 0:
            return {"action": "NONE", "reason": "INVALID_RATE", "state": state}

        entry_type = state.get("entry_condition_type", "3M_AVG")
        benchmark_target = float(state.get("target_benchmark_val", 98.0))
        drop_step_pct = float(state.get("drop_buy_step_pct", 0.5))
        buy_unit = float(state.get("buy_unit_amount", 100.0))
        max_rounds = int(state.get("max_buy_rounds", 10))
        cur_round = int(state.get("current_round", 0))
        tot_fiat = float(state.get("total_fiat_bought", 0.0))
        tot_krw = float(state.get("total_krw_spent", 0.0))
        avg_buy_rate = float(state.get("avg_buy_rate", 0.0))
        last_buy_rate = float(state.get("last_buy_rate", 0.0))
        sell_strat = state.get("sell_strategy_type", "SPLIT_3")
        target_profit_pct = float(state.get("target_sell_profit_pct", 1.5))
        sell_stage = int(state.get("sell_stage", 0))

        # -------------------------------------------------------------
        # A. 매도 (익절) 조건 평가 (보유 외화가 있는 경우)
        # -------------------------------------------------------------
        if tot_fiat > 0 and avg_buy_rate > 0:
            profit_pct = ((cur_rate - avg_buy_rate) / avg_buy_rate) * 100.0

            # 1) 3분할 매도 (1%, 2%, 3% 상승 시 각각 약 33% 매도)
            if sell_strat == "SPLIT_3":
                if profit_pct >= 3.0 and sell_stage == 2:
                    sell_amt = tot_fiat  # 잔여 전액 매도
                    note = f"[Forex DCA 3단계 전액 익절] 수익률 +{profit_pct:.2f}% 도달"
                    ok = self.mgr.execute_exchange("SELL", amount_usd=sell_amt, note=note)
                    if ok:
                        state["total_fiat_bought"] = 0.0
                        state["total_krw_spent"] = 0.0
                        state["current_round"] = 0
                        state["avg_buy_rate"] = 0.0
                        state["last_buy_rate"] = 0.0
                        state["sell_stage"] = 0
                        state["status"] = "ALL_PROFIT_TAKEN"
                        self.save_state(state)
                        return {"action": "SELL", "stage": 3, "profit_pct": profit_pct, "amount": sell_amt}

                elif profit_pct >= 2.0 and sell_stage == 1:
                    sell_amt = round(tot_fiat * 0.5, 2)  # 남은 66% 중 절반 (원래의 33%)
                    note = f"[Forex DCA 2단계 33% 익절] 수익률 +{profit_pct:.2f}% 도달"
                    ok = self.mgr.execute_exchange("SELL", amount_usd=sell_amt, note=note)
                    if ok:
                        state["total_fiat_bought"] = round(tot_fiat - sell_amt, 2)
                        state["sell_stage"] = 2
                        state["status"] = "PROFIT_STAGE_2"
                        self.save_state(state)
                        return {"action": "SELL", "stage": 2, "profit_pct": profit_pct, "amount": sell_amt}

                elif profit_pct >= 1.0 and sell_stage == 0:
                    sell_amt = round(tot_fiat * 0.33, 2)
                    note = f"[Forex DCA 1단계 33% 익절] 수익률 +{profit_pct:.2f}% 도달"
                    ok = self.mgr.execute_exchange("SELL", amount_usd=sell_amt, note=note)
                    if ok:
                        state["total_fiat_bought"] = round(tot_fiat - sell_amt, 2)
                        state["sell_stage"] = 1
                        state["status"] = "PROFIT_STAGE_1"
                        self.save_state(state)
                        return {"action": "SELL", "stage": 1, "profit_pct": profit_pct, "amount": sell_amt}

            # 2) 전액 일괄 매도 (FULL_TARGET)
            elif sell_strat == "FULL_TARGET":
                if profit_pct >= target_profit_pct:
                    sell_amt = tot_fiat
                    note = f"[Forex DCA 목표 전액 익절] 수익률 +{profit_pct:.2f}% 도달 (목표: {target_profit_pct}%)"
                    ok = self.mgr.execute_exchange("SELL", amount_usd=sell_amt, note=note)
                    if ok:
                        state["total_fiat_bought"] = 0.0
                        state["total_krw_spent"] = 0.0
                        state["current_round"] = 0
                        state["avg_buy_rate"] = 0.0
                        state["last_buy_rate"] = 0.0
                        state["sell_stage"] = 0
                        state["status"] = "ALL_PROFIT_TAKEN"
                        self.save_state(state)
                        return {"action": "SELL", "stage": "FULL", "profit_pct": profit_pct, "amount": sell_amt}

        # -------------------------------------------------------------
        # B. 매수 조건 평가 (분할 회차 여유가 있는 경우)
        # -------------------------------------------------------------
        if cur_round < max_rounds:
            trigger_buy = False
            buy_reason = ""

            # 1) 최초 1회차 진입 조건
            if cur_round == 0:
                if entry_type == "3M_AVG":
                    avg_3m = self.mgr.get_3m_avg_rate(currency)
                    if cur_rate <= avg_3m:
                        trigger_buy = True
                        buy_reason = f"3개월 평균 환율({avg_3m:,.2f}원) 이하 진입 (현재: {cur_rate:,.2f}원)"
                elif entry_type == "DXY_BELOW":
                    dxy = self.mgr.get_dxy_index()
                    if dxy <= benchmark_target:
                        trigger_buy = True
                        buy_reason = f"달러인덱스({dxy:.2f}) 기준치({benchmark_target:.2f}) 이하 진입"
                elif entry_type == "MANUAL_TARGET":
                    if cur_rate <= benchmark_target:
                        trigger_buy = True
                        buy_reason = f"지정 목표환율({benchmark_target:,.2f}원) 이하 진입 (현재: {cur_rate:,.2f}원)"

            # 2) 2회차 이후 추가 매수: 직전 매수가 대비 drop_buy_step_pct(기본 0.5%) 하락 시
            else:
                if last_buy_rate > 0:
                    drop_from_last = ((cur_rate - last_buy_rate) / last_buy_rate) * 100.0
                    if drop_from_last <= -drop_step_pct:
                        trigger_buy = True
                        buy_reason = f"직전 체결가({last_buy_rate:,.2f}원) 대비 {drop_from_last:.2f}% 하락 (기준: -{drop_step_pct}%)"

            if trigger_buy:
                note = f"[Forex DCA {cur_round+1}회차 분할매수] {buy_reason}"
                ok = self.mgr.execute_exchange("BUY", amount_usd=buy_unit, note=note)
                if ok:
                    quote = self.mgr.get_applied_rate("BUY", currency)
                    applied_p = float(quote.get("applied_rate", cur_rate)) if quote else cur_rate
                    cost_krw = int(buy_unit * applied_p)

                    new_tot_fiat = round(tot_fiat + buy_unit, 2)
                    new_tot_krw = tot_krw + cost_krw
                    new_avg = round((new_tot_krw / new_tot_fiat), 2)

                    state["current_round"] = cur_round + 1
                    state["total_fiat_bought"] = new_tot_fiat
                    state["total_krw_spent"] = new_tot_krw
                    state["avg_buy_rate"] = new_avg
                    state["last_buy_rate"] = applied_p
                    state["sell_stage"] = 0
                    state["status"] = f"ROUND_{cur_round+1}_BOUGHT"
                    self.save_state(state)
                    return {"action": "BUY", "round": cur_round + 1, "rate": applied_p, "amount": buy_unit}

        return {"action": "NONE", "reason": "CONDITIONS_NOT_MET", "state": state}


# 싱글톤 인스턴스 제공
forex_manager = MeritzForexManager()
forex_dca_engine = ForexDcaEngine(forex_manager)


