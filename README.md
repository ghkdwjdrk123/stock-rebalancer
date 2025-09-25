# 📈 KIS Stock Rebalancer

한국투자증권 OpenAPI를 활용한 자동 주식 포트폴리오 리밸런싱 시스템입니다.

## ✨ 주요 기능

### 🔍 계좌 조회
- **잔고 조회**: 현재 보유 종목 및 예수금 조회
- **미체결 주문 조회**: 당일 미체결 주문 현황 확인
- **계좌 유형별 지원**: 일반 위탁계좌, 연금계좌 자동 감지

### ⚖️ 자동 리밸런싱
- **포트폴리오 레벨 밴드**: 가상 전량 청산 기반 정확한 비중 조정
- **순복합 델타**: 동일 종목 매도/매수 중복 방지로 수수료 절약
- **미수금 처리**: 현금 부족 상황에서의 안전한 리밸런싱
- **안전여유율**: 설정 가능한 현금 보유율로 리스크 관리

### 🛡️ 안전장치
- **환경별 분리**: 모의투자/실전 환경 완전 분리
- **계좌 유형별 제한**: 연금계좌 주문 기능 자동 차단
- **영업일/장중 가드**: 거래 시간 외 실행 방지
- **레이트리밋**: API 호출 제한으로 안정성 확보

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 저장소 클론
git clone <repository-url>
cd kis-rebalancer

# 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일을 생성하고 KIS OpenAPI 정보를 입력하세요:

```env
# === 기본 인증 정보 ===
# 모의투자 환경
KIS_BASE_DEV=https://openapivts.koreainvestment.com:29443
KIS_APP_KEY_DEV=모의투자_앱키
KIS_APP_SECRET_DEV=모의투자_시크릿
KIS_ACCOUNT_8_DEV=계좌번호_앞8자리
KIS_ACCOUNT_PD_DEV=01

# 실전 환경
KIS_BASE_PROD=https://openapi.koreainvestment.com:9443
KIS_APP_KEY_PROD=실전_앱키
KIS_APP_SECRET_PROD=실전_시크릿
KIS_ACCOUNT_8_PROD=계좌번호_앞8자리
KIS_ACCOUNT_PD_PROD=01

# === TR_ID 설정 ===
# 일반 위탁계좌 - 개발환경
KIS_TR_BALANCE_DEV=VTTC8434R
KIS_TR_DAILY_ORDERS_DEV=VTTC8001R
KIS_TR_ORDERABLE_CASH_DEV=VTTC8407R
KIS_TR_ORDER_BUY_DEV=VTTC0802U
KIS_TR_ORDER_SELL_DEV=VTTC0801U
KIS_TR_ORDER_CANCEL_DEV=VTTC0803U
KIS_TR_PRICE_DEV=JTPT1002R

# 일반 위탁계좌 - 운영환경
KIS_TR_BALANCE_PROD=TTTC8434R
KIS_TR_DAILY_ORDERS_PROD=TTTC8001R
KIS_TR_ORDERABLE_CASH_PROD=TTTC8407R
KIS_TR_ORDER_BUY_PROD=TTTC0802U
KIS_TR_ORDER_SELL_PROD=TTTC0801U
KIS_TR_ORDER_CANCEL_PROD=TTTC0803U
KIS_TR_PRICE_PROD=JTPT1002R
```

### 3. 리밸런싱 설정

`targets/kis/{env}/{account_id}.json` 파일을 생성하고 목표 비중을 설정하세요:

```json
{
  "account_info": {
    "broker": "kis",
    "env": "dev",
    "account_8": "XXXXXXXX",
    "account_pd": "01",
    "description": "모의투자 계좌"
  },
  "rebalance_config": {
    "band_pct": 1.0,
    "order_style": "market",
    "safety_margin_pct": 0.5
  },
  "tickers": {
    "379810": 0.60,
    "458730": 0.30,
    "329750": 0.10
  }
}
```

## 📋 사용법

### 계좌 조회

```bash
# 잔고 조회
python -m src.cli.main balance --env dev

# 미체결 주문 조회
python -m src.cli.main pending --env dev

# 원문 JSON 출력
python -m src.cli.main balance --env dev --raw
```

### 리밸런싱 실행

```bash
# 시뮬레이션 (안전)
python -m src.cli.main rebalance --env dev --dry-run

# 실제 실행 (모의투자)
python -m src.cli.main rebalance --env dev --no-dry-run

# 실제 실행 (실전 - 장시간 내만)
python -m src.cli.main rebalance --env prod --no-dry-run
```

### 고급 옵션

```bash
# 영업일 가드 무시 (테스트용)
python -m src.cli.main rebalance --env dev --no-dry-run --ignore-guards

# 지속적 재시도 활성화
python -m src.cli.main rebalance --env dev --no-dry-run --persistent-retry --retry-threshold 0.8

# 엄격한 취소 모드 (미체결 주문 취소 실패 시 전체 중단)
python -m src.cli.main rebalance --env dev --no-dry-run --strict-cancellation

# 주문 간 지연 시간 조정 (초)
python -m src.cli.main rebalance --env dev --no-dry-run --order-delay 2.0

# 원문 JSON 출력
python -m src.cli.main rebalance --env dev --dry-run --raw
```

## 🏗️ 시스템 아키텍처

### 3단계 분기 처리

1. **증권사 분기**: KIS 전용 (확장 가능)
2. **모의/운영환경 분기**: 자동 환경 감지 및 API 분리
3. **계좌상품별 분기**: 일반계좌/연금계좌 자동 감지 및 기능 제한

### 계좌 유형별 지원

| 기능 | 일반계좌 (01) | 연금계좌 (22) |
|------|---------------|---------------|
| **Balance** | ✅ 정상 | ✅ 정상 |
| **Pending** | ✅ 정상 | ❌ 차단 |
| **Rebalance (dry-run)** | ✅ 정상 | ✅ 정상 |
| **Rebalance (no-dry-run)** | ✅ 정상 | ❌ 차단 |

## 🔧 고급 기능

### 포트폴리오 레벨 밴드

- **가상 전량 청산**: 현재 주식을 모두 매도한다고 가정하고 목표 비중으로 재구성
- **개별 종목 밴드**: 각 종목이 목표 비중 대비 ±`band_pct` 범위 내 유지
- **전체 합 보장**: 포트폴리오 전체 비중이 100% 유지
- **순복합 델타**: 동일 종목 매도/매수 중복 방지

### 미수금 처리

- **자동 감지**: `D+2 예수금 < 0` 또는 `주문가능현금 < 0` 상황 감지
- **가상 전량 청산**: 보유 주식 매도로 미수금 해결
- **잔여 현금 리밸런싱**: 남은 현금으로 목표 비중 재구성

### 안전여유율

- **설정 가능**: `safety_margin_pct`로 현금 보유율 조정 (기본 0.5%)
- **리스크 관리**: 전체 자산 기준으로 안전 현금 확보
- **모의투자 최적화**: 실전과 유사한 현금 관리

## 📁 프로젝트 구조

```
kis-rebalancer/
├── src/
│   ├── cli/                    # CLI 명령어
│   │   ├── main.py            # 메인 진입점
│   │   └── commands/          # 개별 명령어
│   ├── core/                  # 핵심 로직
│   │   ├── rebalance.py      # 리밸런싱 알고리즘
│   │   └── models.py         # 데이터 모델
│   ├── services/              # 서비스 레이어
│   │   ├── brokers/          # 증권사 어댑터
│   │   ├── portfolio.py      # 포트폴리오 관리
│   │   └── trading_safety.py # 거래 안전장치
│   ├── adapters/             # 외부 API 어댑터
│   │   └── kis/              # KIS OpenAPI
│   └── utils/                # 유틸리티
├── targets/                   # 리밸런싱 설정
│   └── kis/                  # KIS 설정
│       ├── dev/              # 모의투자
│       └── prod/             # 실전
├── rules/                    # 개발 규칙 및 문서
└── requirements.txt          # 의존성
```

## ⚠️ 주의사항

### 보안
- **환경변수 보호**: `.env` 파일을 git에 커밋하지 마세요
- **토큰 관리**: `token/` 폴더는 자동으로 gitignore 처리됩니다
- **IP 화이트리스트**: 실전 환경에서는 IP 등록이 필요합니다

### 거래 제한
- **연금계좌**: 조회 기능만 지원, 주문 기능 자동 차단
- **장시간 제한**: 실전 환경에서는 장시간 내에만 주문 가능
- **안전장치**: 미체결 주문 취소, 레이트리밋, 영업일 가드 등 다중 안전장치 적용

### 설정 검증
- **비중 합계**: 목표 비중의 합은 반드시 1.0 (100%)이어야 합니다
- **계좌 정보**: `account_8`은 8자리, `account_pd`는 올바른 상품코드여야 합니다
- **환경 일치**: `--env` 옵션과 실제 계좌 환경이 일치해야 합니다

## 🐛 문제 해결

### 자주 발생하는 오류

1. **TR_ID not found**
   - `.env` 파일에 해당 TR_ID 환경변수가 설정되었는지 확인
   - 환경(dev/prod)과 TR_ID가 일치하는지 확인

2. **401 Unauthorized**
   - 앱키/시크릿이 올바른지 확인
   - 토큰 캐시 삭제 후 재실행: `rm token/kis_*.json`

3. **500 Internal Server Error**
   - KIS 서버 일시적 문제 (자동 재시도됨)
   - 계좌 정보 유효성 확인

4. **연금계좌 주문 차단**
   - 연금계좌는 조회 기능만 지원됩니다
   - 일반 위탁계좌를 사용하세요

## 📚 추가 문서

- **개발 규칙**: `rules/` 폴더의 .mdc 파일들 참조
- **리밸런싱 로직**: `rules/rebalance.mdc` 상세 설명
- **API 설정**: `rules/common.mdc` 환경변수 가이드
- **잔고 조회**: `rules/balance.mdc` 조회 기능 설명

## 🤝 기여하기

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


---

**⚠️ 면책 조항**: 이 도구는 교육 및 개인 사용 목적으로만 제공됩니다. 실제 투자에 사용할 때는 충분한 테스트와 검증을 거치시기 바랍니다. 투자 손실에 대한 책임은 사용자에게 있습니다.