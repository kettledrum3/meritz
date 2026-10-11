"""Meritz Open API 환율 조회 및 환전 관리 모듈 (MeritzForexManager)

- 고시환율 조회: GET /forex/v1/rates (fx_rates)
- 환전 적용환율 조회: GET /forex/v1/rates/applied (fx_rates_applied)
- 실시간 환전신청: POST /forex/v1/exchanges (fx_exchanges)
- 환전 내역 조회: GET /forex/v1/exchanges/history (fx_exchanges_history)
- CAVR 연계 스마트 환전 지원 (USD 부족 시 자동 충전, 익절 달러 원화 회수)
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Tuple

# open-api 패키지 경로 추가
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
OPEN_API_DIR = PROJECT_ROOT / "open-api"
if str(OPEN_API_DIR) not in sys.path:
    sys.path.insert(0, str(OPEN_API_DIR))

try:
    from meritz import client, load_catalog, MeritzError
except ImportError:
    client = None
    load_catalog = None
    MeritzError = Exception

from config.settings import settings
from core.database import log_forex_trade_db, get_forex_history_db, save_exchange_rate_db
from core.notifier import send_telegram_message

logger = logging.getLogger(__name__)


class MeritzForexManager:
    """메리츠증권 외환(FX) 및 환전 통합 관리자"""

    def __init__(self):
        if client is None or load_catalog is None:
            raise ImportError(
                "meritz 패키지를 불러올 수 없습니다. 'pip install -e open-api' 또는 경로를 확인하세요."
            )
        self.cat = load_catalog()
        self.client = client()
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

    def get_market_rate(self, symbol: str = "USD", target_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        고시환율 조회 (기본: 오늘 일자, USD)
        :param symbol: 통화 코드 (대문자 3자리, 기본 'USD')
        :param target_date: 조회일자 YYYYMMDD (None이면 오늘)
        :return: 기준환율, 전신환 매도/매입환율, 매매기준환율 등 딕셔너리
        """
        stnd_date = target_date or datetime.now().strftime("%Y%m%d")
        symbol = symbol.upper()
        try:
            data = self._call("fx_rates", {"stnd_date": stnd_date, "crcd": symbol})
            rows = data if isinstance(data, list) else [data]
            for row in rows:
                if row.get("crcd") == symbol:
                    rate_info = {
                        "date": row.get("tr_date", stnd_date),
                        "crcd": symbol,
                        "name": row.get("crcd_kor_name", "미국 달러"),
                        "stnd_exrt": float(row.get("stnd_exrt", 0.0)),         # 기준환율
                        "deal_stnd_exrt": float(row.get("deal_stnd_exrt", 0.0)), # 매매기준환율
                        "tltr_byrt": float(row.get("tltr_byrt", 0.0)),         # 전신환 매입율
                        "tltr_slrt": float(row.get("tltr_slrt", 0.0)),         # 전신환 매도율
                        "hour": row.get("pros_hour", "")
                    }
                    # DB exchange_rates 테이블에도 기록 (CAVR 환율 추적용)
                    if symbol == "USD" and rate_info["deal_stnd_exrt"] > 0:
                        save_exchange_rate_db(
                            trade_date=rate_info["date"],
                            recorded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            rate=rate_info["deal_stnd_exrt"],
                            base_rate=rate_info["stnd_exrt"],
                            diff=0.0,
                            pct=0.0,
                            source="MERITZ"
                        )
                    return rate_info
            logger.warning(f"[FX] {stnd_date} 기준 {symbol} 고시환율 데이터가 없습니다.")
        except Exception as e:
            logger.error(f"[FX] 고시환율 조회 중 오류: {e}")
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


# 싱글톤 인스턴스 제공
forex_manager = MeritzForexManager()

