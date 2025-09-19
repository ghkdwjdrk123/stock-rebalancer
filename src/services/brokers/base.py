from __future__ import annotations
from typing import Protocol, Dict, Any, List, Tuple


class Broker(Protocol):
    async def fetch_balance(self) -> Dict[str, Any]:
        """원본 잔고 JSON을 반환한다. 호출자는 필요한 값을 파싱한다."""

    async def fetch_price(self, code: str) -> float:
        """단일 종목 현재가를 반환한다. 실패 시 예외를 던진다."""

    async def fetch_prices(self, codes: List[str]) -> Dict[str, float]:
        """여러 종목 현재가를 반환한다. 기본 구현은 순차 호출로 대체 가능."""

    async def fetch_orderable_cash(self) -> Dict[str, Any]:
        """주문가능현금 조회 API 원본 JSON을 반환한다."""

    async def fetch_daily_orders(self, date: str = "") -> Dict[str, Any]:
        """일별 주문체결 조회 API 원본 JSON을 반환한다. 미체결 주문 포함."""

    async def order_cash(self, code: str, qty: int, price: float | None, side: str) -> Dict[str, Any]:
        """현금주문(시장/지정). side는 BUY|SELL."""

    async def cancel_order(self, order_id: str, code: str, qty: int) -> Dict[str, Any]:
        """미체결 주문 취소."""


