import smtplib
import os
import logging
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timedelta
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 공통 환경 변수 로드
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, "env", ".env"))

def send_email(subject: str, content_or_msg_object: str | MIMEMultipart):
    """Zoho SMTP를 이용한 이메일 발송 공통 함수"""
    smtp_host = os.getenv("ZOHO_SMTP_SERVER")
    smtp_port = int(os.getenv("ZOHO_SMTP_PORT", "465"))
    smtp_user = os.getenv("ZOHO_SMTP_USER")
    smtp_pass = os.getenv("ZOHO_SMTP_PASSWORD")
    sender = os.getenv("ZOHO_SMTP_USER")
    receiver = os.getenv("ZOHO_RECEIVER_EMAIL") or smtp_user

    if not all([smtp_user, smtp_pass, receiver]):
        logger.warning("[Email] SMTP 설정이 누락되어 이메일 발송을 건너뜁니다.")
        return False

    if isinstance(content_or_msg_object, MIMEMultipart):
        msg = content_or_msg_object
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = receiver
    else:
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = receiver
        msg.attach(MIMEText(content_or_msg_object, 'html', 'utf-8'))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender, receiver, msg.as_string())
        logger.info(f"[Email] 이메일 발송 성공: {subject}")
        return True
    except Exception as e:
        logger.error(f"[Email] 이메일 발송 실패: {e}")
        return False
