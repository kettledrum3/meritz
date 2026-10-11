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
| **2026-10-12 (월)** | **Open API 서비스 오픈 & 실호출** | • 메리츠증권 개발자 포털에서 **App Key / App Secret 발급 및 적용**<br>• 계좌 연동 및 시세/잔고/환율 실호출 검증<br>• 안전장치 검증(`MERITZ_READ_ONLY=1` 확인 후 주문 테스트) 및 소액 실거래 시작 |

---

## 2. 진행 완료 작업 (2026-10-11 완료 내역)

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
   - **[신규] `forex_history` (실시간 외화 환전 체결 내역 기록 테이블) 및 CRUD 함수 추가**

4. **메리츠 외환/환전 통합 관리자 (`core/forex.py`) 신규 구축**:
   - 고시환율 조회 (`get_market_rate`)
   - 환전 적용환율 견적 조회 (`get_applied_rate` - 스프레드/우대할인율 반영)
   - 실시간 환전 실행 (`execute_exchange` - `MERITZ_READ_ONLY` 모의 환전 지원, 텔레그램 알림 및 DB 자동 기록)
   - **CAVR 연계 스마트 환전 구현**:
     - `ensure_usd_balance`: 미국 주식 매수 시 달러 부족분 자동 충전(Auto-Funding)
     - `harvest_usd_profit`: 익절 매도 대금의 원화 자동 회수(Profit-Harvesting)

5. **브로커 계층 구축 (`core/brokers/`)**:
   - `core/brokers/base.py`: 공통 Broker 인터페이스
   - `core/brokers/meritz_kr.py`: 메리츠 공식 SDK 기반 국내주식 브로커 (`A` 접두사 자동 처리, 2단계 토큰 발급)
   - `core/brokers/meritz_us.py`: 메리츠 공식 SDK 기반 해외(미국)주식 브로커 (`SOXL` 등 거래소 매핑)

6. **CA VR 핵심 전략 엔진 이식 (`core/cavr.py`)**:
   - Kiwoom에서 검증된 무한매수법(Cost Averaging) & 밸류리밸런싱(Value Rebalancing) 엔진 100% 이식
   - 브로커 객체지향 DI(Dependency Injection) 바인딩 및 팩토리(`get_broker`) 지원

7. **종합 사전점검 스크립트 작성 및 통과 (`test_meritz_setup.py`)**:
   - 환경설정, DB 테이블/CRUD, 브로커 인스턴스화, 외환 시뮬레이션, CA/VR 엔진 인스턴스화 전 항목 통과 완료!

8. **OCI 서버 및 Portainer 배포 인프라 완비**:
   - `Dockerfile`: `python:3.12-slim` 멀티플랫폼(AMD64/ARM64) 이미지 정의
   - `.dockerignore`: 시크릿 및 런타임 데이터 이미지 격리
   - `docker-compose.yml`: Portainer Stack 배포 파일 작성 (대시보드 8504:8501, 스케줄러, `nginx-proxy` 연동)
   - `.gitignore` 정밀화: 환경변수 시크릿 격리 및 ETF 리스트 보존

9. **IDE 환경 및 모듈 의존성 해결**:
   - `.vscode/settings.json` extraPaths 설정 및 `open-api` editable 등록으로 IDE 정적 린터 에러 해소

10. **프로젝트 종합 설명서 작성 (`README.md`)**:
    - 전략 및 환전 특장점, 디렉터리 구조, 로컬 실행법, OCI Portainer 배포 가이드 완비

---

## 3. 핵심 기술 아키텍처 및 차이점 정리

| 항목 | Kiwoom Open API | Meritz Open API | 대응 구현 상태 |
| :--- | :--- | :--- | :--- |
| **계좌번호 지정** | 모든 요청 바디에 `cano`, `acnt_no` 필수 전송 | **App Key에 계좌 자동 매핑** (요청 시 전송 금지) | 브로커 내부에서 계좌번호 파라미터 제외 (완료) |
| **종목 코드 규격** | 시세/주문 동일 6자리 (`005930`) | **시세: 6자리 (`005930`)**<br>**주문: "A" 접두사 (`A005930`)** | `place_order` 호출 시 `"A"` 자동 부착 (완료) |
| **미국 주식 티커** | 티커 문자열 (`SOXL`) | 티커 문자열 + 거래소 (`OQ`, `NASD`) | `MeritzUsBroker` 거래소 매핑 딕셔너리 구축 (완료) |
| **주문 안전장치** | 즉시 전송 | `preview()` → `confirm_token` 2단계 확인 & `MERITZ_READ_ONLY` | 브로커 내부에서 원스톱 안전 래핑 (완료) |
| **외환 환율/환전** | 키움 별도 프로세스 필요 | **REST API로 실시간 고시환율/적용환율/즉시환전 지원** | `MeritzForexManager` 구축 및 CAVR 연계 (완료) |

---

## 4. 내일(10월 12일 월요일) 작업 계획

- [ ] **1. 메리츠 개발자 포털 API KEY 신청 및 발급받기**:
  - 메리츠증권 개발자 포털 접속 후 실계좌 연동 App Key / App Secret 발급
  - 발급받은 키를 `env/.env` 파일의 `MERITZ_APP_KEY`, `MERITZ_APP_SECRET`에 입력
- [ ] **2. 실제 시세/잔고/환율 실호출 동작 검증**:
  - `python -m open-api.examples.02_market` (국내 시세 실조회)
  - `python -m open-api.examples.03_overseas_market` (미국 시세 실조회)
  - `python -m open-api.examples.04_account` (계좌 잔고 및 예수금 실조회)
  - `python -m open-api.examples.08_forex` (실시간 고시환율 실조회)
- [ ] **3. 시스템 종합 검증 스크립트 실호출 테스트**:
  - `python test_meritz_setup.py` 실행하여 실계좌 잔고 및 고시환율 실체결 연동 확인
- [ ] **4. CAVR 실시간 주문 검증 (안전모드 -> 실거래 가동)**:
  - `MERITZ_READ_ONLY=1` 안전 상태에서 CA/VR 주문 프리뷰 및 토큰 발급 확인
  - 정상 동작 검증 후 `MERITZ_READ_ONLY=0` 전환 및 1주 소액 테스트를 거쳐 본 전략 정식 가동


