# 📋 리밸런싱 설정 관리

이 폴더는 **증권사별, 환경별, 계좌별**로 리밸런싱 비율을 체계적으로 관리합니다.

## 📁 폴더 구조

```
targets/
├── kis/                    # KIS 증권사 설정
│   ├── dev/               # 개발 환경 (모의투자)
│   │   └── XXXXXXXX.json  # 계좌별 리밸런싱 설정
│   └── prod/              # 운영 환경 (실계좌)
│       └── XXXXXXXX.json  # 계좌별 리밸런싱 설정
└── README.md              # 이 파일
```

## 🔧 설정 파일 형식

### 계좌별 설정 파일 (`{account_8}.json`)

```json
{
  "account_info": {
    "broker": "kis",
    "env": "dev",
    "account_8": "XXXXXXXX",
    "account_pd": "XX",
    "description": "KIS 모의투자 계좌 (개발용)"
  },
  "rebalance_config": {
    "band_pct": 1.0,
    "order_style": "market"
  },
  "tickers": {
    "XXXXXXXX": 0.6,
    "XXXXXXXX": 0.3,
    "XXXXXXXX": 0.1
  }
}
```

### 필드 설명

| 필드 | 설명 | 예시 |
|------|------|------|
| `account_info.broker` | 증권사 코드 | `"kis"` |
| `account_info.env` | 환경 | `"dev"` (개발), `"prod"` (운영) |
| `account_info.account_8` | 계좌번호 앞 8자리 | `"XXXXXXXX"` |
| `account_info.account_pd` | 계좌 상품코드 | `"XX"` |
| `account_info.description` | 계좌 설명 | `"KIS 모의투자 계좌 (개발용)"` |
| `rebalance_config.band_pct` | 허용 밴드 (%) | `1.0` |
| `rebalance_config.order_style` | 주문 방식 | `"market"` |
| `tickers` | 종목별 목표 비중 | `{"XXXXXXXX": 0.6}` |

## 🚀 사용법

### 자동 설정 파일 선택

```bash
# 개발 환경 (자동으로 targets/kis/dev/XXXXXXXX.json 선택)
python -m src.cli.main rebalance --env dev

# 운영 환경 (자동으로 targets/kis/prod/XXXXXXXX.json 선택)
python -m src.cli.main rebalance --env prod
```

### 수동 설정 파일 지정

```bash
# 특정 설정 파일 직접 지정
python -m src.cli.main rebalance --config targets/kis/dev/XXXXXXXX.json
```

## ➕ 새로운 계좌 추가

1. **새 계좌 설정 파일 생성**:
   ```bash
   # 예: 새로운 모의투자 계좌
   cp targets/kis/dev/XXXXXXXX.json targets/kis/dev/NEW_ACCOUNT.json
   ```

2. **설정 파일 내용 수정**:
   - `account_8`: 새로운 계좌번호 앞 8자리
   - `account_pd`: 새로운 계좌 상품코드
   - `description`: 계좌 설명
   - `tickers`: 해당 계좌의 리밸런싱 비율

3. **환경변수 업데이트** (`.env` 파일):
   ```bash
   KIS_ACCOUNT_8_DEV=NEW_ACCOUNT
   KIS_ACCOUNT_PD_DEV=01
   ```

## 🔄 기존 설정 파일 마이그레이션

기존 `targets.example.json`을 새로운 구조로 마이그레이션하려면:

```bash
# 1. 기존 설정 확인
cat targets.example.json

# 2. 새 계좌 설정 파일 생성 (위의 형식 참고)
# 3. 기존 파일은 백업용으로 보관
```

## 📝 주의사항

- **계좌번호는 반드시 8자리**여야 합니다
- **비중의 합은 1.0**이어야 합니다 (100%)
- **환경별 설정**을 명확히 구분하여 관리하세요
- **실계좌 설정**은 신중하게 검토 후 적용하세요
