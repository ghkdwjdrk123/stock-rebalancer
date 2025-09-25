from __future__ import annotations
import typer
import asyncio
from typing import Dict, Any

from src.config import Settings
from src.utils.logging import get_logger
from src.adapters.kis.client import KISClient
from src.adapters.kis.domestic import KISDomestic
from src.services.brokers.kis import KISBroker
from src.services.daily_orders import parse_daily_orders, get_pending_orders, get_order_summary
from src.adapters.kis.api_config import is_pension_account, api_config_manager


log = get_logger("cli.pending")


async def _run(raw: bool = False, env: str = "dev"):
    """미체결 주문 조회"""
    st = Settings()
    conf = st.resolve_kis(env)
    
    # 환경 설정 검증
    missing = [k for k in ("base","app_key","app_secret","account_8","account_pd") if not str(conf.get(k) or "").strip()]
    if missing:
        log.error(f"[설정 오류] 다음 설정이 비어 있습니다: {', '.join(missing)}. .env의 {env} 환경 값을 채워주세요.")
        return
    
    # 연금계좌 제한 체크
    account_pd = conf.get("account_pd")
    if is_pension_account(account_pd):
        account_type_name = api_config_manager.get_account_type_name(account_pd)
        
        log.error(f"❌ {account_type_name}에서는 미체결 주문 조회 기능이 지원되지 않습니다.")
        log.error(f"❌ 연금계좌는 주문 기능이 제한되어 있어 미체결 주문이 발생하지 않습니다.")
        log.error(f"❌ 잔고 조회는 balance 명령어를 사용해주세요.")
        
        typer.echo(f"❌ {account_type_name}에서는 미체결 주문 조회 기능이 지원되지 않습니다.")
        typer.echo(f"❌ 연금계좌는 주문 기능이 제한되어 있어 미체결 주문이 발생하지 않습니다.")
        typer.echo(f"❌ 잔고 조회는 balance 명령어를 사용해주세요.")
        
        raise typer.Exit(1)
    
    client = KISClient(conf["base"], conf["app_key"], conf["app_secret"])
    dom = KISDomestic(client, conf["account_8"], conf["account_pd"], env=env)
    broker = KISBroker(client, dom)

    try:
        # 당일 주문체결 조회
        log.info("당일 주문체결 조회 중...")
        daily_response = await broker.fetch_daily_orders()
        
        # 주문 파싱
        daily_orders = parse_daily_orders(daily_response)
        pending_orders = get_pending_orders(daily_orders)
        summary = get_order_summary(daily_orders)
        
        # --raw 옵션이 있을 때만 원문 JSON 출력
        if raw:
            import json as _json
            typer.echo("=== 원본 API 응답 ===")
            typer.echo(_json.dumps(daily_response, ensure_ascii=False, indent=2))
            typer.echo("\n=== 파싱된 주문 목록 ===")
            typer.echo(_json.dumps([order.__dict__ for order in daily_orders], ensure_ascii=False, indent=2))
            typer.echo("\n=== 미체결 주문 목록 ===")
            typer.echo(_json.dumps([order.__dict__ for order in pending_orders], ensure_ascii=False, indent=2))
            return

        # 상세 출력 형식
        def _fmt_money(v):
            try:
                iv = int(float(v))
                return f"{iv:,} 원"
            except Exception:
                return str(v)

        # 요약 정보 출력
        typer.echo("================ 미체결 주문 조회 ================")
        typer.echo(f"전체 주문: {summary['total_orders']}건")
        typer.echo(f"미체결 주문: {summary['pending_orders']}건")
        
        if summary['pending_orders'] == 0:
            typer.echo("미체결 주문이 없습니다.")
            return

        # 미체결 주문 상세 출력
        typer.echo("\n---------------- 미체결 주문 상세 ----------------")
        for i, order in enumerate(pending_orders, 1):
            side_text = "매수" if order.side == "BUY" else "매도"
            price_text = f"{order.price:,.0f}원" if order.price else "시장가"
            
            typer.echo(f"{i}. {order.code} ({side_text})")
            typer.echo(f"   주문수량: {order.qty:,}주")
            typer.echo(f"   체결수량: {order.exec_qty:,}주")
            typer.echo(f"   미체결수량: {order.pending_qty:,}주")
            typer.echo(f"   주문가격: {price_text}")
            typer.echo(f"   주문번호: {order.order_id}")
            typer.echo(f"   주문상태: {order.order_status}")
            typer.echo(f"   체결상태: {order.exec_status}")
            typer.echo("")

        # 종목별 미체결 수량 요약
        if summary['pending_by_code']:
            typer.echo("---------------- 종목별 미체결 요약 ----------------")
            for code, sides in summary['pending_by_code'].items():
                buy_qty = sides.get('BUY', 0)
                sell_qty = sides.get('SELL', 0)
                
                if buy_qty > 0 and sell_qty > 0:
                    typer.echo(f"{code}: 매수 {buy_qty:,}주, 매도 {sell_qty:,}주")
                elif buy_qty > 0:
                    typer.echo(f"{code}: 매수 {buy_qty:,}주")
                elif sell_qty > 0:
                    typer.echo(f"{code}: 매도 {sell_qty:,}주")

        # 예상 포지션 변화
        pending_positions = summary['pending_positions']
        if pending_positions:
            typer.echo("\n---------------- 예상 포지션 변화 ----------------")
            for code, qty_change in pending_positions.items():
                if qty_change > 0:
                    typer.echo(f"{code}: +{qty_change:,}주 (매수 미체결)")
                elif qty_change < 0:
                    typer.echo(f"{code}: {qty_change:,}주 (매도 미체결)")

    except Exception as e:
        log.error(f"미체결 주문 조회 실패: {e}")
        typer.echo(f"오류가 발생했습니다: {e}")


def run(raw: bool = False, env: str = "dev"):
    """미체결 주문 조회 CLI 명령어"""
    asyncio.run(_run(raw, env))
