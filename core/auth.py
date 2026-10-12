import hashlib
import random
import os
import re
import time
from datetime import datetime
import logging
from dotenv import load_dotenv
from core.database import get_connection, set_config, get_config
from core.email_service import send_email

logger = logging.getLogger(__name__)

# 공통 환경 변수 로드
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, "env", ".env"))

def hash_password(password, salt="cavr_system_salt"):
    """Salt를 포함한 비밀번호 해싱"""
    salted = password + salt
    return hashlib.sha256(salted.encode()).hexdigest()

def validate_password_complexity(password):
    """
    비밀번호 복잡도 검사 (Regex)
    - 최소 8자 이상
    - 영문, 숫자, 특수문자 조합 확인
    """
    if len(password) < 8:
        return False, "비밀번호는 최소 8자 이상이어야 합니다."
    
    if not re.search(r"[a-zA-Z]", password):
        return False, "비밀번호에 영문자가 포함되어야 합니다."
        
    if not re.search(r"\d", password):
        return False, "비밀번호에 숫자가 포함되어야 합니다."
        
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "비밀번호에 특수문자가 포함되어야 합니다."
        
    return True, "OK"

def register_user(username, email):
    """사용자 신규 등록 (OTP 발송 및 임시 비번 설정)"""
    conn = get_connection()
    cursor = conn.cursor()
    otp = str(random.randint(100000, 999999))

    try:
        pw_hash = hash_password(otp)
        cursor.execute('''
            INSERT INTO user_auth (username, email, password_hash, is_verified, is_temp_password)
            VALUES (?, ?, ?, 1, 1)
        ''', (username, email, pw_hash))
        conn.commit()
        
        subject = "[메리츠CAVR] 회원가입을 위한 임시 비밀번호입니다."
        content = f"<h3>안녕하세요, <b>{username}</b>님.</h3><p>귀하의 메리츠CAVR 자동매매 시스템 계정의 회원가입을 위한 임시 비밀번호는 아래와 같습니다.</p><h3>임시 비밀번호: <b style='color:blue;'>{otp}</b></h3><p>로그인 후 즉시 비밀번호를 변경해주세요.</p>"
        send_email(subject, content)
        return True
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        return False
    finally:
        conn.close()

def check_login(username_input, password):
    """로그인 자격 증명 확인"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT email, username, password_hash, failed_attempts, is_temp_password FROM user_auth WHERE username=?', (username_input,))
    user = cursor.fetchone()

    if user:
        email, username, stored_hash, failed_count, is_temp = user
        if stored_hash == hash_password(password):
            cursor.execute('UPDATE user_auth SET failed_attempts=0 WHERE email=?', (email,))
            conn.commit()
            conn.close()
            return {"status": "success", "username": username, "email": email, "is_temp": bool(is_temp)}
        else:
            new_failed = failed_count + 1
            if new_failed >= 5:
                conn.close()
                reset_password_request(email)
                return {"status": "locked", "msg": "비밀번호 5회 오류로 인해 임시 비밀번호가 메일로 발송되었습니다."}
            
            cursor.execute('UPDATE user_auth SET failed_attempts=? WHERE email=?', (new_failed, email))
            conn.commit()
            conn.close()
            return {"status": "fail", "msg": f"비밀번호가 틀렸습니다. ({new_failed}/5)"}
    
    conn.close()
    return None

def reset_password_request(email):
    """비밀번호 재설정 요청 (OTP 발송)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM user_auth WHERE email=?', (email,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    username = row[0]
    
    otp = str(random.randint(100000, 999999))
    pw_hash = hash_password(otp)
    cursor.execute('UPDATE user_auth SET password_hash=?, is_temp_password=1, failed_attempts=0 WHERE email=?', (pw_hash, email))
    conn.commit()
    conn.close()
    
    subject = "[메리츠CAVR] 비밀번호 재설정을 위한 임시 비밀번호입니다."
    content = f"<h3>안녕하세요, <b>{username}</b>님.</h3><p>귀하의 메리츠CAVR 자동매매 시스템 계정의 비밀번호 재설정을 위한 임시 비밀번호는 아래와 같습니다.</p><h3>임시 비밀번호: <b style='color:red;'>{otp}</b></h3><p>보안을 위해 로그인 후 바로 변경해주세요.</p>"
    return send_email(subject, content)

def update_password(email, new_password):
    """사용자 비밀번호 실제 변경 (복잡도 검증 포함)"""
    is_valid, msg = validate_password_complexity(new_password)
    if not is_valid:
        logger.warning(f"Password complexity check failed for {email}: {msg}")
        return False, msg

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT username FROM user_auth WHERE email=?', (email,))
        row = cursor.fetchone()
        username = row[0] if row else "고객"

        new_hash = hash_password(new_password)
        cursor.execute('UPDATE user_auth SET password_hash=?, is_temp_password=0 WHERE email=?', (new_hash, email))
        conn.commit()

        subject = "[메리츠CAVR] 비밀번호가 성공적으로 변경되었습니다."
        content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
            <h2 style="color: #2e6c80;">🔐 비밀번호 변경 완료</h2>
            <p>안녕하세요, <b>{username}</b>님.</p>
            <p>귀하의 <b>메리츠CAVR 자동매매 시스템</b> 계정({email})의 비밀번호가 성공적으로 변경되었습니다.</p>
            <p style="background-color: #f9f9f9; padding: 15px; border-left: 5px solid #2e6c80;">
                <b>변경 일시:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (KST)
            </p>
            <p>만약 본인이 비밀번호를 변경하지 않았다면, 계정 보안을 위해 즉시 비밀번호 재설정을 진행하거나 관리자에게 문의해 주세요.</p>
            <br>
            <hr>
            <p style="font-size: 12px; color: #888;">본 메일은 보안 알림을 위해 시스템에서 자동 발송되었습니다.</p>
        </div>
        """
        send_email(subject, content)

        return True, "비밀번호가 성공적으로 변경되었습니다."
    except Exception as e:
        logger.error(f"Password update failed: {e}")
        return False, f"오류 발생: {str(e)}"
    finally:
        conn.close()

def generate_otp(email):
    """6자리 OTP 생성 및 이메일 발송"""
    otp = str(random.randint(100000, 999999))
    expires_at = int(time.time()) + 600
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO otp_codes (email, code, expires_at) VALUES (?, ?, ?)", 
                   (email, otp, expires_at))
    conn.commit()
    conn.close()
    
    subject = "[메리츠CAVR] 본인 확인을 위한 인증번호입니다."
    content = f"<h3>인증번호: <b style='color:blue;'>{otp}</b></h3><p>10분 이내에 입력해 주세요.</p>"
    return send_email(subject, content)

def verify_otp(email, input_code):
    """OTP 검증"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, expires_at FROM otp_codes WHERE email=?", (email,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        code, expires = row
        if code == input_code and int(time.time()) < expires:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE user_auth SET is_verified=1 WHERE email=?", (email,))
            conn.commit()
            conn.close()
            return True
    return False

def update_user_email(old_email, new_email):
    """사용자 이메일 변경"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE user_auth SET email=?, is_verified=0 WHERE email=?", (new_email, old_email))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Email update failed: {e}")
        return False
    finally:
        conn.close()

def save_ip_session(ip: str, username: str, email: str):
    """클라이언트 IP 기반 세션 저장"""
    if not ip:
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO ip_auth_sessions (ip, username, email, last_login, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(ip) DO UPDATE SET
                username=excluded.username,
                email=excluded.email,
                last_login=excluded.last_login,
                is_active=1
        """, (ip, username, email, now_str))
        conn.commit()
        conn.close()
        logger.info(f"🔑 [Auth] IP 세션 저장 완료: {ip} -> {username} ({email})")
    except Exception as e:
        logger.error(f"Failed to save IP session for {ip}: {e}")

def get_ip_session(ip: str) -> dict:
    """IP 기반 활성 세션 조회"""
    if not ip:
        return None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, email, last_login, is_active
            FROM ip_auth_sessions
            WHERE ip = ? AND is_active = 1
        """, (ip,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "username": row[0],
                "email": row[1],
                "last_login": row[2]
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get IP session for {ip}: {e}")
        return None

def clear_ip_session(ip: str):
    """로그아웃 시 IP 세션 비활성화"""
    if not ip:
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE ip_auth_sessions SET is_active=0 WHERE ip=?", (ip,))
        conn.commit()
        conn.close()
        logger.info(f"🔒 [Auth] IP 세션 비활성화 완료 (로그아웃): {ip}")
    except Exception as e:
        logger.error(f"Failed to clear IP session for {ip}: {e}")
