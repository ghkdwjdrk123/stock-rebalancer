"""
현금 부족 방지를 위한 가드 로직
"""
from __future__ import annotations
from typing import Dict, List, Tuple
from src.core.models import OrderPlan
from src.core.rounding import round_lot


def validate_cash_sufficiency(plan: List[OrderPlan], initial_cash: float, prices: Dict[str, float]) -> Tuple[List[OrderPlan], float]:
    """
    주문 계획이 실행된 후 현금이 0원 미만이 되지 않는지 검증하고 조정
    
    Args:
        plan: 주문 계획 리스트
        initial_cash: 초기 현금 (음수 가능)
        prices: 종목별 가격
        
    Returns:
        Tuple[List[OrderPlan], float]:
        - 조정된 주문 계획 리스트
        - 최종 예상 현금
    """
    adjusted_plan: List[OrderPlan] = []
    current_cash = initial_cash
    
    # 매도 주문부터 처리 (현금 증가)
    sell_orders = [order for order in plan if order.side == "SELL"]
    buy_orders = [order for order in plan if order.side == "BUY"]
    
    # 매도 주문 실행 (현금이 음수인 경우 현금 확보)
    for order in sell_orders:
        price = prices.get(order.code, 0.0)
        if price > 0:
            cash_increase = order.qty * price
            current_cash += cash_increase
            adjusted_plan.append(order)
    
    # 매수 주문 실행 (현금 부족 방지)
    for order in buy_orders:
        price = prices.get(order.code, 0.0)
        if price > 0:
            required_cash = order.qty * price
            
            if current_cash >= required_cash:
                # 현금이 충분한 경우
                current_cash -= required_cash
                adjusted_plan.append(order)
            else:
                # 현금이 부족한 경우, 가능한 수량으로 조정
                # 초기 현금이 음수여도 매도 후 확보된 현금으로 매수 가능
                if current_cash > 0:
                    adjusted_qty = round_lot(current_cash / price)
                    if adjusted_qty > 0:
                        adjusted_order = OrderPlan(
                            code=order.code,
                            side=order.side,
                            qty=adjusted_qty,
                            limit=order.limit
                        )
                        current_cash -= adjusted_qty * price
                        adjusted_plan.append(adjusted_order)
                # 현금 부족으로 주문 불가능 (건너뛰기)
    
    return adjusted_plan, current_cash


def calculate_final_cash(plan: List[OrderPlan], initial_cash: float, prices: Dict[str, float]) -> float:
    """
    주문 계획 실행 후 예상 최종 현금 계산
    
    Args:
        plan: 주문 계획 리스트
        initial_cash: 초기 현금
        prices: 종목별 가격
        
    Returns:
        float: 예상 최종 현금
    """
    final_cash = initial_cash
    
    for order in plan:
        price = prices.get(order.code, 0.0)
        if price > 0:
            if order.side == "BUY":
                final_cash -= order.qty * price
            elif order.side == "SELL":
                final_cash += order.qty * price
    
    return final_cash


def get_cash_insufficient_orders(plan: List[OrderPlan], initial_cash: float, prices: Dict[str, float]) -> List[OrderPlan]:
    """
    현금 부족으로 실행 불가능한 주문들을 식별
    
    Args:
        plan: 주문 계획 리스트
        initial_cash: 초기 현금
        prices: 종목별 가격
        
    Returns:
        List[OrderPlan]: 실행 불가능한 주문 리스트
    """
    insufficient_orders: List[OrderPlan] = []
    current_cash = initial_cash
    
    # 매도 주문 먼저 처리
    for order in plan:
        if order.side == "SELL":
            price = prices.get(order.code, 0.0)
            if price > 0:
                current_cash += order.qty * price
    
    # 매수 주문 체크
    for order in plan:
        if order.side == "BUY":
            price = prices.get(order.code, 0.0)
            if price > 0:
                required_cash = order.qty * price
                if current_cash < required_cash:
                    insufficient_orders.append(order)
                else:
                    current_cash -= required_cash
    
    return insufficient_orders
