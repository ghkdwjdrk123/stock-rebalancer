"""
일별 주문체결 조회 관련 유틸리티 함수들
KIS API `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` 사용
"""
from __future__ import annotations
from typing import Dict, List, Any, Set
from dataclasses import dataclass


@dataclass
class DailyOrder:
    """일별 주문 정보"""
    code: str          # 종목코드 (PDNO)
    side: str          # BUY/SELL (SLL_BUY_DVSN_CD_NAME)
    qty: int           # 주문수량 (ORD_QTY)
    exec_qty: int      # 체결수량 (EXEC_QTY)
    pending_qty: int   # 미체결수량 (ORD_QTY - EXEC_QTY)
    price: float | None  # 주문단가 (ORD_UNPR)
    order_id: str      # 주문번호 (ORD_GNO_BRNO 또는 ODNO)
    order_status: str  # 주문상태 (ORD_STAT)
    exec_status: str   # 체결상태 (CCLD_STAT)


def parse_daily_orders(api_response: Dict[str, Any]) -> List[DailyOrder]:
    """
    KIS API 일별 주문체결 조회 응답을 파싱하여 DailyOrder 리스트로 변환
    
    Args:
        api_response: KIS API 응답 JSON
        
    Returns:
        List[DailyOrder]: 파싱된 주문 리스트
    """
    orders: List[DailyOrder] = []
    
    try:
        output1 = api_response.get("output1", [])
        if not isinstance(output1, list):
            return orders
            
        for item in output1:
            try:
                code = str(item.get("pdno", "")).strip()
                side_raw = str(item.get("sll_buy_dvsn_cd_name", "")).strip()
                ord_qty = int(item.get("ord_qty", "0") or "0")
                # KIS API에서 체결수량은 tot_ccld_qty, 미체결수량은 rmn_qty로 제공
                exec_qty = int(item.get("tot_ccld_qty", "0") or "0")
                rmn_qty = int(item.get("rmn_qty", "0") or "0")
                price_str = item.get("ord_unpr", "0")
                order_gno = str(item.get("ord_gno_brno", "")).strip()
                odno = str(item.get("odno", "")).strip()
                ord_stat = str(item.get("ord_stat", "")).strip()
                ccld_stat = str(item.get("ccld_stat", "")).strip()
                
                # 매수/매도 구분
                if "매수" in side_raw or "BUY" in side_raw.upper():
                    side = "BUY"
                elif "매도" in side_raw or "SELL" in side_raw.upper():
                    side = "SELL"
                else:
                    continue
                
                # 미체결 수량: API에서 직접 제공되는 rmn_qty 사용
                pending_qty = rmn_qty
                
                # 주문번호: 취소 시에는 odno (고유 주문번호) 사용, ord_gno_brno는 모든 주문에 동일함
                order_id = odno if odno else order_gno
                
                # 가격 처리
                price = None
                if price_str and price_str != "0" and price_str != "":
                    try:
                        price = float(price_str)
                    except (ValueError, TypeError):
                        price = None
                
                if code and ord_qty > 0:
                    orders.append(DailyOrder(
                        code=code,
                        side=side,
                        qty=ord_qty,
                        exec_qty=exec_qty,
                        pending_qty=pending_qty,
                        price=price,
                        order_id=order_id,
                        order_status=ord_stat,
                        exec_status=ccld_stat
                    ))
                    
            except (ValueError, TypeError, AttributeError) as e:
                # 개별 주문 파싱 실패 시 로그만 남기고 계속 진행
                continue
                
    except Exception as e:
        # 전체 파싱 실패 시 빈 리스트 반환
        pass
        
    return orders


def get_pending_orders(daily_orders: List[DailyOrder]) -> List[DailyOrder]:
    """
    일별 주문에서 미체결 주문만 필터링
    
    Args:
        daily_orders: 일별 주문 리스트
        
    Returns:
        List[DailyOrder]: 미체결 주문 리스트
    """
    return [order for order in daily_orders if order.pending_qty > 0]


def get_pending_positions(pending_orders: List[DailyOrder]) -> Dict[str, int]:
    """
    미체결 주문에서 예상 보유 수량을 계산
    
    Args:
        pending_orders: 미체결 주문 리스트
        
    Returns:
        Dict[str, int]: {종목코드: 예상수량} 딕셔너리
        (매수는 +, 매도는 -로 계산)
    """
    pending_positions: Dict[str, int] = {}
    
    for order in pending_orders:
        if order.side == "BUY":
            pending_positions[order.code] = pending_positions.get(order.code, 0) + order.pending_qty
        elif order.side == "SELL":
            pending_positions[order.code] = pending_positions.get(order.code, 0) - order.pending_qty
    
    return pending_positions


def get_executed_positions(daily_orders: List[DailyOrder]) -> Dict[str, int]:
    """
    당일 체결된 주문에서 포지션 변화를 계산
    
    Args:
        daily_orders: 일별 주문 리스트 (체결+미체결)
        
    Returns:
        Dict[str, int]: {종목코드: 체결수량변화} 딕셔너리
        (매수는 +, 매도는 -로 계산)
    """
    executed_positions: Dict[str, int] = {}
    
    for order in daily_orders:
        if order.exec_qty > 0:  # 체결된 수량이 있는 경우만
            if order.side == "BUY":
                executed_positions[order.code] = executed_positions.get(order.code, 0) + order.exec_qty
            elif order.side == "SELL":
                executed_positions[order.code] = executed_positions.get(order.code, 0) - order.exec_qty
    
    return executed_positions


def get_cash_impact(daily_orders: List[DailyOrder], prices: Dict[str, float]) -> float:
    """
    당일 주문으로 인한 현금 변동 계산
    
    Args:
        daily_orders: 일별 주문 리스트
        prices: 종목별 현재가
        
    Returns:
        float: 현금 변동 (음수: 현금 감소, 양수: 현금 증가)
    """
    cash_impact = 0.0
    
    for order in daily_orders:
        if order.exec_qty > 0 and order.code in prices:
            price = prices[order.code]
            if order.side == "BUY":
                # 매수 체결: 현금 감소
                cash_impact -= order.exec_qty * price
            elif order.side == "SELL":
                # 매도 체결: 현금 증가
                cash_impact += order.exec_qty * price
    
    return cash_impact


def filter_duplicate_orders(
    new_orders: List[Any], 
    pending_orders: List[DailyOrder],
    tolerance_qty: int = 0
) -> List[Any]:
    """
    미체결 주문과 중복되는 새로운 주문을 필터링
    
    Args:
        new_orders: 새로운 주문 계획 리스트
        pending_orders: 기존 미체결 주문 리스트
        tolerance_qty: 수량 허용 오차
        
    Returns:
        List[Any]: 중복되지 않는 새로운 주문 리스트
    """
    # 미체결 주문을 집합으로 변환 (빠른 검색을 위해)
    pending_set: Set[str] = set()
    for order in pending_orders:
        # 종목코드:매수/매도:수량 조합으로 중복 키 생성
        key = f"{order.code}:{order.side}:{order.pending_qty}"
        pending_set.add(key)
    
    filtered_orders = []
    for new_order in new_orders:
        # 새로운 주문의 키 생성
        new_key = f"{new_order.code}:{new_order.side}:{new_order.qty}"
        
        # 중복 검사 (수량 허용 오차 고려)
        is_duplicate = False
        if new_key in pending_set:
            is_duplicate = True
        else:
            # 수량 허용 오차 범위 내에서 중복 검사
            for order in pending_orders:
                if (order.code == new_order.code and 
                    order.side == new_order.side and
                    abs(order.pending_qty - new_order.qty) <= tolerance_qty):
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            filtered_orders.append(new_order)
    
    return filtered_orders


def get_order_summary(daily_orders: List[DailyOrder]) -> Dict[str, Any]:
    """
    주문 요약 정보 생성
    
    Args:
        daily_orders: 일별 주문 리스트
        
    Returns:
        Dict[str, Any]: 주문 요약 정보
    """
    total_orders = len(daily_orders)
    pending_orders = get_pending_orders(daily_orders)
    total_pending = len(pending_orders)
    
    # 종목별 미체결 수량 집계
    pending_by_code = {}
    for order in pending_orders:
        if order.code not in pending_by_code:
            pending_by_code[order.code] = {"BUY": 0, "SELL": 0}
        pending_by_code[order.code][order.side] += order.pending_qty
    
    return {
        "total_orders": total_orders,
        "pending_orders": total_pending,
        "pending_by_code": pending_by_code,
        "pending_positions": get_pending_positions(pending_orders)
    }
