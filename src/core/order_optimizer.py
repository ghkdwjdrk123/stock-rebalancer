"""
주문 수수료 최적화를 위한 모듈
"""
from __future__ import annotations
from typing import Dict, List, Tuple
from src.core.models import OrderPlan


def optimize_order_sequence(plan: List[OrderPlan], cash: float, prices: Dict[str, float]) -> List[OrderPlan]:
    """
    주문 순서를 최적화하여 수수료를 줄입니다.
    
    최적화 전략:
    1. 동일 종목의 매도/매수 주문이 있으면 순매수/순매도로 통합
    2. 현금 부족 시 매도 주문을 먼저 실행
    3. 불필요한 주문 제거 (순매수량이 0인 경우)
    
    Args:
        plan: 원본 주문 계획
        cash: 초기 현금
        prices: 종목별 가격
        
    Returns:
        List[OrderPlan]: 최적화된 주문 계획
    """
    if not plan:
        return plan
    
    # 1. 동일 종목의 매도/매수 주문을 통합
    net_orders = _calculate_net_orders(plan)
    
    # 2. 현금 부족 방지를 위한 주문 순서 최적화
    optimized_plan = _optimize_cash_flow(net_orders, cash, prices)
    
    return optimized_plan


def _calculate_net_orders(plan: List[OrderPlan]) -> List[OrderPlan]:
    """
    동일 종목의 매도/매수 주문을 순매수/순매도로 통합
    """
    net_positions: Dict[str, int] = {}
    
    # 각 종목별 순매수량 계산
    for order in plan:
        if order.side == "BUY":
            net_positions[order.code] = net_positions.get(order.code, 0) + order.qty
        elif order.side == "SELL":
            net_positions[order.code] = net_positions.get(order.code, 0) - order.qty
    
    # 순매수/순매도 주문 생성
    net_orders = []
    for code, net_qty in net_positions.items():
        if net_qty > 0:
            # 순매수
            net_orders.append(OrderPlan(code=code, side="BUY", qty=net_qty, limit=None))
        elif net_qty < 0:
            # 순매도
            net_orders.append(OrderPlan(code=code, side="SELL", qty=abs(net_qty), limit=None))
        # net_qty == 0인 경우는 불필요한 주문이므로 제외
    
    return net_orders


def _optimize_cash_flow(orders: List[OrderPlan], cash: float, prices: Dict[str, float]) -> List[OrderPlan]:
    """
    현금 흐름을 고려한 주문 순서 최적화
    """
    sell_orders = []
    buy_orders = []
    
    # 매도/매수 주문 분리
    for order in orders:
        if order.side == "SELL":
            sell_orders.append(order)
        elif order.side == "BUY":
            buy_orders.append(order)
    
    # 매도 주문을 먼저 배치 (현금 확보)
    # 매수 주문을 나중에 배치 (현금 사용)
    optimized_plan = sell_orders + buy_orders
    
    return optimized_plan


def calculate_commission_savings(original_plan: List[OrderPlan], optimized_plan: List[OrderPlan]) -> Dict[str, int]:
    """
    최적화로 인한 수수료 절약 효과 계산
    
    Args:
        original_plan: 원본 주문 계획
        optimized_plan: 최적화된 주문 계획
        
    Returns:
        Dict[str, int]: 수수료 절약 정보
    """
    original_orders = len(original_plan)
    optimized_orders = len(optimized_plan)
    saved_orders = original_orders - optimized_orders
    
    return {
        "original_orders": original_orders,
        "optimized_orders": optimized_orders,
        "saved_orders": saved_orders,
        "savings_percentage": (saved_orders / original_orders * 100) if original_orders > 0 else 0
    }


def estimate_commission_cost(plan: List[OrderPlan], prices: Dict[str, float], 
                           commission_rate: float = 0.0015) -> float:
    """
    주문 계획의 예상 수수료 비용 계산
    
    Args:
        plan: 주문 계획
        prices: 종목별 가격
        commission_rate: 수수료율 (기본 0.15%)
        
    Returns:
        float: 예상 수수료 비용
    """
    total_commission = 0.0
    
    for order in plan:
        price = prices.get(order.code, 0.0)
        if price > 0:
            order_value = order.qty * price
            commission = order_value * commission_rate
            total_commission += commission
    
    return total_commission
