# Meritz Open API CAVR 자동매매 및 스마트 환전 시스템

**Meritz CAVR**은 메리츠증권(Meritz Securities)의 최신 Open API(REST & WebSocket)를 활용하여 **국내(KR) 및 미국(US) 주식 시장**에서 알고리즘 기반 자동매매를 실행하는 통합 시스템입니다.  
라오어의 **무한매수법(Cost Averaging - CA)**과 **밸류 리밸런싱(Value Rebalancing - VR)** 전략을 자동화하고, 메리츠 Open API의 강점인 **실시간 외환(FX) 고시환율 조회 및 즉시 환전 기능**을 결합하여 환율 리스크 관리와 외화 자동 충전을 원스톱으로 지원합니다.

---

## 🌟 주요 특징 및 차별점 (Key Features)

### 1. 무한매수법 V2.2 & V4.0 (Cost Averaging)
* **분할 매수 및 평단 관리**: 자본금을 $a$분할(기본 40분할)하여 매일 LOC/지정가로 분할 매수합니다.
* **수익 실현 및 추세 추종**: 평단가 대비 목표 수익률(기본 10% / 국내 7%) 도달 시 분할 익절 및 Star(⭐)% 주문을 통한 추가 상승 추종.
* **쿼터 손절 및 리버스 모드**: 원금 소진 및 급락 시 손실을 최소화하는 쿼터 손절 또는 평단을 빠르게 낮추는 리버스 모드(Reverse Mode) 지원.
* **자동 차수 전환(Cycling)**: 전량 매도 완료 시 해당 차수를 자동 정산하고, 즉시 다음 차수(예: `SOXL_1차` ➔ `SOXL_2차`)로 신규 자동 진입.

### 2. 밸류 리밸런싱 (Value Rebalancing)
* **가치 추종 곡선**: 목표 밸류($V$)를 시간과 가격 변동에 맞춰 동적으로 산출하여 고점 매도, 저점 매수를 기계적으로 실행.
* **2주 예약 분할 주문**: 설정된 변동성 밴드(±15%)에 따라 체결 가능성이 높은 가격대에 매수/매도 분할 주문 배치.
* **투자 성향별 Pool 관리**: 적립식, 거치식, 인출식 모드에 따른 현금 풀(Pool) 소진 한도 방어.

### 3. 메리츠 전용 스마트 환전 관리자 (`core/forex.py`)
* **실시간 고시환율 & 적용환율 조회**: `GET /forex/v1/rates` 및 `GET /forex/v1/rates/applied`를 통해 고객별 우대할인율(`dcrt`)과 적용 스프레드가 반영된 정확한 실시간 환전 견적 확인.
* **실시간 즉시 환전 (`execute_exchange`)**: `POST /forex/v1/exchanges`를 통한 즉시 외화 매수(원화 ➔ USD) 및 외화 매도(USD ➔ 원화) 지원.
* **CAVR 연계 Auto-Funding (자동 매수 충전)**: 미국 주식 정기 매수 주문 시 USD 예수금이 부족하면, **필요한 부족분만큼 실시간 자동 환전**하여 주문 거부 방지.
* **CAVR 연계 Profit-Harvesting (익절금 회수)**: 미국 주식 익절 매도 체결 시 발생한 달러 대금을 지정한 비율만큼 **원화로 자동 환전**하여 확정 수익 실현.
* **환전 이력 DB 관리**: 환율, 적용 스프레드, 수수료, 거래번호를 `forex_history` 테이블에 영구 로깅.

### 4. 메리츠 Open API 특화 아키텍처
* **App Key 계좌 자동 바인딩**: 별도의 계좌번호 파라미터 전송 없이 토큰과 계좌가 1:1로 매핑되는 메리츠 규격 완벽 준수.
* **주문 2단계 안전장치**: 주문 전 `safety.preview()`를 거쳐 사전 검증 및 `confirm_token`을 자동 취득하여 주문 안정성 확보.
* **안전 시뮬레이션 모드 (`MERITZ_READ_ONLY=1`)**: 실제 주문이나 자금 이동 전, 가상 시뮬레이션으로 전체 로직 검증 가능.
* **종목 코드 규격 자동 변환**: 국내주식 시세(6자리 `005930`)와 주문(접두사 `A005930`) 규격 자동 처리, 미국주식 거래소(`OQ`, `NY` 등) 자동 라우팅.

### 5. 멀티 마켓 지원 및 알림 시스템
* **한국(KR) & 미국(US) 병렬 운용**: 국내 ETF(`122630` KODEX 레버리지 등)와 미국 레버리지(`SOXL`, `TQQQ` 등) 동시 운용.
* **SQLite WAL 모드 DB**: `trade_history`, `order_history`, `strategy_state`, `exchange_rates`, `forex_history` 무결성 보장.
* **텔레그램 실시간 알림**: 주문 전송, 체결, 실시간 환전 결과, 일일 계좌 요약을 텔레그램 봇으로 즉시 발송.

---

## 📂 프로젝트 폴더 구조 (Project Structure)

```text
Meritz/
├── config/                     # 전역 환경설정
│   └── settings.py             # .env 로더, 자격증명 및 시장별 파라미터 관리
├── core/                       # 핵심 비즈니스 로직
│   ├── brokers/                # 증권사 브로커 추상화 계층
│   │   ├── base.py             # Broker 공통 인터페이스 (Kiwoom 호환)
│   │   ├── meritz_kr.py        # 메리츠 국내주식 브로커 (시세/잔고/주문)
│   │   └── meritz_us.py        # 메리츠 미국주식 브로커 (시세/외화잔고/주문)
│   ├── cavr.py                 # 무한매수법(CA) & 밸류리밸런싱(VR) 엔진
│   ├── forex.py                # 외환(FX) 고시환율 조회 및 실시간 환전 관리자
│   ├── database.py             # SQLite WAL DB 초기화 및 상태/거래/환전 CRUD
│   ├── notifier.py             # 텔레그램 봇 메시지 발송 모듈
│   └── utils.py                # 종목명(ETF_list) 매핑 및 티커 변환 헬퍼
├── env/                        # 런타임 환경설정 및 종목 리스트 (보안 대상)
│   ├── .env                    # 메리츠 공통 API 키 및 텔레그램 설정
│   ├── .env.kr                 # 국내 주식 전략 파라미터
│   ├── .env.us                 # 미국 주식 전략 파라미터
│   ├── ETF_list_kr.txt         # 국내 관심 종목 목록
│   └── ETF_list_us.txt         # 미국 관심 종목 목록
├── open-api/                   # 메리츠증권 공식 SDK 저장소
│   ├── meritz/                 # meritz 경량 클라이언트 패키지
│   ├── examples/               # 공식 예제 코드 (01~09)
│   └── openapi.json            # 메리츠 REST API 공식 명세 (82개)
├── data/                       # 런타임 SQLite 데이터베이스 (cavr.db)
├── logs/                       # 실행 로그 보관 디렉터리
├── Dockerfile                  # OCI/서버 배포용 멀티플랫폼 도커파일
├── docker-compose.yml          # Portainer Stack 배포 정의 파일
├── requirements.txt            # 파이썬 의존성 패키지 명세
├── test_meritz_setup.py        # 시스템 종합 사전점검 및 모의 환전 검증 스크립트
├── project_context.md          # 개발 이력 및 기술 마일스톤
└── README.md                   # 본 프로젝트 설명서
```

---

## 🚀 설치 및 시작하기 (Getting Started)

### 1. 가상환경 구성 및 의존성 패키지 설치
Python 3.10 이상 사용을 권장합니다.

```bash
# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate       # Linux / WSL
# .venv\Scripts\activate        # Windows PowerShell

# 필수 패키지 설치
pip install -r requirements.txt

# 메리츠 공식 SDK를 editable 모드로 등록
pip install -e ./open-api
```

### 2. 환경변수 설정
`env/.env`, `env/.env.kr`, `env/.env.us` 파일에 자격증명 및 투자 파라미터를 설정합니다.

#### `env/.env` (공통)
```ini
# 메리츠증권 자격증명 (개발자 포털 발급)
MERITZ_APP_KEY=your_app_key
MERITZ_APP_SECRET=your_app_secret
MERITZ_BASE_URL=https://openapi.imeritz.com:9443
MERITZ_WS_URL=wss://openapi.imeritz.com:29443/websocket

# 안전 모드: 1(조회 및 모의 주문/환전), 0(실제 주문 및 실제 환전 실행)
MERITZ_READ_ONLY=1
MERITZ_TIMEOUT=15

# 텔레그램 알림 설정
NOTIFIER_ENABLED=true
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# 환전(FX) 설정
FX_AUTO_EXCHANGE=false
FX_TARGET_CURRENCY=USD
FX_BUFFER_USD=10.0
```

#### `env/.env.kr` (국내 주식)
```ini
MARKET_TYPE=KR
ticker="122630"             # KODEX 레버리지
initial_cash=10000000       # 초기 투자금 1,000만원
fee_rate=0.0                # 수수료
tax_sell=0.0020             # 매도 거래세 0.2%
T_default=40                # 무한매수 기본 분할 수
a_default=40                # 사용자 분할 수
T_profit=0.07               # 목표 수익률 7%
quarter_loss_stop=FALSE     # 쿼터 손절 여부
```

#### `env/.env.us` (미국 주식)
```ini
MARKET_TYPE=US
ticker="SOXL"               # 미국 반도체 3배 레버리지
initial_cash=10000.0        # 초기 투자금 $10,000
fee_rate=0.0                # 수수료
tax_sell=0.0000206          # SEC Fee
T_default=40                # 무한매수 기본 분할 수
a_default=40                # 사용자 분할 수
T_profit=0.15               # 목표 수익률 15%
quarter_loss_stop=FALSE     # 쿼터 손절 여부
```

### 3. 시스템 종합 사전점검 실행
API 키 적용 후 또는 모의 모드 상태에서 전체 파이프라인을 검증합니다:

```bash
python test_meritz_setup.py
```
* **검증 항목**: 환경설정 로드, SQLite DB 스키마 및 CRUD, 브로커 초기화, 외환 시뮬레이션(모의 환전), CA/VR 엔진 인스턴스화.

---

## 💱 외환 및 환전 사용 예시 (Forex Usage)

```python
from core.forex import forex_manager

# 1. 미국 달러(USD) 실시간 고시환율 조회
rate_info = forex_manager.get_market_rate(symbol="USD")
print(f"기준환율: {rate_info['deal_stnd_exrt']}원")

# 2. 실시간 적용환율 견적 (우대할인율 및 스프레드 반영)
quote = forex_manager.get_applied_rate(direction="BUY", symbol="USD")
print(f"적용 매수환율: {quote['applied_rate']}원 (우대율: {quote['dcrt']}%)")

# 3. 실시간 외화 환전 신청 (원화 -> $100 외화 매수)
# MERITZ_READ_ONLY=1 이면 모의 환전 시뮬레이션으로 안전하게 동작합니다.
success = forex_manager.execute_exchange(
    direction="BUY",
    amount_usd=100.0,
    note="CAVR 정기 매수 자금 충전"
)

# 4. CAVR 연계 외화 부족분 자동 충전 (Auto-Funding)
forex_manager.ensure_usd_balance(
    current_usd=20.0,
    required_usd=150.0,
    buffer_usd=10.0,
    strategy_name="VR_SOXL"
)
```

---

## 🐳 Docker 및 OCI (오라클 클라우드) 배포

본 프로젝트는 Docker Hub 및 OCI Portainer 환경에 최적화되어 있습니다.

### 1. Docker 이미지 빌드 및 푸시
```bash
# AMD64 및 ARM64(Ampere A1) 동시 지원 멀티플랫폼 빌드
docker buildx build --platform linux/amd64,linux/arm64 \
  -t simji3/meritz-autotrade:latest \
  --push .
```

### 2. OCI 서버 준비 및 환경파일 복사
```bash
# OCI 서버 디렉터리 생성
mkdir -p /home/snaredrum/meritz/data
mkdir -p /home/snaredrum/meritz/logs
mkdir -p /home/snaredrum/meritz/env

# 로컬 환경파일을 서버로 전송 (SCP)
scp env/.env* snaredrum@<OCI_IP>:/home/snaredrum/meritz/env/
scp env/ETF_list_*.txt snaredrum@<OCI_IP>:/home/snaredrum/meritz/env/
```

### 3. Portainer Stack 배포
Portainer 웹 콘솔의 `Stacks` ➔ `Add stack`에서 `docker-compose.yml`을 배포합니다:

```yaml
version: '3.8'

services:
  dashboard:
    image: simji3/meritz-dashboard:latest
    container_name: meritz-dashboard
    command: >
      streamlit run dashboard.py
      --server.port=8501
      --server.address=0.0.0.0
      --server.enableCORS=false
      --server.enableXsrfProtection=false
      --browser.gatherUsageStats=false
    ports:
      - "8504:8501"  # 타 서비스와 포트 충돌 방지
    volumes:
      - /home/snaredrum/meritz/data:/app/data
      - /home/snaredrum/meritz/logs:/app/logs
      - /home/snaredrum/meritz/env:/app/env
    restart: unless-stopped
    environment:
      - TZ=Asia/Seoul
      - PYTHONUNBUFFERED=1

  scheduler:
    image: simji3/meritz-scheduler:latest
    container_name: meritz-scheduler
    command: python core/scheduler.py
    volumes:
      - /home/snaredrum/meritz/data:/app/data
      - /home/snaredrum/meritz/logs:/app/logs
      - /home/snaredrum/meritz/env:/app/env
    restart: unless-stopped
    depends_on:
      - dashboard
    environment:
      - TZ=Asia/Seoul
      - PYTHONUNBUFFERED=1

networks:
  default:
    external: true
    name: nginx-proxy
```

---

## 🛡️ 안전 가이드라인 (Safety & Disclaimer)

1. **`MERITZ_READ_ONLY=1` 유지 권장**: 초기 설정 및 전략 테스트 시에는 반드시 `MERITZ_READ_ONLY=1`을 설정하여 모의 주문 및 모의 환전 상태에서 동작을 확인하십시오.
2. **환전 주의사항**: 실시간 환전(`POST /forex/v1/exchanges`)은 **실제 계좌 간 자금 이동**을 수반합니다. `MERITZ_READ_ONLY=0`으로 전환하기 전에 충분히 로그를 확인하시기 바랍니다.
3. **투자 유의사항**: 본 소프트웨어는 투자 참고 및 자동화 도구이며, 모든 투자 결과와 손실에 대한 최종 책임은 사용자 본인에게 있습니다.

---

## 📜 라이선스 (License)

본 프로젝트는 개인 및 비상업적 투자 자동화 목적으로 제작되었습니다.
