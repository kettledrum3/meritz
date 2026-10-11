# Meritz Open API 자동매매 프로젝트 Context (project_context.md)

- **프로젝트 위치**: `D:\Python_D\Meritz`
- **프로젝트 시작일**: 2026년 10월 11일 (일)
- **대상 증권사**: 메리츠증권 (Meritz Securities)
- **주요 목표**: 메리츠증권 Open API를 활용한 CA VR (Cost Averaging Value Rebalancing) 주식 자동매매 시스템 구축 (기존 Kiwoom REST/WebSocket 기반 시스템 이식)

---

## 1. 일정 및 주요 마일스톤

| 일자 | 구분 | 내용 및 목표 |
| :--- | :--- | :--- |
| **2026-10-11 (일)** | **프로젝트 착수 & 기본 셋업** | • 메리츠 공식 Open API 리포지토리 클론 및 분석<br>• 기존 `d:\Python_D\kiwoom` 아키텍처 및 CA VR 엔진 분석<br>• 기본 프로젝트 폴더 구조 설계 및 베이스 브로커 인터페이스 구축<br>• 마이그레이션 가이드 및 환경설정 파일 작성 |
| **2026-10-11 (일)** | **CAVR 이식 & 외환/인프라 완비** | • CA VR 핵심 엔진(`cavr.py`) 및 데이터베이스 모듈(`database.py`) 이식 완료<br>• 메리츠 외환/환전 통합 관리자(`forex.py`) 신규 구축 및 CAVR 연계<br>• 국내/미국 브로커(`meritz_kr.py`, `meritz_us.py`) 구현 완료<br>• OCI Dockerfile, docker-compose.yml 및 README.md 작성 완료<br>• 시스템 종합 사전점검(`test_meritz_setup.py`) 통과 |
| **2026-10-12 (월)** | **API Key 발급 & 실호출 & 런타임 완비** | • 메리츠증권 실계좌 **App Key / App Secret 발급 및 `env/.env` 등록 완료**<br>• 국내/미국 실시간 시세, 잔고, 고시환율 실호출 검증 통과 (100% 동작)<br>• OCI 배포용 런타임 엔트리포인트(`core/scheduler.py`, `dashboard.py`) 신규 구현 완료<br>• 메리츠 공식 로고(`meritz_logo.png`) UI 적용 및 Arca/AMEX 거래소 코드(`AX`) 보정 |

---

## 2. 진행 완료 작업 내역

### 1) 2026-10-11 (일) 완료 내역
1. **메리츠 공식 저장소 Clone & API 카탈로그 분석**:
   - `open-api/` 공식 저장소 및 82개 REST/WebSocket API 스펙 전수 분석 완료
   - 환전/외환 API (`fx_rates`, `fx_rates_applied`, `fx_exchanges`, `fx_exchanges_history`) 발굴 및 규격 분석
2. **환경설정 및 알림 모듈 이식**:
   - `config/settings.py`: `.env`, `.env.kr`, `.env.us` 동적 로더 및 FX 환경설정 구현
   - `core/notifier.py`: 메리츠 전용 텔레그램 봇 알림 모듈 이식 (HTML 태그 지원)
   - `core/utils.py`: 국내/해외 종목명 매핑 및 티커 클렌징 유틸리티 이식
3. **데이터베이스 모듈 이식 및 환전 스키마 확장 (`core/database.py`)**:
   - SQLite `data/cavr.db` 초기화 및 WAL 모드 구성
   - `trade_history`, `order_history`, `strategy_state`, `exchange_rates` 이식 완료
   - `forex_history` (실시간 외화 환전 체결 내역 기록 테이블) 및 CRUD 함수 추가
4. **메리츠 외환/환전 통합 관리자 (`core/forex.py`) 신규 구축**:
   - 고시환율 조회 (`get_market_rate`) 및 환전 적용환율 견적 조회 (`get_applied_rate`)
   - 실시간 환전 실행 (`execute_exchange` - 모의 환전 지원, 텔레그램 알림 및 DB 자동 기록)
   - CAVR 연계 스마트 환전(`ensure_usd_balance`, `harvest_usd_profit`) 구현
5. **브로커 계층 구축 (`core/brokers/`)**:
   - `core/brokers/base.py`: 공통 Broker 인터페이스
   - `core/brokers/meritz_kr.py`: 국내주식 브로커 (`A` 접두사 자동 처리, 2단계 토큰 발급)
   - `core/brokers/meritz_us.py`: 해외(미국)주식 브로커
6. **CA VR 핵심 전략 엔진 이식 (`core/cavr.py`)**:
   - Kiwoom에서 검증된 무한매수법(Cost Averaging) & 밸류리밸런싱(Value Rebalancing) 엔진 100% 이식
7. **OCI 서버 및 Portainer 배포 인프라 정의**:
   - `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitignore` 정밀화

### 2) 2026-10-12 (월) 신규 진행 및 개선 내역
1. **메리츠 공식 API Key 발급 및 실서버 호출 검증 완료**:
   - `env/.env` 파일에 실계좌 연동 `MERITZ_APP_KEY`, `MERITZ_APP_SECRET` 등록
   - 국내 주식 실시간 시세 실호출 검증: `005930`(삼성전자) 정상 수신 (`263,000원`)
   - 미국 주식 실시간 시세 실호출 검증: `SOXL`($139.76), `TQQQ`($81.28), `SPY`($778.57) 정상 수신
   - 계좌 예수금 및 실시간 고시환율(`1,339.20원`) 실호출 연동 성공
2. **미국 해외 거래소 코드 정밀 매핑 (`core/brokers/meritz_us.py`)**:
   - 메리츠 OpenAPI 사양에 따라 NYSE Arca 상장 레버리지 ETF(`SOXL`, `UPRO`, `SPY`)의 거래소 코드를 `AX`(아멕스)로 정밀 매핑하여 시세 조회 오류 해결
3. **새벽/주말 대비 외환 고시환율 Fallback 구현 (`core/forex.py`)**:
   - 당일 첫 고시 전(새벽 시간) 또는 휴일 조회 시, 최대 5일 전까지 역추적하여 직전 영업일 최종 고시환율을 자동 적용하도록 안정화
4. **자동매매 스케줄러 신규 구현 (`core/scheduler.py`)**:
   - `APScheduler` 기반 컨테이너 상시 구동 백그라운드 데몬 구축
   - **한국장 (KR)**: 08:50(장전 정비), 09:00(VR/CA 정규장 개장 주문), 10:00(CA 75% 매도 확인), 09:05~15:20(5분 주기 급락 감시), 15:20(CA 종가/LOC 주문), 15:40(일일 결산 및 텔레그램 리포트)
   - **미국장 (US)**: 서머타임(DST) & 표준시 자동 감지, 장 시작 30분 전 자금 부족 시 스마트 자동 환전(Auto-Funding), 10분 전 VR/CA 주문 전송, 장중 5분 주기 급락 감시, 새벽 장마감 후 결산 리포트 발송
   - `run_intraday_check`의 불필요한 `now_dt` 키워드 인자 제거로 린트/런타임 에러 해소
5. **Streamlit 웹 관제 대시보드 신규 구현 (`dashboard.py`)**:
   - 실시간 시장 개장 상태 배지 (`OPEN` / `CLOSED`), 안전모드 배지, 실시간 고시환율 카드
   - 계좌 자산 요약(원화 예수금, 외화 예수금, 환산 합산액)
   - 무한매수법(CA) 회차($a$/$T$) 및 진행률 프로그레스 바, 밸류리밸런싱(VR) V 추종 밴드 게이지
   - 당일 주문 내역(`order_history`), 체결 및 실현손익 이력(`trade_history`), 실시간 외환 환전 내역(`forex_history`), `scheduler.log` 실시간 뷰어 탑재
6. **메리츠 공식 브랜딩 로고 적용**:
   - 대시보드 사이드바 상단 및 메인 헤더에 `meritz_logo.png` 로고 탑재

---

## 3. 핵심 기술 아키텍처 및 차이점 정리

| 항목 | Kiwoom Open API | Meritz Open API | 대응 구현 상태 |
| :--- | :--- | :--- | :--- |
| **계좌번호 지정** | 모든 요청 바디에 `cano`, `acnt_no` 필수 전송 | **App Key에 계좌 자동 매핑** (요청 시 전송 금지) | 브로커 내부에서 계좌번호 파라미터 제외 (완료) |
| **종목 코드 규격** | 시세/주문 동일 6자리 (`005930`) | **시세: 6자리 (`005930`)**<br>**주문: "A" 접두사 (`A005930`)** | `place_order` 호출 시 `"A"` 자동 부착 (완료) |
| **미국 주식 거래소** | 티커 문자열 (`SOXL`) | 티커 + 거래소코드 (`OQ` 나스닥, `AX` 아멕스/Arca, `NY` 뉴욕) | `MeritzUsBroker` 거래소 매핑 딕셔너리 구축 (완료) |
| **주문 안전장치** | 즉시 전송 | `preview()` → `confirm_token` 2단계 확인 & `MERITZ_READ_ONLY` | 브로커 내부에서 원스톱 안전 래핑 (완료) |
| **외환 환율/환전** | 키움 별도 프로세스 필요 | **REST API로 실시간 고시환율/적용환율/즉시환전 지원** | `MeritzForexManager` 구축 및 CAVR 연계 (완료) |

---

## 4. 향후 작업 계획 (Next Steps)

- [x] **1. 메리츠 개발자 포털 API KEY 신청 및 발급받기**: 발급 완료 및 `env/.env` 등록 완료
- [x] **2. 실제 시세/잔고/환율 실호출 동작 검증**: 국내/미국 시세 및 고시환율 수신 검증 완료
- [x] **3. 런타임 엔트리포인트 파일 완비**: `core/scheduler.py`, `dashboard.py` 구현 및 문법 검증 완료
- [ ] **4. Docker 이미지 재빌드 및 OCI Portainer 재배포**:
  - `docker buildx build --platform linux/amd64,linux/arm64 -t simji3/meritz-dashboard:latest -t simji3/meritz-scheduler:latest --push .`
  - OCI Portainer에서 `Re-pull image and redeploy` 실행하여 컨테이너 정상 기동
- [ ] **5. CAVR 실시간 주문 검증 (안전모드 -> 실거래 가동)**:
  - `MERITZ_READ_ONLY=1` 안전 상태에서 CA/VR 주문 프리뷰 및 토큰 발급 동작 확인
  - 1주 소액 테스트 후 `MERITZ_READ_ONLY=0` 전환하여 본 전략 정식 가동
