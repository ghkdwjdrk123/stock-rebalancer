"""
미체결 주문 취소 서비스
"""
from __future__ import annotations
from typing import Dict, List, Any
from src.services.brokers.base import Broker
from src.services.daily_orders import parse_daily_orders, get_pending_orders


async def cancel_all_pending_orders(broker: Broker) -> List[Dict[str, Any]]:
    """
    모든 미체결 주문을 취소
    
    Args:
        broker: 브로커 인스턴스
        
    Returns:
        List[Dict[str, Any]]: 취소 결과 리스트
    """
    from src.utils.logging import get_logger
    log = get_logger("order_canceler")
    
    # 1. 미체결 주문 조회
    try:
        daily_response = await broker.fetch_daily_orders()
        daily_orders = parse_daily_orders(daily_response)
        pending_orders = get_pending_orders(daily_orders)
        
        if not pending_orders:
            log.info("✅ 취소할 미체결 주문이 없습니다 - 정상 상태")
            return []
            
        log.info(f"미체결 주문 {len(pending_orders)}건 취소 시작")
        
        # 2. 모든 미체결 주문 취소
        cancel_results = []
        for order in pending_orders:
            try:
                log.info(f"주문 취소: {order.code} {order.side} {order.pending_qty}주 (주문번호: {order.order_id})")
                result = await broker.cancel_order(order.order_id, order.code, order.pending_qty)
                cancel_results.append({
                    "code": order.code,
                    "side": order.side,
                    "qty": order.pending_qty,
                    "order_id": order.order_id,
                    "result": result,
                    "success": True
                })
                log.info(f"주문 취소 완료: {order.code}")
                
            except Exception as e:
                log.error(f"주문 취소 실패: {order.code} - {e}")
                cancel_results.append({
                    "code": order.code,
                    "side": order.side,
                    "qty": order.pending_qty,
                    "order_id": order.order_id,
                    "result": None,
                    "success": False,
                    "error": str(e)
                })
        
        success_count = sum(1 for r in cancel_results if r["success"])
        log.info(f"미체결 주문 취소 완료: {success_count}/{len(pending_orders)}건 성공")
        
        return cancel_results
        
    except Exception as e:
        log.error(f"미체결 주문 취소 실패: {e}")
        return []


async def cancel_pending_buy_orders(broker: Broker) -> List[Dict[str, Any]]:
    """
    미체결 매수 주문만 취소 (미수 해결을 위해)
    
    Args:
        broker: 브로커 인스턴스
        
    Returns:
        List[Dict[str, Any]]: 취소 결과 리스트
    """
    from src.utils.logging import get_logger
    log = get_logger("order_canceler")
    
    # 1. 미체결 주문 조회
    try:
        daily_response = await broker.fetch_daily_orders()
        daily_orders = parse_daily_orders(daily_response)
        pending_orders = get_pending_orders(daily_orders)
        
        # 매수 주문만 필터링
        pending_buy_orders = [order for order in pending_orders if order.side == "BUY"]
        
        if not pending_buy_orders:
            log.info("취소할 미체결 매수 주문이 없습니다.")
            return []
            
        log.info(f"미체결 매수 주문 {len(pending_buy_orders)}건 취소 시작 (미수 해결)")
        
        # 2. 미체결 매수 주문 취소
        cancel_results = []
        for order in pending_buy_orders:
            try:
                log.info(f"매수 주문 취소: {order.code} {order.pending_qty}주 (주문번호: {order.order_id})")
                result = await broker.cancel_order(order.order_id, order.code, order.pending_qty)
                cancel_results.append({
                    "code": order.code,
                    "side": order.side,
                    "qty": order.pending_qty,
                    "order_id": order.order_id,
                    "result": result,
                    "success": True
                })
                log.info(f"매수 주문 취소 완료: {order.code}")
                
            except Exception as e:
                log.error(f"매수 주문 취소 실패: {order.code} - {e}")
                cancel_results.append({
                    "code": order.code,
                    "side": order.side,
                    "qty": order.pending_qty,
                    "order_id": order.order_id,
                    "result": None,
                    "success": False,
                    "error": str(e)
                })
        
        success_count = sum(1 for r in cancel_results if r["success"])
        log.info(f"미체결 매수 주문 취소 완료: {success_count}/{len(pending_buy_orders)}건 성공")
        
        return cancel_results
        
    except Exception as e:
        log.error(f"미체결 매수 주문 취소 실패: {e}")
        return []
