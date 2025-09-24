#!/usr/bin/env python3
"""
실제 미수 상황 테스트 (미수금이 보유주식 가치보다 큰 경우)
"""

import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.logging import get_logger
from src.core.rebalance import plan_rebalance_with_deficit

log = get_logger("test_real_deficit")

def test_real_deficit():
    """실제 미수 상황 테스트"""
    log.info("🧪 실제 미수 상황 테스트 시작")
    
    # 실제 미수 상황: 미수금이 보유주식 가치보다 큰 경우
    positions = {
        "379810": 100,  # 나스닥 100주
        "458730": 50,   # 배당다우존스 50주
        "329750": 30    # 달러채권 30주
    }
    
    prices = {
        "379810": 23000.0,  # 23,000원
        "458730": 12000.0,  # 12,000원
        "329750": 13000.0   # 13,000원
    }
    
    targets = {
        "379810": 0.6,  # 60%
        "458730": 0.3,  # 30%
        "329750": 0.1   # 10%
    }
    
    # 실제 미수 상황: -3,500,000원 (보유주식 가치보다 큰 미수)
    cash = -3500000
    
    log.info(f"📊 실제 미수 상황 테스트:")
    log.info(f"  - 보유 종목: {positions}")
    log.info(f"  - 현재가: {prices}")
    log.info(f"  - 목표 비중: {targets}")
    log.info(f"  - 현재 현금: {cash:,.0f}원 (실제 미수)")
    
    # 포트폴리오 가치 계산
    portfolio_value = sum(prices[t] * qty for t, qty in positions.items())
    total_asset = portfolio_value + cash  # 음수 현금 포함
    log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
    log.info(f"  - 전체 자산: {total_asset:,.0f}원 (음수 = 실제 미수 상황)")
    
    # 미수 해결 로직 실행
    plan = plan_rebalance_with_deficit(
        positions=positions,
        targets=targets,
        cash=cash,
        prices=prices,
        band_pct=1.0,
        max_order_value_per_ticker=0,
        reserve_ratio=0.005
    )
    
    log.info(f"📋 미수 해결 계획 결과:")
    log.info(f"  - 총 주문 건수: {len(plan)}건")
    
    total_sell_value = 0
    total_buy_value = 0
    sell_orders = []
    buy_orders = []
    
    for i, order in enumerate(plan, 1):
        price = prices.get(order.code, 0)
        value = order.qty * price
        if order.side == "SELL":
            total_sell_value += value
            sell_orders.append(f"{order.code}: {order.qty}주")
        else:
            total_buy_value += value
            buy_orders.append(f"{order.code}: {order.qty}주")
        log.info(f"  {i}. {order.side} {order.code} {order.qty}주 @ {price:,.0f}원 = {value:,.0f}원")
    
    log.info(f"📊 거래 요약:")
    log.info(f"  - 총 매도 금액: {total_sell_value:,.0f}원")
    log.info(f"  - 총 매수 금액: {total_buy_value:,.0f}원")
    log.info(f"  - 순 현금 확보: {total_sell_value - total_buy_value:,.0f}원")
    log.info(f"  - 매도 주문: {len(sell_orders)}건 - {sell_orders}")
    log.info(f"  - 매수 주문: {len(buy_orders)}건 - {buy_orders}")
    
    # 검증
    if len(plan) > 0:
        log.info("✅ 미수 해결 주문이 생성되었습니다 - 실제 미수 해결 성공!")
        return True
    else:
        log.warning("⚠️ 미수 해결 주문이 생성되지 않았습니다 - 실제 미수 해결에 문제가 있습니다.")
        return False

async def main():
    """메인 테스트 함수"""
    log.info("🚀 실제 미수 상황 테스트 시작")
    
    try:
        success = test_real_deficit()
        
        if success:
            log.info("🎉 실제 미수 상황 테스트 성공!")
        else:
            log.warning("⚠️ 실제 미수 상황 테스트에 문제가 있습니다.")
        
        return success
        
    except Exception as e:
        log.error(f"❌ 테스트 실행 중 예외: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
