from __future__ import annotations
import time, httpx
from pydantic import BaseModel
from pathlib import Path
import json
from typing import Optional
from src.config import Settings

class Token(BaseModel):
    access_token: str
    expires_at: float

async def issue_token(base: str, appkey: str, appsecret: str) -> Token:
    url = f"{base}/oauth2/tokenP"
    payload = {"grant_type": "client_credentials", "appkey": appkey, "appsecret": appsecret}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        expires_in = float(data.get("expires_in", 3600.0))
        return Token(access_token=data["access_token"], expires_at=time.time() + expires_in)


def load_cached_token(path: str) -> Optional[Token]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return Token(**data)
    except Exception:
        return None


def save_cached_token(path: str, token: Token) -> None:
    try:
        p = Path(path)
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(token.model_dump(), f, ensure_ascii=False)
    except Exception:
        pass
