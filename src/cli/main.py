from __future__ import annotations
import asyncio, json
import typer
from typing import Dict, Optional
from src.utils.logging import get_logger
from src.config import Settings

app = typer.Typer(help="KIS Rebalancer CLI")
log = get_logger("cli")

# 공통 옵션
raw_option = typer.Option(False, "--raw", help="원본 JSON 응답을 그대로 출력")
env_option = typer.Option("dev", "--env", help="환경(dev|prod)")

# Settings 인스턴스 생성
settings = Settings()


@app.command()
def rebalance(config: str = typer.Option(None, "--config", help="설정 파일 경로 (미지정시 자동 선택)"), env: str = env_option, raw: bool = raw_option, dry_run: bool = True, ignore_guards: bool = typer.Option(False, help="영업일/장중 가드 무시"), order_delay: float = typer.Option(settings.default_order_delay, "--order-delay", help="주문 간 지연 시간(초)"), safety_mode: str = typer.Option("conservative", "--safety-mode", help="거래 안전 모드 (conservative|checkpoint|legacy)"), strict_cancellation: bool = typer.Option(True, "--strict-cancellation", help="미체결 주문 취소 실패 시 전체 중단"), persistent_retry: bool = typer.Option(True, "--persistent-retry", help="이상 감지 시 지속적 재시도"), retry_threshold: float = typer.Option(0.8, "--retry-threshold", help="재시도 성공 임계값 (0.0-1.0)")):
    from src.cli.commands.rebalance import run as run_rebalance, find_targets_config
    
    # config가 지정되지 않은 경우 자동으로 적절한 설정 파일 선택
    if config is None:
        config = find_targets_config(env, "kis")
        typer.echo(f"🔍 자동 선택된 설정 파일: {config}")
    
    run_rebalance(config, dry_run, env, ignore_guards, raw, order_delay, safety_mode, strict_cancellation, persistent_retry, retry_threshold)


@app.command()
def balance(raw: bool = raw_option, env: str = env_option):
    from src.cli.commands.balance import run as run_balance
    run_balance(raw, env)


@app.command()
def pending(raw: bool = raw_option, env: str = env_option):
    """미체결 주문 조회"""
    from src.cli.commands.pending import run as run_pending
    run_pending(raw, env)


@app.command()
def schedule(config: str = settings.default_config_file, cron: str = settings.default_cron_schedule, env: str = env_option, raw: bool = raw_option, order_delay: float = typer.Option(settings.default_order_delay, "--order-delay", help="주문 간 지연 시간(초)")):
    # 기존 스케줄러는 내부에서 _rebalance_once를 호출했으나, 이제는 커맨드 러너를 호출
    from src.services.schedule import build_scheduler
    from src.cli.commands.rebalance import _run as _rebalance_async
    async def job():
        await _rebalance_async(config, dry_run=False, env=env, ignore_guards=False, raw=raw, order_delay=order_delay)
    sch = build_scheduler(lambda: asyncio.create_task(job()), cron)
    sch.start()
    typer.echo("스케줄러 시작. Ctrl+C 종료")
    import asyncio
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    app()
