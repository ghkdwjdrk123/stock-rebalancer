from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

def build_scheduler(job, cron: str):
    minute, hour, *_ = cron.split()
    sch = AsyncIOScheduler(timezone=ZoneInfo("Asia/Seoul"))
    sch.add_job(job, trigger="cron", minute=minute, hour=hour)
    return sch
