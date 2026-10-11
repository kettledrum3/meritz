import os
import requests
import logging
import re
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 프로젝트 루트 및 환경변수 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / "env" / ".env"
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)

def send_telegram_message(message: str) -> bool:
    """
    메리츠 전용 텔레그램 알림 메시지 발송 함수
    - HTML 태그 파싱 지원
    - 환경변수 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 사용
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.debug("[Notifier] 텔레그램 토큰 또는 Chat ID가 설정되지 않아 발송을 건너뜁니다.")
        return False

    clean_msg = re.sub(r'<[^<]+?>', '', message).replace('\n', ' ')
    logger.info(f"[TG_SEND] {clean_msg}")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            logger.error(f"Telegram API Error ({response.status_code}): {response.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram 메시지 발송 실패: {e}")
        return False
