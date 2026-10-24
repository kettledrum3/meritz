# Meritz Open API 자동매매 프로젝트 Context (project_context.md)

- **프로젝트 위치**: `D:\Python_D\Meritz`
- **프로젝트 시작일**: 2026년 10월 11일 (일)
- **대상 증권사**: 메리츠증권 (Meritz Securities)
- **주요 목표**: 메리츠증권 Open API를 활용한 CA VR (Cost Averaging Value Rebalancing) 주식 자동매매 시스템 구축 (기존 Kiwoom REST/WebSocket 기반 시스템 이식)
- **문서 관리 원칙**: 향후 모든 기능 개발, 버그 수정 및 인프라 변경 작업 내역은 **작업 일자(YYYY-MM-DD)별 독립 섹션**으로 체계적으로 누적 기록 및 관리함.

---

## 1. 일정 및 주요 마일스톤

| 일자 | 구분 | 내용 및 목표 |
| :--- | :--- | :--- |
| **2026-10-11 (일)** | **프로젝트 착수 & 기본 셋업** | • 메리츠 공식 Open API 리포지토리 클론 및 분석<br>• 기존 `d:\Python_D\kiwoom` 아키텍처 및 CA VR 엔진 분석<br>• 기본 프로젝트 폴더 구조 설계 및 베이스 브로커 인터페이스 구축<br>• 마이그레이션 가이드 및 환경설정 파일 작성 |
| **2026-10-11 (일)** | **CAVR 이식 & 외환/인프라 완비** | • CA VR 핵심 엔진(`cavr.py`) 및 데이터베이스 모듈(`database.py`) 이식 완료<br>• 메리츠 외환/환전 통합 관리자(`forex.py`) 신규 구축 및 CAVR 연계<br>• 국내/미국 브로커(`meritz_kr.py`, `meritz_us.py`) 구현 완료<br>• OCI Dockerfile, docker-compose.yml 및 README.md 작성 완료<br>• 시스템 종합 사전점검(`test_meritz_setup.py`) 통과 |
| **2026-10-12 (월)** | **API Key 발급 & 실호출 & 런타임 완비** | • 메리츠증권 실계좌 **App Key / App Secret 발급 및 `env/.env` 등록 완료**<br>• 국내/미국 실시간 시세, 잔고, 고시환율 실호출 검증 통과 (100% 동작)<br>• OCI 배포용 런타임 엔트리포인트(`core/scheduler.py`, `dashboard.py`) 신규 구현 완료<br>• 메리츠 공식 로고(`meritz_logo.png`) UI 적용 및 Arca/AMEX 거래소 코드(`AX`) 보정 |
| **2026-10-12 (월) ~ 10-13 (화)** | **키움 대시보드/백테스트 전면 이식 및 안정화** | • 키움 대시보드 컨트롤 패널 및 5개 탭 전면 이식 (`dashboard.py`)<br>• 백테스트 엔진(`core/backtest.py`) 이식 및 TQQQ CA/VR 시뮬레이션 검증 완료<br>• `core.brokers.kiwoom_*` 잔재 제거 및 메리츠 브로커 완전 전환<br>• Streamlit 최신 규격(`width='stretch'`) 전면 반영 및 Deprecation 해소<br>• 외환 고시환율 연동 및 미국 휴장일/주말 판정 로직(`is_us_market_holiday`) 결함 해결 |
| **2026-10-17 (토)** | **MY 계좌평가 신설 & 외환/잔고 고도화 & 점검 방어** | • 대시보드 상단 메리츠 HTS 형식 **"MY 계좌평가"** 구역 신설 (기본 닫힘 Expander, 7개 자산평가 및 2행 1레코드 보유잔고 테이블)<br>• 외환 100% 우대 실시간 환전/관리 탭 및 사이드바 환전 모드 신설<br>• 모의투자 Dimming 및 강제 실전투자 보호 가드 구축<br>• 메리츠 공식 GitHub(`open-api`) 최신 업데이트 동기화 (페이징/방화벽/예약주문 코드 완비)<br>• 외화/원화 가용예수금 실제 API 필드 매핑 및 표시 정상화 ($135.87 / ₩183,220원)<br>• 메리츠 일일 전산 점검 시간(**23:50 ~ 00:20**) 자동 감지 및 에러 방어 로직 전면 구축 |
| **2026-10-18 (일)** | **환전 조건부 분할 자동매매 (Forex DCA/CA 전략) 신설 & 스케줄러 심박/운영시간 고도화** | • 환전 DCA/CA 전략 엔진 구축 (`ForexDcaEngine` in `core/forex.py`)<br>• 지표 연동: 3개월 평균 환율(`3M_AVG`) 및 달러인덱스(`DXY`) 실시간 조회 및 캐싱<br>• 분할 매수 규칙: 직전 매수가 대비 0.5%씩 하락 시 설정 단위금액 추가 매수<br>• 분할/일괄 익절 규칙: 3단계 순차 분할 매도(`SPLIT_3`) 및 목표수익률 일괄 매도(`FULL_TARGET`)<br>• DB 영속화: `forex_strategy_state` 테이블 및 CRUD 함수 신설 (`core/database.py`)<br>• **실시간 환전 시간 반영**: 메리츠 개정 규격에 맞추어 **영업일 09:00 ~ 익일 02:00** (점검시간 23:50~00:20 제외) 자동 판별 함수(`is_forex_available_time`) 탑재<br>• **스케줄러 2단계 감시 등록**: 주간/야간(09:00~23:50) 및 심야 연장(00:20~02:00) 10분 주기 등록 (`core/scheduler.py`)<br>• **스케줄러 30초 심박(Heartbeat) 엔진 보강**: 30초 주기 DB 기록(`update_heartbeat`) 및 기동 즉시 첫 심박 보장으로 "프로세스 응답 없음" 버그 해결<br>• 대시보드 외환 탭 강화: DXY/3개월 평균 메트릭, DCA 파라미터 설정 및 진행 모니터링 카드, 즉시 평가 버튼 탑재 |
| **2026-10-19 (월)** | **환전 안전장치 & 실시간 환율 & 미국 일봉 시세(백테스트) API & 스케줄러 최적화** | • **환전 confirm_token 에러 해결**: 메리츠 상태변경 2단계 안전장치(`safety.preview()`)를 `execute_exchange`에 연동하여 1회용 `confirm_token` 자동 취득 및 요청 파라미터 전달 구현 완료<br>• **mac_address 및 규격 점검**: 메리츠 라이브러리(`client.py`)에서 `headers()`를 통해 12자리 단말 MAC 주소를 자동 포함 전송함을 검증하고, 명세에 맞추어 `frcr_amt` 규격(문자열 소수점 3자리) 보완<br>• **실시간 환율 원스톱 조회 API 신설**: `forex_manager.get_rates_summary("USD")`를 통해 기준환율, 적용 매수환율(`by_rate`), 적용 매도환율(`sl_rate`), 우대율(`dcrt`), 스프레드를 일괄 조회하는 기능 구현<br>• **대시보드 실시간 환율 버튼 및 3대 환율 표시**: `render_forex_tab`에 **[🔄 실시간 환율 조회]** 버튼을 추가하고, 기준 환율 메트릭 아래에 매수 환율(원화➔달러)과 매도 환율(달러➔원화)을 명확하게 동시 표시하도록 고도화<br>• **미국 일봉 시세(백테스트) API 파라미터 오류 해결**: `ovs_market_candles_days` 필수 파라미터(`dely_rltm_cls_code="0"`, `mod_stpr_cls_code="0"`) 및 기간 조회(`from`, `to`) 누락 보완 완료 ➔ TQQQ 220일 과거 데이터 수집 및 백테스트 정상화<br>• **스케줄러 로그 최적화**: APScheduler(`apscheduler.executors.default`)의 30초 주기 반복 실행 로그(`Running job... / executed successfully`) 및 `meritz` HTTP 통신 로그를 `WARNING`으로 필터링하여 로그 노이즈 대폭 차단<br>• **환율 및 외환 DCA 감시 주기 1분 단축**: 스케줄러의 외환 DCA 조건 평가 및 실시간 USD/KRW 환율 갱신 주기를 10분에서 **1분**으로 단축 적용 완료 |
| **2026-10-24 (토)** | **백테스트-실전투자 DB 완전 격리 & 차수 비정상 전환 결함 해결 & DB 정상화** | • **원인 규명**: 백테스트 시뮬레이션 중 전량 매도 발생 시 `_handle_cycle_finish_and_restart`에서 `use_db` 체크가 누락되어 실제 운용 DB의 `finish_strategy_db` 및 `save_state_db`가 호출되고 텔레그램 메시지가 발송되던 결함 발견<br>• **3중 격리 안전망 구축**: `cavr.py` 내 모든 차수 전환/상태 저장/알림 로직에 `use_db` 조건 분기 탑재, `backtest.py`에 고유 네임스페이스(`BACKTEST_`) 및 격리 파일 경로 주입, `database.py`에 백테스트 상태 저장 차단 Safety Guard 탑재<br>• **실제 DB 완전 복구**: `finished_strategy_state`에 오염 저장되었던 `TQQQ_1차` ~ `TQQQ_6차` 레코드 6건 삭제 및 활성 `strategy_state`의 TQQQ 전략을 정상 기본 0차(`strategy_name=''`)로 초기화 완료<br>• **격리 무결성 검증**: TQQQ 220일 백테스트 재실행 후 실제 DB 레코드 수 및 활성 상태가 단 1건도 변하지 않음을 자동 검증 통과 |

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

### 3) 2026-10-12 (월) 키움 대시보드 구조 및 백테스트 전면 이식 완료
1. **키움 스타일 컨트롤 패널 & 대시보드 100% 이식 (`dashboard.py`)**:
   - **사이드바 구성**:
     - 상단 메리츠 로고 및 사용자 환영/로그아웃
     - 4개 분할 운영 설정: 운영 모드(실전/모의), 활성 시장(미국/한국), 방법론(CA/VR), 실행 모드(투자 실행/백테스트)
     - 전략 설정 컨트롤: 종목 선택, 저장된 전략 선택, 선택됨 배지, 자본금, G값, 밴드(%), 투자방식(적립식/거치식/인출식), 주기별 적립/인출액, 주기(격주 금요일), 0일차 잔고 편입, Pool 사용한도(%) 슬라이더
     - 3대 전략 관리 버튼: [신규전략 저장 및 실행], [저장된 전략 불러오기], [전략 업데이트]
     - 스케줄러 제어: 30초 주기 Heartbeat 감지 프래그먼트, [실행]/[정지] 토글, 실시간 상태 배지
     - 수동 주문 제어: [주문 계획 생성 (Preview)]
     - 전략별 투자 현황 요약 배너 (SOXL CA, TQQQ VR 등)
   - **메인 탭 5종 구성**:
     1. `🇺🇸 미국 주식 시장 현황` (선택 시장 우선 배치)
     2. `🇰🇷 한국 주식 시장 현황`
     3. `🏁 종료된 전략 내역` (실현 손익 요약, MDD, 거래 내역)
     4. `📈 손익분석` (일/주/월/년 단위 Plotly 차트 및 종목/전략 비중 파이차트)
     5. `⚙️ 설정` (사용자 프로필, Zoho SMTP 알림 설정)
   - **시장 탭 내부 핵심 모듈 완비**:
     - 전략 요약 아코디언 (`[CA] ...`, `[VR] ...`) 및 작업 대상 헤더
     - 10초 주기 실시간 시세 / 고시환율 / [지금 환율 조회] 버튼
     - `미국 환율(USD/KRW) 일별 변동 추이` 익스팬더: Plotly 시계열 라인 차트 및 최근 기록 테이블
     - 계좌 상태 갱신 / 1주일 강제 동기화 버튼 / 운용 자본금 및 총 예수금 메트릭
     - 실시간 보유 종목 현황 카드
     - 실전 매매 운영: VR 실력공식 구성 변수 표 (`V1`, `Pool`, `G`, `E`, `Contribution`, `V2`), 밴드 위치 게이지
     - 당일 발주 기준 상태 및 1~5차 매수/매도 지정가 예약 주문 가이드
     - 주문 내역 조회 & 전략 필터링
     - 실현 손익 현황 & 거래 내역 테이블 (별칭 필터, 실시간 동기화)
     - 하단 실시간 시스템 로그 및 백그라운드 스케줄러 로그 뷰어
2. **백테스트 엔진 전면 이식 및 검증 (`core/backtest.py`)**:
   - `BacktestBroker` 및 `run_backtest` 모듈 이식 완료
   - CA V2.2 및 VR 가변 밴드/Pool 한도 알고리즘 완벽 지원
   - `TQQQ` 300일 데이터 기반 CA/VR 시뮬레이션 검증 완료 (수익률, CAGR, MDD, 승률, Plotly 시계열 차트 연동)
3. **보조 지원 모듈 완비**:
   - `core/auth.py`: IP 기반 자동 로그인, OTP 및 사용자 비밀번호 관리
   - `core/email_service.py`: Zoho SMTP 기반 이메일 알림
   - `core/fetch_data.py`: 메리츠 브로커 기반 일봉 데이터 수집
   - `core/brokers/meritz_kr.py`, `core/brokers/meritz_us.py`: `account_no`, `get_stock_info`, `get_exchange_rate`, `fetch_daily_chart` 확충
4. **런타임 결함 해결 및 최신 Streamlit 규격 반영**:
   - **브로커 동적 임포트 오류 해결**: `dashboard.py` 내 `core.brokers.kiwoom_*` 잔재를 `core.brokers.meritz_*`로 전면 교체하여 `ModuleNotFoundError` 근본 해소
   - **Streamlit 최신 권고사항 반영**: `use_container_width=True` Deprecation 대응으로 모든 위젯에 `width='stretch'` 적용 완료 (경고 0건)
   - **외환 고시환율 시그니처 정합성 교정**: `forex_manager.get_market_rate`의 `force_refresh` 옵셔널 인자 지원 및 반환 딕셔너리(`deal_stnd_exrt`, `diff`, `pct`)와 `save_exchange_rate_db` 인자 연동 안정화
   - **미국장 휴장일 및 주말 판정 로직 보완**: `is_us_market_holiday(d=None)` 기본값 지원 및 토/일 주말 감지 로직 추가로 스케줄러 5분 급락 감시(`job_us_intraday_check`)의 `TypeError` 해소 및 실호출 통과

### 4) 2026-10-17 (토) MY 계좌평가 신설 & 외환/잔고 고도화 & 점검 방어 내역
1. **대시보드 상단 메리츠 HTS 형식 "MY 계좌평가" 구역 신설 (`dashboard.py`)**:
   - **기본 닫힘 Expander 구성**: 모든 시장/현황 탭 상단에 `st.expander("💼 MY 계좌평가 (계좌자산 및 보유잔고 상세)", expanded=False)` 형태로 배치하여 기본적으로 닫혀 있으며 사용자가 원할 때 언제든 클릭하여 펼쳐볼 수 있도록 구현.
   - **계좌 헤더 바**: 계좌번호 포맷터(`3043-6536-01`), 성명(`심재한`), 상품명(`Super365`), `[조회]` 새로고침 버튼 탑재.
   - **`◆ 계좌자산평가액` 7대 항목 테이블**: 메리츠 Open API `/accounts/v1/me/valuation`과 연동하여 원화예수금(D일), 원화예수금(D+2), 외화예수금, 유가증권평가액, 총평가액, 대출금액, 순자산평가액을 메리츠 HTS 스타일로 표시.
   - **`◆ 보유잔고내역` 2행 1레코드 테이블**: 메리츠 Open API `/accounts/v1/me/holdings`와 연동하여 1종목당 2행 구조(1행: 구분/수량/현재가/평가액/손익률/매수일/대출만기일, 2행: 종목명/매입가/전일비/평가손익/종목코드/만기일/대출금액) 구현 및 부호별 색상(수익 빨강, 손실 파랑) 적용.
   - **API 캐싱 및 마크다운 파싱 안정화**: 15초 세션 캐싱으로 중복 호출을 방지하고, HTML 들여쓰기 공백을 제거하여 마크다운 파서가 코드 블록(`<pre><code>`)으로 오인하지 않고 정상 테이블로 렌더링하도록 조치.

2. **실시간 환율 및 외환 100% 우대 환전 관리 체계 완비**:
   - **실시간 적용환율 연동**: `core/forex.py` 및 `core/brokers/meritz_us.py`에서 `fx_rates_applied`(실시간 적용환율) 1순위, `stnd_exrt`(고시환율) 2순위, 전일 대비 계산 로직을 완비하여 하루 전 환율이 표출되던 문제 해결.
   - **사이드바 환전 모드**: 3행에 "💱 환전 모드" (자동 환전 / 수동 환전) 토글 및 메리츠 스프레드 0원 이벤트 연계 배지(`🎉 환율우대 100%`) 탑재.
   - **`💱 외환/환전 관리 (Forex)` 메인 탭 신설**: 실시간 적용환율 메트릭, 원화/외화 가용예수금 카드, 실시간 수동 환전 실행 UI, 자동 환전 설정 및 환전 체결 이력 조회.

3. **모의투자 Dimming 및 시스템 운영 설정 컬럼 정렬**:
   - 메리츠 Open API가 모의투자를 미지원(HTS 전용)함에 따라 기존 코드를 삭제하지 않고 CSS로 완전 Dimming(그레이스케일, 마우스 이벤트 차단) 처리.
   - 세션 캐시나 오동작으로 모의투자가 선택되더라도 강제로 실전투자로 리셋하는 `_guard_mock_trade_mode` 콜백 적용.
   - 사이드바 "운영 모드"와 "활성 시장" 컬럼 간 높이 불일치 현상 해결 (`<style>` 태그 컨테이너 밖 분리).

4. **메리츠 공식 GitHub 저장소 (`meritz-securities/open-api`) 최신 업데이트 동기화**:
   - 공식 저장소 커밋(`init: customer distribution`) 및 최신 패치를 로컬 `open-api/` 폴더에 즉시 동기화 완료 (`env/.env` 설정 보존).
   - 보유종목 페이징(`PAGING_OK`에 `holdings`, `ovs_holdings` 추가), 긴 연속조회 키의 방화벽 차단 방지(헤더 대신 쿼리 전송), 예약 주문 성공 코드(`5620`) 정상 처리 등 핵심 개선점 반영.

5. **메리츠 일일 전산 점검 시간 (23:50 ~ 00:20) 대응 로직 구축**:
   - 증권사 일마감 및 계좌 정산 작업 시간(매일 23:50 ~ 00:20) 동안 발생하는 `BUSINESS_ERROR - 서비스 가능시간이 아닙니다` 에러 방어.
   - `is_meritz_maintenance_time()` 판별 함수를 구현하여 점검 시간대에는 불필요한 API 호출을 건너뛰고 기존 캐시/DB 잔고를 유지하여 에러 로그 폭풍 방지.
   - 대시보드 상단에 일일 시스템 점검 안내 배너 표출 및 점검 종료(00:20) 직후 자동 실시간 조회 재개.

### 5) 2026-10-18 (일) 환전 조건부 분할 자동매매 (Forex DCA/CA 전략) 및 스케줄러 심박/운영시간 고도화 내역
1. **환전 조건부 분할 자동매매 (Forex DCA & Scalping Engine / 환전 CA 전략) 엔진 구축 (`core/forex.py`)**:
   - **엔진 신설**: `ForexDcaEngine` 클래스 신설 및 싱글톤 `forex_dca_engine` 등록.
   - **시장 지표 실시간 연동**: 야후 파이낸스 기반 실시간 달러인덱스(`DXY`) 120초 캐싱 및 USD/KRW 3개월 평균 환율(`3M_AVG`) 300초 캐싱.
   - **가용 예수금 연동 (`get_account_balances`)**: 메리츠 계좌 원화(KRW), 외화(USD) 가용 잔고 및 총 자산 실시간 연동.
   - **진입(트리거) 조건**: 3개월 평균 환율(`3M_AVG`) 이하, 달러인덱스(`DXY_BELOW`) 98.0 이하, 또는 지정 목표환율(`MANUAL_TARGET`) 이하 진입.
   - **분할 매수 규칙**: 진입 후 직전 매수가 대비 **0.5%씩 하락할 때마다** 설정 단위금액($100 등) 추가 분할 매수 (최대 N회차 제한).
   - **분할 / 일괄 익절 규칙**: 평균 매수 환율 대비 **+1.0%, +2.0%, +3.0% 상승 시 각각 33%씩 순차 분할 매도(`SPLIT_3`)** 또는 **목표 수익률 도달 시 일괄 전액 매도(`FULL_TARGET`)**.

2. **외환 전략 상태 DB 테이블 및 CRUD 구현 (`core/database.py`)**:
   - `forex_strategy_state` 테이블 신설 (`init_db`): 전략 활성화 여부, 진입조건, 분할매수 회차, 누적 보유 외화, 누적 투입 원화, 평균 매수 환율, 직전 매수 환율, 익절 단계(`sell_stage`), 설정 JSON 등 영속화.
   - CRUD 함수 구현: `save_forex_strategy_state_db(strategy_id, state_dict)`, `load_forex_strategy_state_db(strategy_id)`.

3. **메리츠증권 개정 환전 운영시간 연동 및 시간 판별 로직 탑재 (`core/forex.py`)**:
   - 2026.08.24 개정 규정 반영: USD 실시간 환전 가능 시간은 **영업일 09:00 ~ 다음 날 02:00** (단, 시스템 점검시간 **23:50 ~ 00:20**은 환전 불가).
   - 판별 함수 `is_forex_available_time()` 구현 (주말, 점검시간, 비영업시간 자동 차단).
   - `ForexDcaEngine.evaluate_tick(check_time=True)`: 환전 가능 시간대 자동 검증으로 안전 매매 보장.

4. **스케줄러 2단계 외환 감시 작업 등록 (`core/scheduler.py`)**:
   - **주간/야간 세션 (`forex_dca_check_day`)**: `CronTrigger(day_of_week='mon-fri', hour='9-23', minute='*/10', timezone=KST)` 등록 (23:50 점검시간은 내부 함수에서 자동 스킵).
   - **심야 연장 세션 (`forex_dca_check_night`)**: `CronTrigger(day_of_week='tue-sat', hour='0-1', minute='*/10', timezone=KST)` 등록 (00:00~00:20 점검시간 자동 스킵, 00:20~02:00 감시).

5. **스케줄러 30초 실시간 심박(Heartbeat) 엔진 및 대시보드 프로세스 모니터링 버그 해결 (`core/scheduler.py`, `dashboard.py`)**:
   - **원인 분석**: `core/scheduler.py`의 기존 `job_heartbeat`에 DB 저장(`set_config`) 코드가 누락되었고 주기가 30분 단위여서 대시보드의 2~3분 판정 기준에 의해 "가동 중(Running)"임에도 "프로세스 응답 없음"이 표시되던 문제.
   - **조치**: 30초 주기 실시간 심박 전송 함수 `update_heartbeat()` 신설, `IntervalTrigger(seconds=30)` 등록, 스케줄러 기동(`main()`) 즉시 첫 심박 기록 보장.
   - **대시보드 UI 분리**: "프로세스 생존 상태 (`🟢 프로세스 정상 동작 중` / `🔴 프로세스 응답 없음`)"와 "운영 설정 상태 (`운영 설정: 🟢 가동 중`)"를 시각적으로 명확히 분리 표기.

6. **대시보드 `💱 외환/환전 관리 (Forex)` 탭 고도화 (`dashboard.py`)**:
   - 메리츠 100% 우대(No Spread) 배너 및 USD 실시간 환전 가능 시간(영업일 09:00 ~ 다음 날 02:00, 점검시간 23:50~00:20 제외) 안내 인포 박스 탑재.
   - 실시간 적용환율, 달러인덱스(DXY), 3개월 평균 환율 3단 메트릭 카드.
   - 원화/외화 가용 예수금 카드 및 실시간 수동 환전 계산기/발주 인터페이스.
   - 외환 DCA 전략 파라미터 설정 카드 및 "외환 조건 즉시 평가 및 1회 실행" 버튼.
   - 분할 매매 진행 현황 모니터링 카드 (회차 프로그레스 바, 누적 보유 외화, 평균 매수 환율, 현재 평가 손익률).
   - CAVR 연계 스마트 자동 환전(Auto-Funding / Profit-Harvesting) 설정 및 실시간 환전 체결 기록 뷰어.

### 6) 2026-10-23 (금) ~ 10-24 (토) 실시간 환율 수집 최적화 및 FX 견적 로그 레벨 조정
1. **환율 갱신 및 Forex DCA 스케줄러 수집 주기 최적화 (`core/scheduler.py`)**:
   - **배경 및 원인**: 실시간 고시환율 갱신(`job_update_exchange_rate`) 및 외환 분할매매 조건 감시(`job_forex_dca_check`)가 `minute='*'`(1분 간격)으로 설정되어 있어, 영업일 기준 하루 수백 회의 불필요한 증권사 OpenAPI 호출 트래픽 및 로그 과다 발생, DB(`exchange_rates`) 과다 INSERT 현상이 발생함.
   - **조치**: 주간 세션(`forex_dca_check_day`, `update_fx_rate_day`) 및 심야 연장 세션(`forex_dca_check_night`, `update_fx_rate_night`) 작업의 크론 주기를 `minute='*/10'`(10분 간격)으로 완화하여 증권사 OpenAPI 레이트 리밋 방어 및 시스템 부하/DB 누적을 대폭 경감.

2. **환전 견적 로그 레벨 하향 (`core/forex.py`)**:
   - `forex_manager.get_applied_rate()`의 단순 실시간 견적 조회 시 매번 터미널과 로그 파일에 출력되던 `💱 [FX 견적] USD 외화매수...` 로그를 `logger.info`에서 `logger.debug`로 하향 조정.
   - 스케줄러 환율 수집 시 10분 주기 정기 갱신 로그(`[FX 갱신] USD/KRW = ...`) 및 실제 환전 주문 체결(`execute_exchange`) 시의 핵심 트레이딩 로그만 명확히 표출되도록 로그 가독성 및 관제 편의성 개선.

### 7) 2026-10-24 (토) 백테스트-실전투자 DB 완전 격리 및 비정상 차수 전환 버그 해결
1. **문제 현상 및 원인 분석**:
   - **현상**: 사용자가 미국 주식 TQQQ CA 백테스트를 진행한 직후, 실전 DB의 TQQQ 전략이 0차에서 7차(`TQQQ_7차`)까지 비정상적으로 전환되고, `finished_strategy_state`에 `TQQQ_1차` ~ `TQQQ_6차` 이력이 실시간으로 기록되며 텔레그램 알림이 전송됨.
   - **원인**: `core/cavr.py`의 `CostAveragingEngine._handle_cycle_finish_and_restart` 함수에서 전량 매도 발생 시 차수 전환을 처리할 때, `self.config.use_db` 플래그 확인 없이 `finish_strategy_db()`, `get_next_strategy_name()`, `send_telegram_message()`, `save_state_db()`를 무조건 호출하도록 구현되어 있었음. 이로 인해 `use_db=False`인 백테스트 시뮬레이션 중에도 실제 운용 DB와 텔레그램으로 데이터가 유입됨.
   - 추가로 리버스 모드 진입/복귀 및 VR 빌드업 알림 일부에서 `use_db` 체크 누락, `core/backtest.py`에서 `strategy_name` 미분리 및 `detailed_trade_history_path` 공유 결함이 함께 발견됨.

2. **구현 및 조치 내역 (3중 격리 안전망 구축)**:
   - **CA/VR 엔진 분기 완비 (`core/cavr.py`)**:
     - `_handle_cycle_finish_and_restart`: `self.config.use_db == True`일 때만 DB 함수 및 텔레그램 발송을 수행하도록 엄격히 분기. `use_db == False`(백테스트)일 때는 DB 호출 없이 로컬 정규식 기반 차수 증가(`TQQQ_1차` ➔ `TQQQ_2차`) 및 로컬 임시 파일(`save_state`) 저장만 수행.
     - `_run_reverse_mode_routine` (리버스 모드 진입/복귀) 및 VR 엔진(빌드업 완료)의 텔레그램 발송에 `if self.config.use_db and not preview:` 가드 추가.
   - **백테스트 네임스페이스 및 파일 경로 완전 격리 (`core/backtest.py`)**:
     - `CAConfig` 및 `VRConfig` 생성 시 `use_db=False` 명시적 주입.
     - `strategy_name=f"BACKTEST_{symbol}_{strategy_type}"`를 부여하여 실전 전략과 네임스페이스를 완전히 분리.
     - `detailed_trade_history_path`를 `backtest_detailed_trade_history_{symbol}.csv`로 분리하여 실전 거래 내역 파일(`data/detailed_trade_history.csv`) 오염 방지.
   - **시스템 레벨 Safety Guard 탑재 (`core/database.py`)**:
     - `save_state_db` 및 `finish_strategy_db` 함수 진입부에 전략명에 `"BACKTEST"`가 포함된 경우 실제 DB 조작을 즉시 중단(Early Return)하는 안전 가드 구축.

3. **실제 DB 복구 및 검증**:
   - `finished_strategy_state` 테이블에서 백테스트 시 생성된 `TQQQ_1차` ~ `TQQQ_6차` 레코드 6건 삭제 완료.
   - `strategy_state` 테이블의 TQQQ 전략명을 기본 0차(`strategy_name=''`)로 되돌리고, 회차(T=0.0), 평단가, 잔고를 초기 상태로 복구 완료.
   - 실제 TQQQ 220일 일봉 데이터를 바탕으로 CA 백테스트를 재실행하여, 내부적으로 수차례 차수 전환이 일어나도 실제 DB의 레코드 수(`strategy_state`, `finished_strategy_state`)와 내용이 단 1건도 변하지 않음을 자동 검증 통과.

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
- [x] **3. 키움 대시보드 UI/UX 및 백테스트 전면 이식 완료**: `dashboard.py`, `core/backtest.py` 구현 및 검증 통과
- [x] **4. 런타임 오류 및 브로커/스케줄러 정합성 패치 완료**: 브로커 임포트, Streamlit 위젯 규격, 휴장일 판정 완료
- [ ] **5. 전략 초기상태(Initial State) 보완사항 정밀 점검 (내일 진행 예정)**:
  - 신규 전략 생성 시 0일차 기존 잔고 편입(`include_existing`) 계산 로직 점검
  - VR 목표 V값 초기화 공식($V_0 = \frac{Pool}{G} + \frac{E}{2\sqrt{G}}$) 및 가변 Bootstrap 모드 진입 조건 검증
  - CA 분할 매수금($\frac{Budget}{a}$) 및 회차 초기화 정합성 확인
- [ ] **6. Docker 이미지 재빌드 및 OCI Portainer 재배포**:
  - `docker buildx build --platform linux/amd64,linux/arm64 -t simji3/meritz-dashboard:latest -t simji3/meritz-scheduler:latest --push .`
  - OCI Portainer에서 `Re-pull image and redeploy` 실행하여 컨테이너 정상 기동
- [ ] **7. CAVR 실시간 주문 검증 (안전모드 -> 실거래 가동)**:
  - `MERITZ_READ_ONLY=1` 안전 상태에서 CA/VR 주문 프리뷰 및 토큰 발급 동작 확인
  - 1주 소액 테스트 후 `MERITZ_READ_ONLY=0` 전환하여 본 전략 정식 가동

