from typing import Tuple, List, Literal, Optional
import math

class Broker:
    """증권사 API 공통 추상 베이스 클래스 (Kiwoom / Meritz 호환)"""

    def get_price(self, symbol: str) -> float:
        """현재가 조회"""
        raise NotImplementedError
        
    def get_previous_close(self, symbol: str) -> float:
        """전일 종가 조회"""
        raise NotImplementedError

    def get_last_5_day_avg_close(self, symbol: str) -> float:
        """직전 5거래일의 종가 평균을 반환합니다."""
        raise NotImplementedError

    def get_current_high(self, symbol: str) -> float:
        """당일 고가 조회"""
        raise NotImplementedError

    def get_current_low(self, symbol: str) -> float:
        """당일 저가 조회"""
        raise NotImplementedError
    
    def get_account_equity(self, symbol: str) -> Tuple[float, float, float]:
        """계좌 자산 및 보유 수량 조회: (shares, avg_price, eval_amt) 반환"""
        raise NotImplementedError
    
    def get_cash_pool(self) -> float:
        """예수금(주문 가능 현금) 조회"""
        raise NotImplementedError

    def adjust_price_by_tick(self, symbol: str, price: float, order_type: Literal["BUY", "SELL"]) -> float:
        """호가 단위에 맞게 가격 보정 (기본값은 미국 호가 단위 기준: 매수 올림, 매도 버림, 부동소수점 오차 방어)"""
        if price <= 0:
            return 0.0
        scaled = round(price * 100.0, 6)
        if order_type == "BUY":
            return math.ceil(scaled) / 100.0
        else:
            return math.floor(scaled) / 100.0
        
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
        """주문 실행 (지정가/시장가)"""
        raise NotImplementedError

    def fetch_open_orders(self, symbol: str) -> List[dict]:
        """미체결 주문 내역 조회"""
        raise NotImplementedError

    def fetch_execution_history(self, symbol: str, start_date: str, end_date: str) -> List[dict]:
        """체결 내역 조회"""
        raise NotImplementedError
