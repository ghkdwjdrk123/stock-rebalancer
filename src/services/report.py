from __future__ import annotations
from typing import List
from datetime import datetime
from zoneinfo import ZoneInfo
from src.core.models import OrderPlan

KST = ZoneInfo("Asia/Seoul")

def format_plan(plans: List[OrderPlan]) -> str:
    ts = datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{ts}] Planned Orders ({len(plans)}):"]
    for p in plans:
        lines.append(f" - {p.side:<4} {p.code} x {p.qty}" + (f" @ {p.limit}" if p.limit else ""))
    return "\n".join(lines)
