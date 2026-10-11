import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

def clean_symbol(symbol: str) -> str:
    """종목코드에서 접두사 'A' 등을 제거한 순수 코드 반환 (국내: '005930', 미국: 'SOXL')"""
    if not symbol:
        return ""
    symbol = symbol.strip().upper()
    if len(symbol) == 7 and symbol.startswith("A") and symbol[1:].isalnum():
        return symbol[1:]
    return symbol

def get_ticker_name(symbol: str, market: str = "KR") -> str:
    """종목 코드에 해당하는 한글/영문 이름을 반환 (env/ETF_list_*.txt 참조)"""
    symbol_clean = clean_symbol(symbol)
    try:
        env_suffix = market.lower()
        file_name = f"ETF_list_{env_suffix}.txt"
        file_path = BASE_DIR / "env" / file_name
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.split("#")[0].strip()
                    if line:
                        parts = line.split(None, 1)
                        if clean_symbol(parts[0]) == symbol_clean:
                            return parts[1].strip().strip('"') if len(parts) > 1 else symbol_clean
    except Exception as e:
        logger.debug(f"종목명 조회 오류 ({symbol}): {e}")
    return symbol_clean

def format_symbol_display(symbol: str, market: str = "KR") -> str:
    """종목 코드와 이름을 '코드 (종목명)' 형식으로 반환"""
    name = get_ticker_name(symbol, market)
    symbol_clean = clean_symbol(symbol)
    if name != symbol_clean:
        return f"{symbol_clean} ({name})"
    return symbol_clean
