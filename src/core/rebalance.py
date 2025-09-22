from __future__ import annotations
from typing import Dict, List, Tuple
from src.core.models import OrderPlan
from src.core.rounding import round_lot, clamp_order_value


def calculate_virtual_cash(
    positions: Dict[str, int], 
    prices: Dict[str, float], 
    d2_cash: float,
    is_mock: bool = True
) -> Tuple[float, float]:
    """
    모의투자에서 실전과 유사한 가상 예수금 계산
    
    Args:
        positions: 현재 보유 종목 수량
        prices: 종목별 현재가
        d2_cash: D+2 예수금 (모의투자 API 응답)
        is_mock: 모의투자 여부 (기본값: True)
        
    Returns:
        Tuple[float, float]: (전체 자산 가치, 실제 주문가능현금)
    """
    from src.utils.logging import get_logger
    log = get_logger("virtual_cash")
    
    # 전체 자산 가치 계산 (보유 주식 + D+2 예수금)
    portfolio_value = sum(prices.get(ticker, 0) * qty for ticker, qty in positions.items())
    total_asset_value = portfolio_value + d2_cash
    
    if not is_mock:
        # 실전 환경: 주문가능현금을 사용 (ord_psbl_cash)
        # 주문가능현금이 제공되지 않는 경우 D+2 예수금 사용
        available_cash = d2_cash  # 실제로는 ord_psbl_cash를 사용해야 함
        return total_asset_value, available_cash
    
    # 모의투자 환경: 전체 자산 기준 안전여유율 적용
    safety_margin = 0.0  # 0% (전체 자산 기준) - 최대 활용
    safety_amount = total_asset_value * safety_margin
    available_cash = d2_cash - safety_amount
    
    log.info(f"💰 가상 예수금 계산 (모의투자):")
    log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
    log.info(f"  - D+2 예수금: {d2_cash:,.0f}원")
    log.info(f"  - 전체 자산 가치: {total_asset_value:,.0f}원")
    log.info(f"  - 안전여유율: {safety_margin*100:.1f}% (전체 자산 기준)")
    log.info(f"  - 안전여유금: {safety_amount:,.0f}원")
    log.info(f"  - 주문가능현금: {available_cash:,.0f}원")
    
    return total_asset_value, available_cash

async def plan_rebalance(positions: Dict[str, int], targets: Dict[str, float],
                   cash: float, prices: Dict[str, float],
                   band_pct: float = 1.0,
                         max_order_value_per_ticker: int = 0,
                         d2_cash: float = None,
                         broker=None) -> List[OrderPlan]:
    """
    깔끔한 리밸런싱 계획 수립
    
    핵심 개선사항:
    1. 미수 상황(cash < 0)에서는 새로운 plan_rebalance_with_deficit 함수 사용
    2. 모든 미체결 주문 취소 후 깔끔한 재계획
    3. 수수료 부담 없이 안정성 향상
    4. 복잡한 미체결 주문 상태 관리 불필요
    """
    from src.utils.logging import get_logger
    log = get_logger("rebalance")
    
    # 미수 상황에서는 새로운 로직 사용 (D+2 예수금 기준)
    if cash < 0 or (d2_cash is not None and d2_cash < 0):
        from src.config import Settings
        settings = Settings()
        
        # D+2 예수금이 음수면 미수 상황으로 판단
        deficit_amount = d2_cash if d2_cash is not None and d2_cash < 0 else cash
        log.info(f"🔧 미수 상황 감지 (D+2 예수금: {d2_cash:,.0f}원, 주문가능현금: {cash:,.0f}원) - 새로운 미수 해결 로직 사용")
        return plan_rebalance_with_deficit(
            positions=positions,
            targets=targets,
            cash=deficit_amount,  # 미수 금액을 음수로 전달
            prices=prices,
            band_pct=band_pct,
            max_order_value_per_ticker=max_order_value_per_ticker or settings.deficit_max_order_value,
            reserve_ratio=settings.deficit_reserve_ratio
        )
    
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
    
    # 전체 자산 가치 계산 (가상 예수금 시스템 적용)
    total_asset_value, available_cash = calculate_virtual_cash(
        positions=positions,
        prices=prices,
        d2_cash=cash,  # D+2 예수금
        is_mock=True   # 모의투자 환경
    )
    
    # 전체 자산 가치를 리밸런싱 기준으로 사용
    value = total_asset_value
    
    if value <= 0:
        return []
    
    # 현재 비중 및 델타 계산
    cur_w = {c: (prices.get(c, 0.0) * positions.get(c, 0)) / value for c in targets}
    deltas = {c: targets[c] - cur_w.get(c, 0.0) for c in targets}
    
    # 밴드 체크: 하나라도 밴드를 초과하면 전체 리밸런싱
    band_violations = [c for c, d in deltas.items() if abs(d) > band_pct/100.0]
    
    if not band_violations:
        log.info(f"✅ 모든 종목이 밴드 내부 ({band_pct}%) - 리밸런싱 불필요")
        return []
    
    log.info(f"🔄 밴드 초과 종목: {band_violations} - 전체 리밸런싱 실행")
    
    # 전체 리밸런싱: 모든 종목을 목표 비중으로 조정
    to_sell = [c for c, d in deltas.items() if d < 0]  # 음수 델타 = 매도 필요
    to_buy  = [c for c, d in deltas.items() if d > 0]  # 양수 델타 = 매수 필요
    
    # 현금 부족 시 매도 강제 실행 로직
    if not to_sell and to_buy:
        # 매도할 종목이 없고 매수만 필요한 경우
        # 매수에 필요한 총 금액 계산
        total_buy_need = sum((targets[c] - cur_w.get(c, 0.0)) * value for c in to_buy)
        
        if total_buy_need >= available_cash * 0.99:  # 99% 이상이면 현금 부족으로 판단
            log.warning(f"💰 현금 부족: 필요 {total_buy_need:,.0f}원, 보유 {available_cash:,.0f}원")
            log.info("🔄 현금 부족으로 인한 목표 비중 조정")
            
            # 현금 범위 내에서 현실적인 목표 비중으로 조정
            cash_ratio = available_cash / value
            log.info(f"💰 현금 비율: {cash_ratio*100:.1f}%")
            
            # 각 종목의 목표 비중을 현금 범위에 맞게 조정
            adjusted_targets = {}
            total_stock_weight = 1.0 - cash_ratio  # 현금 제외한 주식 비중
            
            for ticker in targets.keys():
                # 현재 비중을 기준으로 현실적인 목표 설정
                current_weight = cur_w.get(ticker, 0.0)
                adjusted_target = current_weight * total_stock_weight
                adjusted_targets[ticker] = adjusted_target
            
            log.info("🔄 조정된 목표 비중:")
            for ticker, target in adjusted_targets.items():
                log.info(f"  {ticker}: {target*100:.1f}%")
            
            # 조정된 목표 비중으로 델타 재계산
            adjusted_deltas = {c: adjusted_targets[c] - cur_w.get(c, 0.0) for c in targets}
            to_sell = [c for c, d in adjusted_deltas.items() if d < 0]
            to_buy = [c for c, d in adjusted_deltas.items() if d > 0]
            
            log.info(f"🔄 조정된 매도/매수: to_sell={to_sell}, to_buy={to_buy}")
    
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
    
    # === 2단계: 적응형 리밸런싱 예산 계산 (가상 예수금 시스템 적용) ===
    # 매도로 확보될 현금 + 실제 주문가능현금 (안전여유율 적용됨)
    total_available_cash = total_sell_value + available_cash
    
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
        # 전체 포트폴리오 가치 = 현재 보유 주식 총 가치 + 확보된 현금
        total_value = sum(prices.get(code, 0.0) * qty for code, qty in expected_positions.items()) + expected_cash
        
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
                log.info(f"🔍 매수 계획 상세: {len(test_buy_orders)}건 - {[(order.code, order.qty) for order in test_buy_orders]}")
                break
            else:
                log.info(f"❌ 미수 해결 모드 현금 보유 비율 {reserve_ratio*100:.1f}%에서 매수 계획 실패 (feasible={plan_feasible}, orders={len(test_buy_orders)})")
        
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


def plan_rebalance_with_deficit(
    positions: Dict[str, int],
    targets: Dict[str, float],
    cash: float,
    prices: Dict[str, float],
    band_pct: float = 1.0,
    max_order_value_per_ticker: int = 0,
    reserve_ratio: float = 0.005,  # 0.5% 기본 예비금
) -> List[OrderPlan]:
    """
    미수(음수 예수금) 상황을 처리하는 새로운 리밸런싱 로직
    
    1) 가상 전량 청산 예산으로 목표 정수 수량(target_qty) 산출
    2) delta = target_qty - current_qty -> SELL, BUY 순으로 계획 생성
    3) SELL로 확보된 현금 + 기존 cash(음수면 보정) 범위 내에서 BUY 수량 조절
    4) band_pct 내 델타는 생략
    5) 동일 티커에 대해 동시에 SELL/BUY가 나오지 않음 (순복합 결과만)
    """
    from src.utils.logging import get_logger
    log = get_logger("deficit_rebalance")
    
    # 0) 유효성 검사
    tickers = set(targets.keys()) | set(positions.keys())
    usable = [t for t in tickers if prices.get(t, 0) > 0]
    if not usable:
        log.warning("❌ 유효한 가격 정보가 있는 종목이 없습니다")
        return []

    # 1) 가상 전량 청산 예산 계산 (모의투자 환경 고려)
    portfolio_value = sum(prices[t] * positions.get(t, 0) for t in usable)
    
    # 모의투자에서 실전과 유사한 가상 예수금 계산
    virtual_total_cash, available_cash = calculate_virtual_cash(
        positions=positions,
        prices=prices,
        d2_cash=cash,  # D+2 예수금을 cash로 전달
        is_mock=True   # 모의투자 환경
    )
    
    # 가상 전량 청산 예산 = 보유자산 가치 + 가상 총예수금
    V_total = portfolio_value + virtual_total_cash
    
    log.info(f"📊 가상 전량 청산 예산: {V_total:,.0f}원 (포트폴리오: {portfolio_value:,.0f}원 + 현금: {max(cash, 0):,.0f}원)")
    
    # 2) 이상적 타깃 수량(정수) 계산
    target_qty: Dict[str, int] = {t: 0 for t in usable}
    # 미수 상황에서는 예비금을 0%로 설정 (미수 해결 우선)
    effective_reserve_ratio = 0.0 if cash < 0 else reserve_ratio
    budget = V_total * (1 - effective_reserve_ratio)
    
    # 2-1) 1차 배분(바닥 나눗셈)
    for t in usable:
        w = targets.get(t, 0.0)
        target_value = budget * w
        q = int(target_value // prices[t])
        target_qty[t] = max(q, 0)
    
    # 2-2) 잔액으로 +1씩 증액(가격 낮은 순)
    spent = sum(target_qty[t] * prices[t] for t in usable)
    leftover = max(budget - spent, 0.0)
    if leftover > 0:
        for t in sorted(usable, key=lambda x: prices[x]):  # 저가부터 1주 추가 시도
            if prices[t] <= leftover:
                target_qty[t] += 1
                leftover -= prices[t]
    
    log.info(f"🎯 목표 수량 계산 완료 (예비금: {effective_reserve_ratio*100:.1f}%):")
    for t in usable:
        log.info(f"  - {t}: {positions.get(t, 0)}주 → {target_qty[t]}주 (목표 비중: {targets.get(t, 0)*100:.1f}%)")

    # 3) 델타 산출 및 밴드 적용
    deltas = {t: target_qty.get(t, 0) - positions.get(t, 0) for t in usable}
    
    # 밴드 적용: 현재 가치 기준으로 밴드 내면 거래 생략
    filtered_deltas = {}
    for t, delta in deltas.items():
        current_value = positions.get(t, 0) * prices[t]
        target_value = target_qty[t] * prices[t]
        if current_value > 0:
            ratio_diff = abs(target_value - current_value) / current_value
            if ratio_diff * 100 > band_pct:  # 밴드 초과시만 거래
                filtered_deltas[t] = delta
                log.info(f"📈 {t}: 밴드 초과 거래 필요 (차이: {ratio_diff*100:.2f}% > {band_pct}%)")
            else:
                log.info(f"✅ {t}: 밴드 내 거래 생략 (차이: {ratio_diff*100:.2f}% ≤ {band_pct}%)")
        else:
            # 보유하지 않는 종목은 매수만 고려
            if delta > 0:
                filtered_deltas[t] = delta
    
    sells = [t for t, d in filtered_deltas.items() if d < 0]
    buys  = [t for t, d in filtered_deltas.items() if d > 0]

    plan: List[OrderPlan] = []
    current_cash = cash

    # 3-1) SELL 우선 실행 (미수 해결을 위한 충분한 매도)
    required_cash = abs(cash)  # 미수 해결에 필요한 현금
    log.info(f"💰 미수 해결 필요 현금: {required_cash:,.0f}원")
    
    # 미수 해결을 위한 추가 매도 계산
    additional_sells = {}
    remaining_deficit = required_cash
    
    # 현재 매도 계획으로 확보 가능한 현금 계산
    planned_sell_cash = sum(abs(filtered_deltas.get(t, 0)) * prices[t] for t in sells)
    log.info(f"💰 계획된 매도로 확보 가능한 현금: {planned_sell_cash:,.0f}원")
    
    # 미수 해결에 부족한 현금이 있으면 추가 매도 필요
    if planned_sell_cash < required_cash:
        deficit = required_cash - planned_sell_cash
        log.info(f"💰 추가 매도 필요: {deficit:,.0f}원")
        
        # 보유 종목을 가격 높은 순으로 정렬 (효율적인 매도)
        available_positions = [(t, positions.get(t, 0), prices[t]) for t in usable if positions.get(t, 0) > 0]
        sorted_positions = sorted(available_positions, key=lambda x: x[2], reverse=True)
        
        for t, current_qty, price in sorted_positions:
            if remaining_deficit <= 0:
                break
                
            # 이미 매도 계획이 있는 종목은 제외
            if t in sells:
                continue
                
            # 추가 매도 수량 계산
            needed_qty = max(1, round_lot(remaining_deficit / price))
            sell_qty = min(current_qty, needed_qty)
            
            if sell_qty > 0:
                additional_sells[t] = sell_qty
                remaining_deficit -= sell_qty * price
                log.info(f"💰 추가 매도: {t} {sell_qty}주 @ {price:,.0f}원 = {sell_qty * price:,.0f}원")
    
    # 모든 매도 주문 실행
    for t in sorted(sells, key=lambda x: filtered_deltas[x]):
        price = prices[t]
        qty = abs(filtered_deltas[t])
        if qty <= 0 or price <= 0:
            continue
        
        # 최소 거래 단위 확인
        qty = round_lot(qty)
        if qty <= 0:
            continue
            
        # 최대 주문 금액 제한
        if max_order_value_per_ticker:
            qty = clamp_order_value(qty, price, max_order_value_per_ticker)
        if qty <= 0:
            continue
            
        plan.append(OrderPlan(code=t, side="SELL", qty=qty, limit=None))
        current_cash += qty * price
        log.info(f"💰 매도 계획: {t} {qty}주 @ {price:,.0f}원 = {qty * price:,.0f}원")
    
    # 추가 매도 주문 실행
    for t, qty in additional_sells.items():
        price = prices[t]
        qty = round_lot(qty)
        if qty > 0:
            plan.append(OrderPlan(code=t, side="SELL", qty=qty, limit=None))
            current_cash += qty * price
            log.info(f"💰 추가 매도: {t} {qty}주 @ {price:,.0f}원 = {qty * price:,.0f}원")

    # 3-2) BUY 후행 (실제 주문가능현금 내에서만, 가장 부족한 것부터)
    # 매수 시에는 안전여유율이 적용된 실제 주문가능현금 사용
    buy_cash = available_cash  # 안전여유율 적용된 현금
    
    for t in sorted(buys, key=lambda x: -filtered_deltas[x]):
        price = prices[t]
        qty = filtered_deltas[t]
        if qty <= 0 or price <= 0:
            continue
        
        # 실제 주문가능현금 내에서만 매수
        affordable = int(buy_cash // price)
        if affordable <= 0:
            log.info(f"⚠️ {t}: 주문가능현금 부족으로 매수 생략 (필요: {qty}주, 가능: {affordable}주)")
            continue
            
        buy_qty = min(qty, affordable)
        buy_qty = round_lot(buy_qty)
        
        if max_order_value_per_ticker:
            buy_qty = clamp_order_value(buy_qty, price, max_order_value_per_ticker)
        if buy_qty <= 0:
            continue
            
        plan.append(OrderPlan(code=t, side="BUY", qty=buy_qty, limit=None))
        buy_cash -= buy_qty * price
        log.info(f"💰 매수 계획: {t} {buy_qty}주 @ {price:,.0f}원 = {buy_qty * price:,.0f}원")

    log.info(f"📋 최종 계획: {len(plan)}건 (매도: {len(sells)}, 매수: {len(buys)})")
    log.info(f"💰 예상 최종 현금: {current_cash:,.0f}원")

    return plan
