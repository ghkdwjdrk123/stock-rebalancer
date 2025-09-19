# src/services/guards.py
from __future__ import annotations
from datetime import datetime, date
from zoneinfo import ZoneInfo
import os
from src.adapters.kis.client import KISClient
from src.config import Settings

KST = ZoneInfo("Asia/Seoul")

# MARKETSTATUS 캐시 (TTL: Settings에서 설정)
_MKT_CACHE: dict[str, tuple[float, dict]] = {}
settings = Settings()
_MKT_TTL_SEC = settings.marketstatus_cache_ttl_sec

def is_regular_session(now: datetime | None = None) -> bool:
    """단순 시간 가드(백업용). 정식 가드는 아래 API 기반 함수를 사용."""
    now = now or datetime.now(tz=KST)
    if now.weekday() >= 5:
        return False
    return 9 <= now.hour < 15 or (now.hour == 15 and now.minute <= 30)

def _env_key(env: str | None) -> str:
    e = (env or "dev").strip().lower()
    return "PROD" if e in ("prod", "production", "real", "live") else "DEV"

async def _get_market_status(client: KISClient, env: str | None = None) -> dict:
    import time
    key = _env_key(env)
    now = time.monotonic()
    cached = _MKT_CACHE.get(key)
    if cached and (now - cached[0] < _MKT_TTL_SEC):
        return cached[1]
    path = os.getenv("KIS_PATH_MARKETSTATUS")
    env_suffix = _env_key(env)
    tr   = os.getenv(f"KIS_TR_MARKETSTATUS_{env_suffix}", os.getenv("KIS_TR_MARKETSTATUS"))
    if not path or not tr:
        data: dict = {}
    else:
        data = await client.get(path, tr_id=tr, params={})
    _MKT_CACHE[key] = (now, data)
    return data

async def is_trading_day(client: KISClient, d: date | None = None, env: str | None = None) -> bool:
    """영업일 판단.
    - dev: 한국 공휴일 라이브러리(있으면) + 평일 판단. 없으면 평일만.
    - prod: 장운영 상태 API 기반.
    """
    d = d or datetime.now(tz=KST).date()
    env_key = _env_key(env)
    if env_key == "DEV":
        # Try python-holidays (KR)
        try:
            import holidays  # type: ignore
            kr_holidays = holidays.country_holidays("KR")  # type: ignore
            is_business = (d.weekday() < 5) and (d not in kr_holidays)
            return bool(is_business)
        except Exception:
            # Fallback: 평일만 영업일로 간주
            return d.weekday() < 5
    # PROD: MARKETSTATUS 사용
    try:
        data = await _get_market_status(client, env=env)
        stat = (data.get("output", {}) or {}).get("mkt_stat", "OPEN")
        s = str(stat).upper()
        return s in ("OPEN", "TRADING")
    except Exception:
        return True

async def is_market_open_now(client: KISClient, now: datetime | None = None, env: str | None = None) -> bool:
    """장운영정보 기반 정규장 판단.
    - dev: 영업일(휴일 제외) + 시간 가드
    - prod: MARKETSTATUS API
    """
    now = now or datetime.now(tz=KST)
    env_key = _env_key(env)
    if env_key == "DEV":
        # dev에서는 API 호출 없이 로컬 판정
        is_bday = await is_trading_day(client, d=now.date(), env=env)
        return is_bday and is_regular_session(now)
    try:
        data = await _get_market_status(client, env=env)
        stat = (data.get("output", {}) or {}).get("mkt_stat", "OPEN")
        return str(stat).upper() in ("OPEN", "TRADING")
    except Exception:
        return is_regular_session(now)
