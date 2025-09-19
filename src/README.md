# 📊 Stock Rebalancer 사용 가이드

KIS 증권 API를 활용한 자동 주식 리밸런싱 시스템입니다.

## ✨ 주요 기능

- **자동 리밸런싱**: 목표 비중에 맞춰 자동으로 포트폴리오 조정
- **적응형 현금 관리**: 0%부터 0.5%씩 증가하여 최소한의 현금으로 계획 수립
- **미수 해결**: 음수 예수금 상황에서 자동으로 미수 해결
- **미체결 주문 관리**: 리밸런싱 전 모든 미체결 주문 취소
- **계좌별 설정**: 증권사/환경/계좌별 독립적인 리밸런싱 전략
- **스케줄링**: 자동 리밸런싱 스케줄링 (미구현)

## 🏗️ 시스템 아키텍처

```
src/
├── cli/                    # CLI 인터페이스
│   ├── main.py            # 메인 CLI 앱
│   └── commands/          # 명령어별 구현
│       ├── balance.py     # 잔고 조회
│       └── rebalance.py   # 리밸런싱 실행
├── adapters/              # 외부 API 어댑터
│   └── kis/               # KIS 증권 API
│       ├── auth.py        # 인증 관리
│       ├── client.py      # HTTP 클라이언트
│       └── domestic.py    # 국내주식 API
├── services/              # 비즈니스 로직
│   ├── brokers/           # 브로커 추상화
│   ├── portfolio.py       # 포트폴리오 관리
│   ├── rebalance_executor.py # 리밸런싱 실행
│   ├── order_canceler.py  # 주문 취소
│   └── daily_orders.py    # 일별 주문 관리
├── core/                  # 핵심 로직
│   ├── rebalance.py       # 리밸런싱 계획 수립
│   ├── cash_guard.py      # 현금 부족 방지
│   ├── models.py          # 데이터 모델
│   └── rounding.py        # 수량 반올림
├── utils/                 # 유틸리티
│   └── logging.py         # 로깅 설정
└── config.py              # 설정 관리
```

## 🚀 설치 및 설정

### 1. 환경 설정

```bash
# .env 파일 생성
cp env.example .env

# 필요한 환경변수 설정
KIS_APP_KEY_DEV=your_dev_app_key
KIS_APP_SECRET_DEV=your_dev_app_secret
KIS_ACCOUNT_8_DEV=your_dev_account
KIS_ACCOUNT_PD_DEV=your_dev_product_code

KIS_APP_KEY_PROD=your_prod_app_key
KIS_APP_SECRET_PROD=your_prod_app_secret
KIS_ACCOUNT_8_PROD=your_prod_account
KIS_ACCOUNT_PD_PROD=your_prod_product_code
```

### 2. 리밸런싱 설정

```bash
# targets 폴더에 계좌별 설정 파일 생성
mkdir -p targets/kis/dev
mkdir -p targets/kis/prod

# 예시 설정 파일 생성
cp targets.example.json targets/kis/dev/your_account.json
```

## 📖 사용법

### 기본 명령어

```bash
# 잔고 조회
python -m src.cli.main balance --env dev

# 리밸런싱 실행 (dry-run)
python -m src.cli.main rebalance --env dev

# 실제 리밸런싱 실행
python -m src.cli.main rebalance --env dev --no-dry-run

# 스케줄링 (미구현)
# python -m src.cli.main schedule --env dev
```

### 고급 옵션

```bash
# 가드 무시 (장외 시간 테스트)
python -m src.cli.main rebalance --env dev --ignore-guards

# 원본 JSON 응답 출력
python -m src.cli.main balance --env dev --raw

# 특정 설정 파일 사용
python -m src.cli.main rebalance --config targets/kis/dev/your_account.json

# 주문 간 지연 시간 설정
python -m src.cli.main rebalance --env dev --order-delay 2.0
```

## ⚙️ 설정 파일 구조

### 계좌별 설정 (`targets/kis/{env}/{account}.json`)

```json
{
  "account_info": {
    "broker": "kis",
    "env": "dev",
    "account_8": "12345678",
    "account_pd": "01",
    "description": "KIS 모의투자 계좌 (개발용)"
  },
  "rebalance_config": {
    "band_pct": 1.0,
    "order_style": "market"
  },
  "tickers": {
    "379810": 0.6,
    "458730": 0.3,
    "329750": 0.1
  }
}
```

### 필드 설명

| 필드 | 설명 | 예시 |
|------|------|------|
| `account_info.broker` | 증권사 코드 | `"kis"` |
| `account_info.env` | 환경 | `"dev"` (개발), `"prod"` (운영) |
| `account_info.account_8` | 계좌번호 앞 8자리 | `"12345678"` |
| `account_info.account_pd` | 계좌 상품코드 | `"01"` |
| `account_info.description` | 계좌 설명 | `"KIS 모의투자 계좌 (개발용)"` |
| `rebalance_config.band_pct` | 허용 밴드 (%) | `1.0` |
| `rebalance_config.order_style` | 주문 방식 | `"market"` |
| `tickers` | 종목별 목표 비중 | `{"379810": 0.6}` |

## 🔧 리밸런싱 로직

### 1. 적응형 현금 관리
- **0% 현금 보유**부터 시작하여 계획 수립 시도
- **0.5%씩 점진적 증가** (0%, 0.5%, 1.0%, 1.5%, ...)
- **계획 수립 가능한 최소 비율**에서 중단

### 2. 미수 해결 전략
- **D+2 예수금 음수** 감지 시 자동 미수 해결 모드 진입
- **최소한의 매도**로 미수 해결 (수수료 효율성)
- **미수 해결 후** 목표 비중에 맞춰 리밸런싱

### 3. 미체결 주문 관리
- **리밸런싱 시작 전** 모든 미체결 주문 취소
- **깔끔한 재계획**을 통한 안정성 확보
- **중복 주문 방지** 및 예측 가능한 실행

## 📊 실행 결과 예시

### 잔고 조회 결과
```
================ 현금/예수금 요약 ================
총 예수금: 9,952,940 원
D+1 예수금: 9,952,940 원
D+2 예수금: 4,963 원
---------------- 보유 종목 ----------------
보유 종목 수: 3
 - TIGER 미국달러단기채권액티브(329750) | 수량: 78 | 평가금액: 1,004,406 원
 - KODEX 미국나스닥100(379810) | 수량: 263 | 평가금액: 5,985,880 원
 - TIGER 미국배당다우존스(458730) | 수량: 246 | 평가금액: 2,986,932 원
```

### 리밸런싱 실행 결과
```
🔍 적응형 리밸런싱 예산 탐색 시작 (총 현금: 663,280원)
📊 현금 보유 비율 0.0% 테스트 (예산: 663,280원)
✅ 현금 보유 비율 0.0%에서 계획 수립 성공 (최종 현금: 3,385원)
🎯 최적 현금 보유 비율: 0.0% (총 1건 매수 계획)

[2025-09-19 14:16:03] Planned Orders (3):
 - SELL 329750 x 23
 - SELL 458730 x 17  
 - BUY  379810 x 29
```

## 🔒 보안 주의사항

- **개인정보 보호**: 계좌번호, API 키 등은 `.env` 파일에만 저장
- **Git 제외**: `targets/` 폴더는 `.gitignore`에 포함
- **환경 분리**: 개발/운영 환경을 명확히 구분하여 관리
- **실계좌 주의**: 운영 환경에서는 신중하게 테스트 후 실행

## 🚨 주의사항

1. **실계좌 사용 시**: 반드시 모의투자에서 충분히 테스트 후 실행
2. **장중 시간**: 실제 거래는 장중 시간에만 실행 권장
3. **수수료**: 매매 시 수수료가 발생하므로 빈번한 리밸런싱 주의
4. **API 제한**: KIS API 호출 제한을 고려한 적절한 지연 시간 설정
5. **스케줄링 기능**: 아직 실제 동작 확인이 안 된 상태로, 사용 시 주의 필요 (미구현)

## 📝 라이선스

MIT License

## 🤝 기여

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request
