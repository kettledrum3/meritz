# Kiwoom REST API → Meritz Open API 마이그레이션 가이드

본 문서는 `d:\Python_D\kiwoom` 프로젝트의 REST/WebSocket 기반 시스템 및 CA VR 전략 로직을 `d:\Python_D\Meritz` 프로젝트로 원활하게 이식하기 위한 기술 비교 및 매핑 문서입니다.

---

## 1. 주요 아키텍처 비교

| 항목 | Kiwoom Open API (REST) | Meritz Open API (REST & WS) | 마이그레이션 영향 / 대응 전략 |
| :--- | :--- | :--- | :--- |
| **인증 방식** | OAuth2 토큰 발급 (`/oauth2/token`) | OAuth2 토큰 발급 (`/oauth2/token`) | `meritz.client` 내부에 토큰 캐싱 및 자동 갱신 로직이 내장되어 있어 관리가 더 간소화됨 |
| **계좌 번호 전달** | 모든 계좌/주문 요청 body에 계좌번호(`cano`, `acnt_no`) 명시 | **앱키(App Key)에 계좌 자동 매핑** (요청 시 계좌번호 생략) | 계좌번호 파라미터 전송 불필요 (보내면 에러 발생). 브로커 래퍼에서 제거 처리 |
| **종목 코드 표기** | 시세/주문 동일 6자리 (`005930`) | **시세: 6자리 (`005930`)**<br>**주문: "A" 접두사 (`A005930`)** | 주문 전송 시 종목코드 앞에 `"A"` 자동 부착 로직 구현 필요 |
| **주문 안전장치** | 자체 안전장치 또는 즉시 전송 | `safety.py` 기반 **preview → confirm_token** 2단계 검증 및 `MERITZ_READ_ONLY` 플래그 | 자동매매 봇 내부에서는 브로커 래퍼가 원스톱으로 preview+send를 처리하되, 테스트 환경 보호를 위해 `MERITZ_READ_ONLY` 환경변수 연동 |
| **응답 포맷 및 판정** | `return_code == 0` | `res["ok"]` 및 `res["body"]["data"]` 존재 유무 | `res["ok"]` 성공 여부 및 `data` 필드 유무로 파싱 |
| **실시간 웹소켓** | Kiwoom WebSocket (JSON 체결/호가) | Meritz WebSocket (`wss://openapi.imeritz.com:29443/websocket`) | 포맷 및 구독 패킷 구조만 Meritz 사양으로 전환 (`open-api/asyncapi.json` 참조) |

---

## 2. Broker 인터페이스 메서드 매핑

Kiwoom의 `core/brokers/base.py` (`Broker` 클래스)를 기준으로 한 메리츠 API 매핑:

| 메서드 | Kiwoom 호출 (TR) | Meritz 카탈로그 키 / 처리 방식 |
| :--- | :--- | :--- |
| `get_price(symbol)` | `ka10001` (stkinfo) | `market_prices` (`body["data"]["stck_prpr"]`) |
| `get_previous_close(symbol)` | `ka10086` (mrkcond 일별) | `market_prices` (`prdy_vrss` 역산) 또는 `market_candles_days` |
| `get_last_5_day_avg_close(symbol)` | `ka10086` (일봉) | `market_candles_days` 최근 5거래일 종가 평균 |
| `get_current_high(symbol)` | `ka10001` (stkinfo) | `market_prices` (`body["data"]["stck_hgpr"]`) |
| `get_current_low(symbol)` | `ka10001` (stkinfo) | `market_prices` (`body["data"]["stck_lwpr"]`) |
| `get_account_equity(symbol)` | 잔고조회 | `holdings` (보유종목 리스트에서 해당 종목 매칭) |
| `get_cash_pool()` | 예수금조회 | `deposit` (`body["data"]`의 주문가능금액/예수금) |
| `place_order(...)` | `kt10000` / `kt10001` | `orders_buy` / `orders_sell` (`iscd="A"+symbol`) |
| `fetch_open_orders(symbol)` | 미체결조회 | 미체결 주문 조회 API (`orders_unexecuted` 등) |
| `fetch_execution_history(...)` | 체결내역조회 | 체결내역 조회 API |

---

## 3. CA VR 전략 로직 이식 방안

1. **전략 엔진 (`cavr.py`) 보존**:
   - `d:\Python_D\kiwoom\core\cavr.py`에 구현된 리밸런싱 공식(V값 계산, 풀 비율, 풀 밴드, 매수/매도 수량 산정)은 순수 계산 로직이므로 코드 변경 없이 그대로 이식 가능합니다.
   - 단, `kis_headers`나 키움 전용 API 직접 호출부가 있다면 `Broker` 인터페이스를 거치도록 정리합니다.

2. **Meritz Broker 클래스 개발 (`core/brokers/meritz_kr.py`)**:
   - `core/brokers/base.py`의 `Broker` 클래스를 상속받아 `MeritzKrBroker`를 구현합니다.
   - 메리츠 공식 SDK (`open-api/meritz`)를 임포트하여 `client.call(cat.get(...))` 형태로 호출합니다.

3. **데이터베이스 & 대시보드 (`database.py`, `dashboard.py`)**:
   - 기존 SQLite 스키마(`orders`, `daily_state`, `audit_log` 등)를 그대로 재사용하여 일관된 모니터링 환경을 유지합니다.
