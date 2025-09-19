from pydantic import BaseModel
from dotenv import load_dotenv
import os
load_dotenv()

class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "dev")
    tz: str = os.getenv("TZ", "Asia/Seoul")

    # 단일(레거시) 설정
    kis_base: str = os.getenv("KIS_BASE", "")

    # 환경별(운영/모의) 설정
    kis_base_prod: str = os.getenv("KIS_BASE_PROD", "")
    kis_app_key_prod: str = os.getenv("KIS_APP_KEY_PROD", "")
    kis_app_secret_prod: str = os.getenv("KIS_APP_SECRET_PROD", "")
    kis_account_8_prod: str = os.getenv("KIS_ACCOUNT_8_PROD", "")
    kis_account_pd_prod: str = os.getenv("KIS_ACCOUNT_PD_PROD", "01")

    kis_base_dev: str = os.getenv("KIS_BASE_DEV", "")
    kis_app_key_dev: str = os.getenv("KIS_APP_KEY_DEV", "")
    kis_app_secret_dev: str = os.getenv("KIS_APP_SECRET_DEV", "")
    kis_account_8_dev: str = os.getenv("KIS_ACCOUNT_8_DEV", "")
    kis_account_pd_dev: str = os.getenv("KIS_ACCOUNT_PD_DEV", "01")

    # 레거시 키(하위 호환)
    kis_app_key: str = os.getenv("KIS_APP_KEY", "")
    kis_app_secret: str = os.getenv("KIS_APP_SECRET", "")
    kis_account_8: str = os.getenv("KIS_ACCOUNT_8", "")
    kis_account_pd: str = os.getenv("KIS_ACCOUNT_PD", "01")

    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"
    default_band_pct: float = float(os.getenv("DEFAULT_BAND_PCT", "1.0"))
    default_order_style: str = os.getenv("DEFAULT_ORDER_STYLE", "market")
    max_order_value_per_ticker: int = int(os.getenv("MAX_ORDER_VALUE_PER_TICKER", "10000000"))

    # 토큰 캐시/리프레시 설정
    token_cache_path: str = os.getenv("KIS_TOKEN_CACHE_PATH", "token/kis.json")
    token_refresh_leeway_sec: int = int(os.getenv("KIS_TOKEN_REFRESH_LEEWAY_SEC", "600"))
    
    # CLI 기본 설정
    default_config_file: str = os.getenv("DEFAULT_CONFIG_FILE", "targets.example.json")
    default_cron_schedule: str = os.getenv("DEFAULT_CRON_SCHEDULE", "20 15 * * 1-5")
    default_order_delay: float = float(os.getenv("DEFAULT_ORDER_DELAY", "1.0"))
    
    # DRY_RUN 샘플 데이터 설정
    default_dry_run_price: float = float(os.getenv("DEFAULT_DRY_RUN_PRICE", "100000.0"))
    default_dry_run_cash: float = float(os.getenv("DEFAULT_DRY_RUN_CASH", "1000000.0"))
    default_dry_run_qty: int = int(os.getenv("DEFAULT_DRY_RUN_QTY", "1"))
    
    # 캐시 설정
    marketstatus_cache_ttl_sec: float = float(os.getenv("KIS_MARKETSTATUS_CACHE_TTL_SEC", "60.0"))
    
    # === 거래 안전장치 설정 ===
    trading_safety_enabled: bool = bool(os.getenv("TRADING_SAFETY_ENABLED", "true").lower() == "true")
    trading_max_retry_attempts: int = int(os.getenv("TRADING_MAX_RETRY_ATTEMPTS", "3"))
    trading_retry_delay: float = float(os.getenv("TRADING_RETRY_DELAY", "1.0"))
    trading_checkpoint_enabled: bool = bool(os.getenv("TRADING_CHECKPOINT_ENABLED", "false").lower() == "true")
    trading_conservative_mode: bool = bool(os.getenv("TRADING_CONSERVATIVE_MODE", "true").lower() == "true")
    trading_partial_execution_threshold: float = float(os.getenv("TRADING_PARTIAL_EXECUTION_THRESHOLD", "0.7"))
    
    # === 지속적 재시도 설정 ===
    persistent_retry_enabled: bool = bool(os.getenv("PERSISTENT_RETRY_ENABLED", "true").lower() == "true")
    retry_max_attempts: int = int(os.getenv("RETRY_MAX_ATTEMPTS", "5"))
    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "2.0"))
    retry_max_delay: float = float(os.getenv("RETRY_MAX_DELAY", "60.0"))
    retry_backoff_multiplier: float = float(os.getenv("RETRY_BACKOFF_MULTIPLIER", "1.5"))
    retry_jitter_enabled: bool = bool(os.getenv("RETRY_JITTER_ENABLED", "true").lower() == "true")
    retry_success_threshold: float = float(os.getenv("RETRY_SUCCESS_THRESHOLD", "0.8"))
    retry_max_duration_minutes: int = int(os.getenv("RETRY_MAX_DURATION_MINUTES", "30"))
    
    
    def get_token_cache_path(self, env: str) -> str:
        """환경별 토큰 캐시 경로 반환"""
        base_path = self.token_cache_path
        if base_path.endswith('.json'):
            base_path = base_path[:-5]  # .json 제거
        return f"{base_path}_{env}.json"

    def resolve_kis(self, env: str) -> dict:
        """env in {"prod","production","real"} or {"dev","demo","sandbox","mock"}

        하위 호환: 해당 env 키가 비어 있으면 레거시 단일 설정을 사용한다.
        """
        key = (env or "").strip().lower()
        if key in ("prod", "production", "real", "live"):
            base = self.kis_base_prod or self.kis_base
            return {
                "base": base,
                "app_key": self.kis_app_key_prod or self.kis_app_key,
                "app_secret": self.kis_app_secret_prod or self.kis_app_secret,
                "account_8": self.kis_account_8_prod or self.kis_account_8,
                "account_pd": self.kis_account_pd_prod or self.kis_account_pd,
            }
        # default: dev/sandbox
        base = self.kis_base_dev or self.kis_base
        return {
            "base": base,
            "app_key": self.kis_app_key_dev or self.kis_app_key,
            "app_secret": self.kis_app_secret_dev or self.kis_app_secret,
            "account_8": self.kis_account_8_dev or self.kis_account_8,
            "account_pd": self.kis_account_pd_dev or self.kis_account_pd,
        }