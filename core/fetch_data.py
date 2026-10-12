import os
import sys
import time
import pandas as pd
import logging
from datetime import datetime

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CORE_DIR)

from core.brokers.meritz_kr import MeritzKrBroker
from core.brokers.meritz_us import MeritzUsBroker

def update_ticker_data(ticker, days=300, market="US"):
    """특정 티커의 데이터를 수집하여 CSV로 저장하는 헬퍼 함수"""
    logging.info(f"[{ticker}] {market} 과거 데이터 조회 시도...")
    
    try:
        if market == "KR":
            broker = MeritzKrBroker()
            history = broker.fetch_daily_chart(ticker, days=days)
        else:
            broker = MeritzUsBroker()
            history = broker.fetch_daily_chart(ticker, days=days)
            
        if history:
            df = pd.DataFrame(history)
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date', ascending=False).reset_index(drop=True)
            
            data_dir = os.path.join(BASE_DIR, "data")
            os.makedirs(data_dir, exist_ok=True)
            save_path = os.path.join(data_dir, f"{ticker}.csv")
            df.to_csv(save_path, index=False)
            return True, f"{ticker} 데이터 {len(df)}건 저장 완료 ({save_path})"
        else:
            return False, f"{ticker} 데이터 수집 실패 (조회된 결과가 없습니다)"
    except Exception as e:
        logging.error(f"[Fetch Error] {ticker} ({market}): {e}")
        return False, str(e)
