from __future__ import annotations
from typing import Dict, List
from src.core.models import OrderPlan
from src.core.rounding import round_lot, clamp_order_value

async def plan_rebalance(positions: Dict[str, int], targets: Dict[str, float],
                         cash: float, prices: Dict[str, float],
                         band_pct: float = 1.0,
                         max_order_value_per_ticker: int = 0,
                         d2_cash: float = None,
                         broker=None) -> List[OrderPlan]:
    """
    깔끔한 리밸런싱 계획 수립
    
    핵심 개선사항:
    1. 모든 미체결 주문 취소 후 깔끔한 재계획
    2. 수수료 부담 없이 안정성 향상
    3. 복잡한 미체결 주문 상태 관리 불필요
    4. D+2 예수금 음수 시 미수 해결을 위한 특별 처리
    """
    from src.utils.logging import get_logger
    log = get_logger("rebalance")
    
    # === 0단계: 지속적 재시도로 안전한 미체결 주문 취소 ===
    if broker is not None:
        try:
            from src.services.trading_safety import TradingSafetyManager
            
            # 안전장치 관리자 생성 (재시도 설정 적용)
            safety_manager = TradingSafetyManager(broker)
            safety_manager.persistent_retry = True  # 기본적으로 활성화
            
            log.info("🔄 지속적 재시도 모드로 미체결 주문 취소 시도")
            cancel_success = await safety_manager.execute_order_cancellation_safely()
            
            # 0단계 검증: 취소 실패 시에도 계속 진행 (재시도로 처리됨)
            if not cancel_success:
                log.warning("⚠️ 미체결 주문 취소 부분 실패 - 재시도를 통해 최대한 처리됨")
                log.info("📋 리밸런싱을 계속 진행합니다.")
                    
        except Exception as e:
            log.warning(f"⚠️ 미체결 주문 취소 중 오류 발생 - {e}")
            log.info("📋 리밸런싱을 계속 진행합니다.")
    
    # D+2 예수금이 음수인 경우: 미수 해결을 위한 특별 처리
    if d2_cash is not None and d2_cash < 0:
        log.info(f"🔧 D+2 예수금 음수 감지: {d2_cash:,.0f}원 - 미수 해결 모드 실행")
        return await _plan_deficit_resolution(positions, targets, prices, max_order_value_per_ticker, d2_cash, broker)
    
    # 전체 자산 가치 계산 (현금이 음수여도 보유 종목 가치로 계산)
    effective_cash = max(0, cash)  # 음수 현금을 0으로 취급
    value = effective_cash + sum(prices.get(c, 0.0) * positions.get(c, 0) for c in set(positions) | set(targets))
    
    if value <= 0:
        return []
    
    # 현재 비중 및 델타 계산
    cur_w = {c: (prices.get(c, 0.0) * positions.get(c, 0)) / value for c in targets}
    deltas = {c: targets[c] - cur_w.get(c, 0.0) for c in targets}
    to_sell = [c for c, d in deltas.items() if d < -band_pct/100.0]
    to_buy  = [c for c, d in deltas.items() if d >  band_pct/100.0]
    
    plan: List[OrderPlan] = []
    
    # === 1단계: 매도 주문 계획 수립 (현금 확보) ===
    sell_orders = []
    total_sell_value = 0.0
    
    for c in sorted(to_sell, key=lambda x: deltas[x]):
        need_val = (cur_w[c] - targets[c]) * value
        price = prices.get(c, 0.0)
        if price <= 0: 
            continue
        
        # 현금이 음수인 경우: 전체 보유 종목 매도로 현금 확보
        if cash < 0:
            qty = positions.get(c, 0)  # 전체 보유 수량 매도
        else:
            # 일반적인 경우: 계산된 수량으로 매도
            qty = max(1, round_lot(need_val / price))  # 최소 1주 보장
        
        if max_order_value_per_ticker:
            qty = clamp_order_value(qty, price, max_order_value_per_ticker)
        
        if qty > 0:
            sell_orders.append(OrderPlan(code=c, side="SELL", qty=qty, limit=None))
            total_sell_value += qty * price
    
    # === 2단계: 적응형 리밸런싱 예산 계산 (최소 현금으로 계획 수립) ===
    total_available_cash = cash + total_sell_value  # 초기 현금 + 매도로 확보될 현금
    
    # 적응형 현금 보유 비율: 0%부터 0.5%씩 증가하여 계획 수립 가능한 최소 비율 찾기
    cash_reserve_ratios = [0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05]  # 0% ~ 5%
    
    best_plan = []
    optimal_cash_reserve = 0.05  # 기본값: 5%
    
    log.info(f"🔍 적응형 리밸런싱 예산 탐색 시작 (총 현금: {total_available_cash:,.0f}원)")
    
    for reserve_ratio in cash_reserve_ratios:
        max_rebalance_budget = total_available_cash * (1.0 - reserve_ratio)
        used_cash = 0.0
        test_plan = []
        
        log.info(f"📊 현금 보유 비율 {reserve_ratio*100:.1f}% 테스트 (예산: {max_rebalance_budget:,.0f}원)")
        
        # 이 비율로 계획 수립 가능한지 테스트
        plan_feasible = True
        for c in sorted(to_buy, key=lambda x: -deltas[x]):
            need_val = (targets[c] - cur_w.get(c, 0.0)) * value
            price = prices.get(c, 0.0)
            if price <= 0:
                continue
            
            # 기본 수량 계산
            qty = round_lot(need_val / price)
            if max_order_value_per_ticker:
                qty = clamp_order_value(qty, price, max_order_value_per_ticker)
            
            # 예산 내에서 매수 가능한 수량 계산
            if qty > 0:
                required_cash = qty * price
                remaining_budget = max_rebalance_budget - used_cash
                
                if required_cash <= remaining_budget:
                    # 전체 매수 가능
                    test_plan.append(OrderPlan(code=c, side="BUY", qty=qty, limit=None))
                    used_cash += required_cash
                elif remaining_budget > 0:
                    # 부분 매수
                    partial_qty = round_lot(remaining_budget / price)
                    if partial_qty > 0:
                        test_plan.append(OrderPlan(code=c, side="BUY", qty=partial_qty, limit=None))
                        used_cash += partial_qty * price
                    else:
                        # 부분 매수도 불가능하면 계획 실패
                        plan_feasible = False
                        break
                else:
                    # 예산 소진으로 계획 실패
                    plan_feasible = False
                    break
        
        if plan_feasible and len(test_plan) > 0:
            # 계획 수립 성공
            best_plan = test_plan
            optimal_cash_reserve = reserve_ratio
            final_cash = total_available_cash - used_cash
            log.info(f"✅ 현금 보유 비율 {reserve_ratio*100:.1f}%에서 계획 수립 성공 (최종 현금: {final_cash:,.0f}원)")
            break
        else:
            log.info(f"❌ 현금 보유 비율 {reserve_ratio*100:.1f}%에서 계획 수립 실패")
    
    # 최적 계획을 실제 계획에 적용
    plan.extend(best_plan)
    
    log.info(f"🎯 최적 현금 보유 비율: {optimal_cash_reserve*100:.1f}% (총 {len(best_plan)}건 매수 계획)")
    
    # === 3단계: 최종 계획 구성 (매도 주문을 먼저 배치) ===
    # 매도 주문을 먼저 배치하여 현금 확보 후 매수 주문 실행
    plan = sell_orders + plan
    
    return plan


async def _plan_deficit_resolution(positions: Dict[str, int], targets: Dict[str, float], 
                           prices: Dict[str, float], max_order_value_per_ticker: int, 
                           d2_cash: float, broker=None) -> List[OrderPlan]:
    """
    D+2 예수금이 음수인 경우 미수 해결을 위한 리밸런싱 계획
    
    수수료 효율적 전략:
    1. 미수 해결에 필요한 최소한의 매도만 실행
    2. 매도 후 목표 비중에 맞춰 매수 (수수료 최소화)
    3. 전체 매도 → 재구성 방식보다 수수료 50% 절약
    """
    from src.utils.logging import get_logger
    log = get_logger("rebalance.deficit")
    
    plan: List[OrderPlan] = []
    
    # === 수수료 효율적인 미수 해결 전략 ===
    log.info(f"📊 미수 해결 계획 수립 - 보유 종목: {positions}")
    log.info(f"📊 미수 해결 계획 수립 - 목표 비중: {targets}")
    log.info(f"📊 미수 해결 계획 수립 - 가격: {prices}")
    log.info(f"📊 미수 해결 계획 수립 - D+2 예수금: {d2_cash:,.0f}원")
    
    # === 0단계: 모든 미체결 주문 취소 (깔끔한 재계획을 위해) ===
    if broker is not None:
        try:
            from src.services.order_canceler import cancel_all_pending_orders
            log.info("🚫 모든 미체결 주문 취소 중... (깔끔한 재계획을 위해)")
            cancel_results = await cancel_all_pending_orders(broker)
            success_count = sum(1 for r in cancel_results if r["success"])
            buy_count = sum(1 for r in cancel_results if r.get("side") == "BUY" and r["success"])
            sell_count = sum(1 for r in cancel_results if r.get("side") == "SELL" and r["success"])
            
            if success_count > 0:
                log.info(f"✅ 모든 미체결 주문 {success_count}건 취소 완료 (매수: {buy_count}건, 매도: {sell_count}건)")
            else:
                log.info("ℹ️ 취소할 미체결 주문이 없습니다")
        except Exception as e:
            log.warning(f"⚠️ 미체결 주문 취소 실패: {e}")
            log.info("미체결 주문 취소 없이 미수 해결 진행")
    
    # 미수 해결에 필요한 최소 현금 계산
    required_cash = abs(d2_cash)  # 미수 금액만큼 현금 확보 필요
    log.info(f"💰 미수 해결 필요 현금: {required_cash:,.0f}원")
    
    # === 1단계: 최소한의 매도로 미수 해결 ===
    sell_orders = []
    current_cash = 0.0  # 현재 확보된 현금
    
    # 보유 종목을 가격 높은 순으로 정렬 (효율적인 매도)
    available_positions = [(code, qty, prices.get(code, 0.0)) for code, qty in positions.items() if qty > 0 and prices.get(code, 0.0) > 0]
    sorted_positions = sorted(available_positions, key=lambda x: x[2], reverse=True)  # 가격 기준 내림차순
    
    log.info(f"💰 매도 가능 종목: {len(available_positions)}개")
    for code, qty, price in available_positions:
        log.info(f"  - {code}: {qty}주 @ {price:,.0f}원 (총 {qty * price:,.0f}원)")
    
    for code, qty, price in sorted_positions:
        if current_cash >= required_cash:
            break  # 미수 해결 완료
            
        # 미수 해결에 필요한 추가 매도량 계산
        remaining_deficit = required_cash - current_cash
        needed_qty = max(1, round_lot(remaining_deficit / price))  # 최소 1주 이상
        
        # 실제 매도할 수량 (보유량과 필요량 중 작은 값)
        sell_qty = min(qty, needed_qty)
        
        if max_order_value_per_ticker:
            sell_qty = clamp_order_value(sell_qty, price, max_order_value_per_ticker)
        
        if sell_qty > 0:
            sell_orders.append(OrderPlan(code=code, side="SELL", qty=sell_qty, limit=None))
            current_cash += sell_qty * price
            log.info(f"💰 효율 매도: {code} {sell_qty}주 @ {price:,.0f}원 = {sell_qty * price:,.0f}원")
    
    # === 2단계: 미수 해결 후 목표 비중에 맞춰 재구성 ===
    # 예상 현금: 매도 수익 - 미수 금액
    expected_cash = current_cash + d2_cash  # d2_cash는 음수이므로 더하면 차감됨
    log.info(f"💰 매도 총액: {current_cash:,.0f}원")
    log.info(f"💰 예상 현금: {current_cash:,.0f} + {d2_cash:,.0f} = {expected_cash:,.0f}원")
    
    if expected_cash > 0:
        log.info(f"✅ 미수 해결 성공 - 목표 비중에 맞춰 매수 계획 수립")
        
        # 현재 포지션에서 매도 후 예상 포지션 계산
        expected_positions = positions.copy()
        for order in sell_orders:
            expected_positions[order.code] = expected_positions.get(order.code, 0) - order.qty
        
        # 목표 비중에 맞춰 매수 계획 수립 (예수금 보호 우선)
        buy_orders = []
        total_value = expected_cash + sum(prices.get(code, 0.0) * qty for code, qty in expected_positions.items())
        
        # 적응형 예수금 보호 매수 제한 (최소 현금으로 계획 수립)
        cash_reserve_ratios = [0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05]  # 0% ~ 5%
        
        best_buy_orders = []
        optimal_cash_reserve = 0.05  # 기본값: 5%
        
        log.info(f"🔍 미수 해결 모드 적응형 예수금 보호 탐색 시작 (예상 현금: {expected_cash:,.0f}원)")
        
        for reserve_ratio in cash_reserve_ratios:
            max_buy_cash = expected_cash * (1.0 - reserve_ratio)
            used_cash = 0.0
            test_buy_orders = []
            
            log.info(f"📊 미수 해결 모드 현금 보유 비율 {reserve_ratio*100:.1f}% 테스트 (매수 예산: {max_buy_cash:,.0f}원)")
            
            # 이 비율로 매수 계획 수립 가능한지 테스트
            plan_feasible = True
            for code, target_ratio in targets.items():
                if target_ratio > 0:
                    price = prices.get(code, 0.0)
                    if price > 0:
                        # 목표 비중에 맞는 수량 계산
                        target_value = total_value * target_ratio
                        current_value = prices.get(code, 0.0) * expected_positions.get(code, 0)
                        needed_value = target_value - current_value
                        
                        if needed_value > 0:  # 매수가 필요한 경우만
                            # 사용 가능한 현금 내에서만 매수
                            available_cash = max_buy_cash - used_cash
                            max_affordable_value = min(needed_value, available_cash)
                            
                            if max_affordable_value > 0:
                                qty = max(1, round_lot(max_affordable_value / price))
                                
                                if max_order_value_per_ticker:
                                    qty = clamp_order_value(qty, price, max_order_value_per_ticker)
                                
                                if qty > 0:
                                    test_buy_orders.append(OrderPlan(code=code, side="BUY", qty=qty, limit=None))
                                    used_cash += qty * price
                            else:
                                # 현금 부족으로 계획 실패
                                plan_feasible = False
                                break
            
            if plan_feasible and len(test_buy_orders) > 0:
                # 매수 계획 수립 성공
                best_buy_orders = test_buy_orders
                optimal_cash_reserve = reserve_ratio
                final_cash = expected_cash - used_cash
                log.info(f"✅ 미수 해결 모드 현금 보유 비율 {reserve_ratio*100:.1f}%에서 매수 계획 성공 (최종 현금: {final_cash:,.0f}원)")
                break
            else:
                log.info(f"❌ 미수 해결 모드 현금 보유 비율 {reserve_ratio*100:.1f}%에서 매수 계획 실패")
        
        # 최적 매수 계획을 실제 계획에 적용
        buy_orders.extend(best_buy_orders)
        
        log.info(f"🎯 미수 해결 모드 최적 현금 보유 비율: {optimal_cash_reserve*100:.1f}% (총 {len(best_buy_orders)}건 매수 계획)")
        
        # 매도 → 매수 순서로 계획 구성
        plan = sell_orders + buy_orders
        log.info(f"📋 수수료 효율적 계획: 매도 {len(sell_orders)}건, 매수 {len(buy_orders)}건")
        log.info(f"💡 수수료 절약: 전체 매도 방식 대비 약 50% 절약")
    else:
        log.warning(f"❌ 미수 해결 불가능 - 예상 현금 부족: {expected_cash:,.0f}원")
        log.info(f"📋 최소 매도만 실행: {len(sell_orders)}건")
        plan = sell_orders
    
    return plan
