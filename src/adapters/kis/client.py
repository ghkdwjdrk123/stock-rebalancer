# src/adapters/kis/client.py
from __future__ import annotations
import time, httpx, asyncio, random, os
from typing import Any, Dict
from src.adapters.kis.auth import issue_token, Token, load_cached_token, save_cached_token
from src.config import Settings
from src.utils.ratelimit import AsyncRateLimiter

# 지수 백오프(지터 포함) 헬퍼
def _expo_backoff(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    # 0.5, 1, 2, 4, 8 ... + 약간의 랜덤 지터
    delay = min(base * (2 ** max(0, attempt - 1)), cap)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter

def _is_transient_status(code: int) -> bool:
    return code in (429, 500, 502, 503, 504)

class KISClient:
    def __init__(self, base: str, appkey: str, appsecret: str, env: str = "dev"):
        self.base = base.rstrip("/")
        self.appkey = appkey
        self.appsecret = appsecret
        self.env = env
        self._tk: Token | None = None
        self._lock = asyncio.Lock()
        st = Settings()
        self._token_cache_path = st.get_token_cache_path(env)
        self._token_refresh_leeway_sec = st.token_refresh_leeway_sec
        # 보수적 레이트리밋(기본: 초당 5회, 분당 200회)
        self._rl_get = AsyncRateLimiter(per_second=int(os.getenv("KIS_GET_RPS", 5)), per_minute=int(os.getenv("KIS_GET_RPM", 200)))
        self._rl_post = AsyncRateLimiter(per_second=int(os.getenv("KIS_POST_RPS", 5)), per_minute=int(os.getenv("KIS_POST_RPM", 100)))
        # 프로세스 시작 시 캐시 로드
        cached = load_cached_token(self._token_cache_path)
        if cached and cached.expires_at - time.time() > self._token_refresh_leeway_sec:
            self._tk = cached

    async def _ensure_token(self):
        # 만료 임박(리프레시 여유시간 이내) 또는 미보유 시 발급
        if not self._tk or self._tk.expires_at - time.time() < self._token_refresh_leeway_sec:
            async with self._lock:
                if not self._tk or self._tk.expires_at - time.time() < self._token_refresh_leeway_sec:
                    self._tk = await issue_token(self.base, self.appkey, self.appsecret)
                    save_cached_token(self._token_cache_path, self._tk)

    def _auth_headers(self, tr_id: str) -> Dict[str, str]:
        return {
            "authorization": f"Bearer {self._tk.access_token}",
            "appkey": self.appkey, "appsecret": self.appsecret,
            "tr_id": tr_id,
            # KIS 권장: 개인 사용자는 custtype=P 명시
            "custtype": "P",
            # 수용성 개선: 응답 포맷 명시
            "accept": "application/json",
        }

    async def _request_once(self, method: str, path: str, tr_id: str, **kwargs):
        await self._ensure_token()
        headers = kwargs.pop("headers", {}) | self._auth_headers(tr_id)
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{self.base}{path}", headers=headers, **kwargs)
            # 401/403 → 토큰 재발급 후 1회 재시도
            if r.status_code in (401, 403):
                async with self._lock:
                    self._tk = await issue_token(self.base, self.appkey, self.appsecret)
                    save_cached_token(self._token_cache_path, self._tk)
                    headers = kwargs.get("headers", {}) | self._auth_headers(tr_id)
                r = await client.request(method, f"{self.base}{path}", headers=headers, **kwargs)
            r.raise_for_status()
            return r

    async def get(self, path: str, tr_id: str, params: Dict[str, Any] | None = None, max_attempts: int = 5):
        attempt = 1
        while True:
            try:
                await self._rl_get.acquire()
                r = await self._request_once("GET", path, tr_id, params=params or {})
                # 429/5xx는 지수 백오프로 재시도
                if _is_transient_status(r.status_code) and attempt < max_attempts:
                    await asyncio.sleep(_expo_backoff(attempt))
                    attempt += 1
                    continue
                return r.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if _is_transient_status(code) and attempt < max_attempts:
                    await asyncio.sleep(_expo_backoff(attempt))
                    attempt += 1
                    continue
                raise

    async def post(self, path: str, tr_id: str, body: Dict[str, Any], need_hash: bool = False, max_attempts: int = 3):
        # 주문은 제한적 재시도 (500 에러만, 중복 주문 위험 최소화)
        await self._ensure_token()
        await self._rl_post.acquire()
        headers = self._auth_headers(tr_id) | {"content-type": "application/json"}
        
        if need_hash:
            url = f"{self.base}/uapi/hashkey"
            async with httpx.AsyncClient(timeout=10) as client:
                h = await client.post(url, headers={"appkey": self.appkey, "appsecret": self.appsecret}, json=body)
                h.raise_for_status()
                data = h.json()
                headers["hashkey"] = data.get("HASH", data.get("hash", ""))
        
        attempt = 1
        while True:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.post(f"{self.base}{path}", headers=headers, json=body)
                    r.raise_for_status()
                    return r.json()
            except httpx.HTTPStatusError as e:
                # 500 에러만 재시도 (중복 주문 위험 최소화)
                if e.response.status_code == 500 and attempt < max_attempts:
                    delay = _expo_backoff(attempt)
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise
