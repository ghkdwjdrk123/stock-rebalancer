"""
미체결 주문 조회 서비스
"""
from __future__ import annotations
from typing import Dict, List, Any, Tuple
from src.services.brokers.base import Broker
from src.services.daily_orders import parse_daily_orders, get_pending_orders, get_order_summary, DailyOrder


async def get_pending_orders_info(broker: Broker, date: str = "") -> Dict[str, Any]:
    """
    미체결 주문 정보를 조회하여 구조화된 정보를 반환
    
    Args:
        broker: 브로커 인스턴스
        date: 조회일자 (YYYYMMDD, 빈 문자열이면 당일)
    
    Returns:
        Dict[str, Any]: 미체결 주문 정보
        {
            "total_orders": int,           # 전체 주문 수
            "pending_orders": int,         # 미체결 주문 수
            "pending_list": List[DailyOrder],  # 미체결 주문 리스트
            "pending_by_code": Dict,       # 종목별 미체결 수량
            "pending_positions": Dict,     # 예상 포지션 변화
            "summary_text": str           # 요약 텍스트
        }
    """
    try:
        # 당일 주문체결 조회
        daily_response = await broker.fetch_daily_orders(date)
        
        # 주문 파싱
        daily_orders = parse_daily_orders(daily_response)
        pending_orders = get_pending_orders(daily_orders)
        summary = get_order_summary(daily_orders)
        
        # 요약 텍스트 생성
        summary_text = _generate_summary_text(summary, pending_orders)
        
        return {
            "total_orders": summary["total_orders"],
            "pending_orders": summary["pending_orders"],
            "pending_list": pending_orders,
            "pending_by_code": summary["pending_by_code"],
            "pending_positions": summary["pending_positions"],
            "summary_text": summary_text,
            "raw_response": daily_response  # 디버깅용
        }
        
    except Exception as e:
        from src.utils.logging import get_logger
        log = get_logger("pending_orders")
        log.error(f"미체결 주문 조회 실패: {e}")
        
        return {
            "total_orders": 0,
            "pending_orders": 0,
            "pending_list": [],
            "pending_by_code": {},
            "pending_positions": {},
            "summary_text": f"미체결 주문 조회 실패: {e}",
            "error": str(e)
        }


def _generate_summary_text(summary: Dict[str, Any], pending_orders: List[DailyOrder]) -> str:
    """미체결 주문 요약 텍스트 생성"""
    lines = []
    
    lines.append(f"전체 주문: {summary['total_orders']}건")
    lines.append(f"미체결 주문: {summary['pending_orders']}건")
    
    if summary['pending_orders'] == 0:
        lines.append("미체결 주문이 없습니다.")
        return "\n".join(lines)
    
    # 미체결 주문 상세
    lines.append("\n미체결 주문 상세:")
    for i, order in enumerate(pending_orders, 1):
        side_text = "매수" if order.side == "BUY" else "매도"
        price_text = f"{order.price:,.0f}원" if order.price else "시장가"
        
        lines.append(f"  {i}. {order.code} ({side_text})")
        lines.append(f"     주문수량: {order.qty:,}주, 체결수량: {order.exec_qty:,}주, 미체결수량: {order.pending_qty:,}주")
        lines.append(f"     주문가격: {price_text}, 주문번호: {order.order_id}")
    
    # 종목별 요약
    if summary['pending_by_code']:
        lines.append("\n종목별 미체결 요약:")
        for code, sides in summary['pending_by_code'].items():
            buy_qty = sides.get('BUY', 0)
            sell_qty = sides.get('SELL', 0)
            
            if buy_qty > 0 and sell_qty > 0:
                lines.append(f"  {code}: 매수 {buy_qty:,}주, 매도 {sell_qty:,}주")
            elif buy_qty > 0:
                lines.append(f"  {code}: 매수 {buy_qty:,}주")
            elif sell_qty > 0:
                lines.append(f"  {code}: 매도 {sell_qty:,}주")
    
    # 예상 포지션 변화
    pending_positions = summary['pending_positions']
    if pending_positions:
        lines.append("\n예상 포지션 변화:")
        for code, qty_change in pending_positions.items():
            if qty_change > 0:
                lines.append(f"  {code}: +{qty_change:,}주 (매수 미체결)")
            elif qty_change < 0:
                lines.append(f"  {code}: {qty_change:,}주 (매도 미체결)")
    
    return "\n".join(lines)


async def check_pending_orders_exist(broker: Broker, date: str = "") -> bool:
    """
    미체결 주문이 있는지 간단히 확인
    
    Args:
        broker: 브로커 인스턴스
        date: 조회일자 (YYYYMMDD, 빈 문자열이면 당일)
    
    Returns:
        bool: 미체결 주문 존재 여부
    """
    try:
        info = await get_pending_orders_info(broker, date)
        return info["pending_orders"] > 0
    except Exception:
        return False


async def get_pending_orders_by_code(broker: Broker, code: str, date: str = "") -> List[DailyOrder]:
    """
    특정 종목의 미체결 주문만 조회
    
    Args:
        broker: 브로커 인스턴스
        code: 종목코드
        date: 조회일자 (YYYYMMDD, 빈 문자열이면 당일)
    
    Returns:
        List[DailyOrder]: 해당 종목의 미체결 주문 리스트
    """
    try:
        info = await get_pending_orders_info(broker, date)
        return [order for order in info["pending_list"] if order.code == code]
    except Exception:
        return []


async def get_pending_orders_by_side(broker: Broker, side: str, date: str = "") -> List[DailyOrder]:
    """
    특정 방향(매수/매도)의 미체결 주문만 조회
    
    Args:
        broker: 브로커 인스턴스
        side: "BUY" 또는 "SELL"
        date: 조회일자 (YYYYMMDD, 빈 문자열이면 당일)
    
    Returns:
        List[DailyOrder]: 해당 방향의 미체결 주문 리스트
    """
    try:
        info = await get_pending_orders_info(broker, date)
        return [order for order in info["pending_list"] if order.side == side.upper()]
    except Exception:
        return []


def format_pending_orders_table(pending_orders: List[DailyOrder]) -> str:
    """
    미체결 주문을 테이블 형태로 포맷팅
    
    Args:
        pending_orders: 미체결 주문 리스트
    
    Returns:
        str: 포맷팅된 테이블 문자열
    """
    if not pending_orders:
        return "미체결 주문이 없습니다."
    
    # 테이블 헤더
    lines = []
    lines.append("=" * 100)
    lines.append(f"{'종목코드':<8} {'방향':<4} {'주문수량':<8} {'체결수량':<8} {'미체결수량':<8} {'주문가격':<10} {'주문번호':<12}")
    lines.append("-" * 100)
    
    # 테이블 데이터
    for order in pending_orders:
        side_text = "매수" if order.side == "BUY" else "매도"
        price_text = f"{order.price:,.0f}원" if order.price else "시장가"
        
        lines.append(
            f"{order.code:<8} {side_text:<4} {order.qty:<8,} {order.exec_qty:<8,} "
            f"{order.pending_qty:<8,} {price_text:<10} {order.order_id:<12}"
        )
    
    lines.append("=" * 100)
    return "\n".join(lines)
