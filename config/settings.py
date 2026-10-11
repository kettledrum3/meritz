import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 디렉터리
BASE_DIR = Path(__file__).resolve().parent.parent

# env/.env 파일 로드
env_file = BASE_DIR / "env" / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file)
else:
    fallback_env = BASE_DIR / "open-api" / ".env"
    if fallback_env.exists():
        load_dotenv(dotenv_path=fallback_env)

def load_market_env(market: str = "KR") -> dict:
    """시장별(.env.kr, .env.us) 설정 로드 및 환경변수 반영"""
    suffix = market.lower()
    m_path = BASE_DIR / "env" / f".env.{suffix}"
    if m_path.exists():
        load_dotenv(dotenv_path=m_path, override=True)
    return {
        "MARKET_TYPE": os.getenv("MARKET_TYPE", market.upper()),
        "ticker": os.getenv("ticker", "122630" if market.upper() == "KR" else "SOXL"),
        "initial_cash": float(os.getenv("initial_cash", 10000000 if market.upper() == "KR" else 10000.0)),
        "fee_rate": float(os.getenv("fee_rate", 0.0)),
        "tax_sell": float(os.getenv("tax_sell", 0.0020 if market.upper() == "KR" else 0.0000206)),
        "T_default": int(os.getenv("T_default", 40)),
        "a_default": int(os.getenv("a_default", 40)),
        "T_profit": float(os.getenv("T_profit", 0.10 if market.upper() == "KR" else 0.15)),
        "quarter_loss_stop": os.getenv("quarter_loss_stop", "FALSE").upper() == "TRUE"
    }

class Settings:
    # 메리츠 자격증명
    MERITZ_APP_KEY: str = os.getenv("MERITZ_APP_KEY", "")
    MERITZ_APP_SECRET: str = os.getenv("MERITZ_APP_SECRET", "")
    MERITZ_BASE_URL: str = os.getenv("MERITZ_BASE_URL", "https://openapi.imeritz.com:9443")
    MERITZ_WS_URL: str = os.getenv("MERITZ_WS_URL", "wss://openapi.imeritz.com:29443/websocket")
    MERITZ_READ_ONLY: bool = os.getenv("MERITZ_READ_ONLY", "1") == "1"
    MERITZ_TIMEOUT: int = int(os.getenv("MERITZ_TIMEOUT", "15"))

    # 계좌 및 전략 설정
    ACCOUNT_NO: str = os.getenv("ACCOUNT_NO", "")
    DEFAULT_MARKET: str = os.getenv("DEFAULT_MARKET", "KR")
    TARGET_SYMBOL: str = os.getenv("TARGET_SYMBOL", "122630")

    # 경로 설정
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"
    DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/cavr.db")

    # 알림 설정
    NOTIFIER_ENABLED: bool = os.getenv("NOTIFIER_ENABLED", "false").lower() == "true"
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # 환전(FX) 관련 설정
    FX_AUTO_EXCHANGE: bool = os.getenv("FX_AUTO_EXCHANGE", "false").lower() == "true"
    FX_TARGET_CURRENCY: str = os.getenv("FX_TARGET_CURRENCY", "USD")
    FX_BUFFER_USD: float = float(os.getenv("FX_BUFFER_USD", "100.0"))

# 디렉터리 자동 생성 보장
Settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
Settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)

settings = Settings()

