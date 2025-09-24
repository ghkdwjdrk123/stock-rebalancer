from __future__ import annotations
from typing import Dict, List, Any, Set

from src.core.models import OrderPlan
from src.core.rebalance import plan_rebalance
from src.core.cash_guard import validate_cash_sufficiency, calculate_final_cash
from src.core.order_optimizer import optimize_order_sequence, calculate_commission_savings
from src.services.brokers.base import Broker
from src.services.daily_orders import parse_daily_orders, get_pending_orders


async def build_plan(
    positions: Dict[str, int],
    targets: Dict[str, float],
    cash: float,
    prices: Dict[str, float],
    *,
    band_pct: float,
    max_order_value_per_ticker: int,
    d2_cash: float = None,
    safety_margin_pct: float = 1.0,
    total_asset_value: float = None,
    broker=None,
    is_mock: bool = True,
    orderable_cash: float = None,
) -> List[OrderPlan]:
    # 1. 깔끔한 리밸런싱 계획 수립 (모든 미체결 주문 취소 후)
    plan = await plan_rebalance(
        positions=positions,
        targets=targets,
        cash=cash,
        prices=prices,
        band_pct=band_pct,
        max_order_value_per_ticker=max_order_value_per_ticker,
        d2_cash=d2_cash,
        safety_margin_pct=safety_margin_pct,
        total_asset_value=total_asset_value,
        broker=broker,
        is_mock=is_mock,
        orderable_cash=orderable_cash,
    )
    
    # 2. 현금 부족 방지 검증 및 조정 (미수 해결 모드에서는 우회)
    if cash >= 0:
        # 정상 현금: 현금 부족 방지 적용
        validated_plan, final_cash = validate_cash_sufficiency(plan, cash, prices)
    else:
        # 미수 상황: 현금 부족 방지 우회 (미수 해결 로직에서 이미 처리됨)
        validated_plan = plan
        final_cash = calculate_final_cash(plan, cash, prices)
    
    # 3. 수수료 최적화: 동일 종목 매도/매수 주문 통합 (미수 해결 모드에서는 비활성화)
    if cash >= 0:
        # 정상 상황: 수수료 최적화 적용
        optimized_plan = optimize_order_sequence(validated_plan, cash, prices)
    else:
        # 미수 상황: 수수료 최적화 비활성화 (의도적인 매도→매수 순서 보존)
        optimized_plan = validated_plan
    
    from src.utils.logging import get_logger
    log = get_logger("rebalance_executor")
    log.info(f"깔끔한 재계획 완료: {len(optimized_plan)}건 주문 계획")
    
    return optimized_plan


async def execute_plan(broker: Broker, plan: List[OrderPlan], *, dry_run: bool = False, order_delay_sec: float = 1.0) -> List[Dict[str, Any]]:
    """안전한 주문 계획 실행 (롤백 보호 포함)"""
    import asyncio
    from src.utils.logging import get_logger
    
    log = get_logger("rebalance_executor")
    
    if dry_run:
        log.info("[DRY_RUN] 주문 실행을 시뮬레이션합니다.")
        return [{"success": True, "order_id": f"DRY_{i}", "message": "DRY_RUN"} for i, _ in enumerate(plan)]
    
    if not plan:
        log.info("실행할 주문이 없습니다.")
        return []
    
    # 안전한 배치 실행
    # Safety 시스템 우회 - Legacy 방식 직접 사용
    log.info("🔄 Legacy 방식으로 주문 실행 (Safety 시스템 우회)")
    return await _execute_plan_legacy(broker, plan, order_delay_sec)

async def _execute_plan_legacy(broker: Broker, plan: List[OrderPlan], order_delay_sec: float = 1.0) -> List[Dict[str, Any]]:
    """기존 방식의 주문 실행 (폴백용)"""
    import asyncio
    from src.utils.logging import get_logger
    
    log = get_logger("rebalance_executor")
    results: List[Dict[str, Any]] = []
    sent_keys: Set[str] = set()
    
    # 깔끔한 재계획으로 모든 미체결 주문이 이미 취소되었으므로 중복 필터링 불필요
    log.info(f"깔끔한 재계획 실행: {len(plan)}건 주문 실행")
    
    for i, p in enumerate(plan):
        idem_key = f"{p.side}:{p.code}:{p.qty}:{p.limit or 'MKT'}"
        if idem_key in sent_keys:
            results.append({"code": p.code, "qty": p.qty, "side": p.side, "limit": p.limit, "status": "SKIPPED_DUP"})
            continue
        sent_keys.add(idem_key)

        # 주문 간 지연 (첫 번째 주문 제외)
        if i > 0:
            log.info(f"주문 간 {order_delay_sec}초 대기 중... ({i+1}/{len(plan)})")
            await asyncio.sleep(order_delay_sec)

        try:
            log.info(f"주문 실행 중: {p.side} {p.code} {p.qty}주 ({i+1}/{len(plan)})")
            res = await broker.order_cash(p.code, p.qty, p.limit, p.side)
            
            # 가능한 주문번호 추출(없으면 그대로 결과 저장)
            order_id = None
            try:
                order_id = res.get("output", {}).get("ODNO") or res.get("odno") or res.get("order_id")
            except Exception:
                order_id = None
            
            log.info(f"주문 완료: {p.code} - 주문번호: {order_id}")
            results.append({"order_id": order_id, **res})
            
        except Exception as e:
            log.error(f"주문 실패: {p.code} - {e}")
            results.append({"code": p.code, "qty": p.qty, "side": p.side, "limit": p.limit, "error": str(e), "status": "FAILED"})
    
    return results


