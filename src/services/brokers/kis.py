from __future__ import annotations
from typing import Dict, Any, List

from src.adapters.kis.client import KISClient
from src.adapters.kis.domestic import KISDomestic
from .base import Broker


class KISBroker:
    def __init__(self, client: KISClient, domestic: KISDomestic):
        self.client = client
        self.dom = domestic

    async def fetch_balance(self) -> Dict[str, Any]:
        return await self.dom.inquire_balance()

    async def fetch_price(self, code: str) -> float:
        try:
            p = await self.dom.inquire_price(code)
            return float(p.get("output", {}).get("stck_prpr", "0") or 0)
        except Exception as e:
            # 500 에러 등 API 오류 시 0.0 반환 (로그는 상위에서 처리)
            return 0.0

    async def fetch_prices(self, codes: List[str]) -> Dict[str, float]:
        # 기본 구현: 순차 호출(추후 병렬/배치 최적화 가능)
        result: Dict[str, float] = {}
        for c in codes:
            try:
                result[c] = await self.fetch_price(c)
            except Exception:
                result[c] = 0.0
        return result

    async def fetch_orderable_cash(self) -> Dict[str, Any]:
        return await self.dom.inquire_orderable_cash()

    async def fetch_daily_orders(self, date: str = "") -> Dict[str, Any]:
        return await self.dom.inquire_daily_orders(date)

    async def order_cash(self, code: str, qty: int, price: float | None, side: str) -> Dict[str, Any]:
        return await self.dom.order_cash(code, qty, price, side)

    async def cancel_order(self, order_id: str, code: str, qty: int) -> Dict[str, Any]:
        return await self.dom.cancel_order(order_id, code, qty)


