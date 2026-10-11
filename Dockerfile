FROM python:3.12-slim

# 시간대 및 로케일 설정
ENV TZ=Asia/Seoul
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# open-api 패키지 설치 (SDK 등록)
RUN pip install --no-cache-dir -e ./open-api

# 데이터 및 로그 디렉터리 생성 보장
RUN mkdir -p /app/data /app/logs /app/env

# 포트 설정 (대시보드 웹 UI용 기본 8501)
EXPOSE 8501

# 기본 실행 명령 (단독 컨테이너 실행 시 대시보드 구동, docker-compose에서 override 가능)
CMD ["python", "test_meritz_setup.py"]
