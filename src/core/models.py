from pydantic import BaseModel
from typing import Optional

class Position(BaseModel):
    code: str
    qty: int
    price: float

class Target(BaseModel):
    code: str
    weight: float  # 0~1

class OrderPlan(BaseModel):
    code: str
    side: str      # BUY|SELL
    qty: int
    limit: Optional[float] = None
