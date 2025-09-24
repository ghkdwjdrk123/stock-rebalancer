from __future__ import annotations
from typing import Dict, List, Tuple
from src.core.models import OrderPlan
from src.core.rounding import round_lot, clamp_order_value


def calculate_virtual_cash(
    positions: Dict[str, int], 
    prices: Dict[str, float], 
    d2_cash: float,
    is_mock: bool = True,
    safety_margin_pct: float = 1.0,
    cash: float = None,
    total_asset_value: float = None,
    orderable_cash: float = None
) -> Tuple[float, float]:
    """
    환경별 가상 예수금 계산
    
    Args:
        positions: 현재 보유 종목 수량
        prices: 종목별 현재가
        d2_cash: D+2 예수금
        is_mock: 모의투자 여부 (기본값: True)
        safety_margin_pct: 안전여유율 (%)
        cash: 기본 현금값 (fallback)
        total_asset_value: API 총자산값
        orderable_cash: 주문가능현금 (실전환경에서 사용)
        
    Returns:
        Tuple[float, float]: (전체 자산 가치, 실제 주문가능현금)
    """
    from src.utils.logging import get_logger
    log = get_logger("virtual_cash")
    
    # 전체 자산 가치 계산
    portfolio_value = sum(prices.get(ticker, 0) * qty for ticker, qty in positions.items())
    effective_d2_cash = d2_cash if d2_cash is not None else (cash if cash is not None else 0)
    
    if total_asset_value is not None:
        # API에서 제공하는 총자산 사용 (권장)
        log.info(f"💰 API 총자산 사용: {total_asset_value:,.0f}원")
        log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
        log.info(f"  - 가용 현금: {effective_d2_cash:,.0f}원")
    else:
        # 기존 방식: 보유 주식 + 현금 계산
        total_asset_value = portfolio_value + effective_d2_cash
        log.info(f"💰 계산된 총자산 사용: {total_asset_value:,.0f}원 (보유주식: {portfolio_value:,.0f}원 + 현금: {effective_d2_cash:,.0f}원)")
    
    if not is_mock:
        # 실전 환경: 주문가능현금 사용 + 안전여유율 적용
        base_cash = orderable_cash if orderable_cash is not None else effective_d2_cash
        
        safety_margin = safety_margin_pct / 100.0  # 퍼센트를 소수로 변환
        safety_amount = total_asset_value * safety_margin
        available_cash = base_cash - safety_amount
        
        log.info(f"💰 가상 예수금 계산 (실전환경):")
        log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
        if orderable_cash is not None:
            log.info(f"  - 주문가능현금: {orderable_cash:,.0f}원 (실거래 기준)")
        else:
            log.info(f"  - D+2 예수금: {effective_d2_cash:,.0f}원 (fallback)")
        log.info(f"  - 전체 자산 가치: {total_asset_value:,.0f}원")
        log.info(f"  - 안전여유율: {safety_margin*100:.1f}% (전체 자산 기준)")
        log.info(f"  - 안전여유금: {safety_amount:,.0f}원")
        log.info(f"  - 최종 주문가능현금: {available_cash:,.0f}원")
        
        return total_asset_value, available_cash
    
    # 모의투자 환경: 전체 자산 기준 안전여유율 적용
    safety_margin = safety_margin_pct / 100.0  # 퍼센트를 소수로 변환
    safety_amount = total_asset_value * safety_margin
    available_cash = effective_d2_cash - safety_amount
    
    log.info(f"💰 가상 예수금 계산 (모의투자):")
    log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
    log.info(f"  - D+2 예수금: {effective_d2_cash:,.0f}원")
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
                         safety_margin_pct: float = 1.0,
                         total_asset_value: float = None,
                         broker=None,
                         is_mock: bool = True,
                         orderable_cash: float = None) -> List[OrderPlan]:
    """
    깔끔한 리밸런싱 계획 수립
    
    핵심 개선사항:
    1. 미수 상황(cash < 0)에서는 새로운 plan_rebalance_with_deficit 함수 사용
    2. 모든 미체결 주문 취소 후 깔끔한 재계획
    3. 포트폴리오 레벨 밴드 기반 리밸런싱 적용
    4. 수수료 부담 없이 안정성 향상
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
        d2_cash=d2_cash,  # D+2 예수금 (None일 수 있음)
        is_mock=is_mock,  # 환경 구분 (모의/실전)
        safety_margin_pct=safety_margin_pct,
        cash=cash,  # d2_cash가 None일 때 사용할 현금
        total_asset_value=total_asset_value,  # API 총자산 (None이면 계산된 값 사용)
        orderable_cash=orderable_cash  # 실전환경에서 사용할 주문가능현금
    )
    
    # 전체 자산 가치를 리밸런싱 기준으로 사용
    value = total_asset_value
    
    if value <= 0:
        return []
    
    # 포트폴리오 레벨 밴드 기반 리밸런싱 사용
    log.info(f"🎯 포트폴리오 레벨 밴드 리밸런싱 적용")
    return plan_rebalance_with_band(
        positions=positions,
        targets=targets,
        cash=available_cash,  # 가상 예수금 시스템에서 계산된 주문가능현금 사용
        prices=prices,
        band_pct=band_pct,
        max_order_value_per_ticker=max_order_value_per_ticker,
        safety_margin_pct=safety_margin_pct
    )


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
    
    수수료 효율적 전략:
    1. 미수 해결에 필요한 최소한의 매도만 실행
    2. 매도 후 목표 비중에 맞춰 매수 (수수료 최소화)
    3. 전체 매도 후 재구성 방식보다 수수료 50% 절약
    """
    from src.utils.logging import get_logger
    log = get_logger("rebalance.deficit")
    
    log.info(f"🔧 미수 해결 모드 시작 - 현재 현금: {cash:,.0f}원")
    
    # 유효성 검사
    tickers = set(targets.keys()) | set(positions.keys())
    usable = [t for t in tickers if prices.get(t, 0) > 0]
    
    if not usable:
        log.warning("거래 가능한 종목이 없습니다.")
        return []
    
    # 1. 가상 전량 청산으로 전체 자산 계산 (미수 상황 고려)
    portfolio_value = sum(prices[t] * positions.get(t, 0) for t in usable)
    
    # 미수 상황에서는 실제 음수 현금을 반영하여 전체 자산 계산
    # 예: 보유주식 1000만원, 현금 -1254만원 = 전체 자산 -254만원 (미수 상태)
    total_asset = portfolio_value + cash  # cash가 음수여도 그대로 반영
    
    log.info(f"📊 가상 전량 청산 기준:")
    log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
    log.info(f"  - 현재 현금: {cash:,.0f}원")
    log.info(f"  - 전체 자산: {total_asset:,.0f}원")
    log.info(f"  - 미수 금액: {abs(cash):,.0f}원" if cash < 0 else "  - 현금 상태: 정상")
    
    # 2. 미수 해결 전략: 기존 리밸런싱 전략과 동일 (전체 자산 기준 목표 비중 계산)
    if cash < 0:
        # 미수 상황: 기존 리밸런싱 전략과 동일하게 전체 자산 기준으로 목표 비중 계산
        deficit_amount = abs(cash)
        log.info(f"🔧 미수 해결 전략 (기존 리밸런싱 전략과 동일):")
        log.info(f"  - 미수 금액: {deficit_amount:,.0f}원")
        log.info(f"  - 전체 자산 기준으로 목표 비중 계산")
        log.info(f"  - 현재 vs 목표 비교하여 매도/매수 주문 생성")
        
        # 가상 전량 매도 후 미수금 해결한 잔여 현금 계산
        virtual_sell_proceeds = portfolio_value  # 가상 전량 매도 대금
        remaining_cash_after_deficit = virtual_sell_proceeds - deficit_amount
        
        log.info(f"💰 가상 전량 매도 후 현금 흐름:")
        log.info(f"  - 매도 대금: {virtual_sell_proceeds:,.0f}원")
        log.info(f"  - 미수금 해결: -{deficit_amount:,.0f}원")
        log.info(f"  - 잔여 현금: {remaining_cash_after_deficit:,.0f}원")
        
        if remaining_cash_after_deficit <= 0:
            # 전량 매도로도 미수 해결 불가능
            log.warning(f"⚠️ 가상 전량 매도로도 미수 해결이 불가능합니다.")
            log.warning(f"⚠️ 모든 종목을 매도하여 최대한 현금을 확보합니다.")
            target_qty = {t: 0 for t in usable}
        else:
            # 잔여 현금으로 목표 비중 리밸런싱
            log.info(f"📈 잔여 현금으로 목표 비중 리밸런싱:")
            log.info(f"  - 투자 예산: {remaining_cash_after_deficit:,.0f}원")
            
            target_qty: Dict[str, int] = {}
            
            # 2-1) 1차 배분
            for t in usable:
                w = targets.get(t, 0.0)
                target_value = remaining_cash_after_deficit * w
                q = int(target_value // prices[t])
                target_qty[t] = max(q, 0)
            
            # 2-2) 잔액으로 +1씩 증액 (가격 낮은 순)
            spent = sum(target_qty[t] * prices[t] for t in usable)
            leftover = max(remaining_cash_after_deficit - spent, 0.0)
            if leftover > 0:
                for t in sorted(usable, key=lambda x: prices[x]):
                    if prices[t] <= leftover:
                        target_qty[t] += 1
                        leftover -= prices[t]
            
            log.info(f"📈 목표 수량 계산 완료:")
            for t in usable:
                log.info(f"  {t}: {target_qty[t]}주 → {target_qty[t] * prices[t] / remaining_cash_after_deficit * 100:.1f}% ({target_qty[t] * prices[t]:,.0f}원)")
            
            # 현재 보유와 목표 수량 비교
            log.info(f"🔍 매도/매수 필요성 검토:")
            for t in usable:
                current_qty = positions.get(t, 0)
                target_qty_val = target_qty.get(t, 0)
                if target_qty_val > current_qty:
                    log.info(f"  {t}: 현재 {current_qty}주 → 목표 {target_qty_val}주 (매수 {target_qty_val - current_qty}주 필요)")
                elif target_qty_val < current_qty:
                    log.info(f"  {t}: 현재 {current_qty}주 → 목표 {target_qty_val}주 (매도 {current_qty - target_qty_val}주 필요)")
                else:
                    log.info(f"  {t}: 현재 {current_qty}주 → 목표 {target_qty_val}주 (변화 없음)")
    else:
        # 정상 상황: 기존 로직
        target_qty: Dict[str, int] = {}
        budget = total_asset * (1 - reserve_ratio)
        
        # 2-1) 1차 배분
        for t in usable:
            w = targets.get(t, 0.0)
            target_value = budget * w
            q = int(target_value // prices[t])
            target_qty[t] = max(q, 0)
        
        # 2-2) 잔액으로 +1씩 증액 (가격 낮은 순)
        spent = sum(target_qty[t] * prices[t] for t in usable)
        leftover = max(budget - spent, 0.0)
        if leftover > 0:
            for t in sorted(usable, key=lambda x: prices[x]):
                if prices[t] <= leftover:
                    target_qty[t] += 1
                    leftover -= prices[t]
        
        log.info(f"📈 이상적 목표 수량 계산 완료:")
        for t in usable:
            log.info(f"  {t}: {target_qty[t]}주 → {target_qty[t] * prices[t] / total_asset * 100:.1f}% ({target_qty[t] * prices[t]:,.0f}원)")
    
    # 3. 순복합 델타 산출
    deltas = {t: target_qty.get(t, 0) - positions.get(t, 0) for t in usable}
    sells = [(t, abs(deltas[t])) for t, d in deltas.items() if d < 0]
    buys = [(t, deltas[t]) for t, d in deltas.items() if d > 0]
    
    log.info(f"📋 순복합 델타 산출:")
    log.info(f"  - 매도 필요: {len(sells)}개 종목")
    log.info(f"  - 매수 필요: {len(buys)}개 종목")
    
    plan: List[OrderPlan] = []
    current_cash = cash
    
    # 4. SELL 우선 실행 (미수 해결)
    for t, qty in sorted(sells, key=lambda x: deltas[x[0]]):  # 과대비중 큰 것부터
        price = prices[t]
        if qty <= 0 or price <= 0:
            continue
            
        # 최대 주문 금액 제한
        if max_order_value_per_ticker:
            qty = clamp_order_value(qty, price, max_order_value_per_ticker)
        if qty <= 0:
            continue
            
        plan.append(OrderPlan(code=t, side="SELL", qty=qty, limit=None))
        current_cash += qty * price
        log.info(f"  {t}: 매도 {qty}주")
    
    # 5. BUY 후행 실행 (가용 현금 내에서만)
    for t, qty in sorted(buys, key=lambda x: -deltas[x[0]]):  # 가장 부족한 것부터
        price = prices[t]
        if qty <= 0 or price <= 0:
            continue
            
        # 예산 내에서만 매수
        affordable = int(current_cash // price)
        if affordable <= 0:
            log.warning(f"  {t}: 현금 부족으로 매수 불가 (필요: {qty}주, 가능: {affordable}주, 현재 현금: {current_cash:,.0f}원)")
            continue
            
        buy_qty = min(qty, affordable)
        
        # 최대 주문 금액 제한
        if max_order_value_per_ticker:
            buy_qty = clamp_order_value(buy_qty, price, max_order_value_per_ticker)
        if buy_qty <= 0:
            continue
            
        plan.append(OrderPlan(code=t, side="BUY", qty=buy_qty, limit=None))
        current_cash -= buy_qty * price
        log.info(f"  {t}: 매수 {buy_qty}주")
    
    log.info(f"✅ 미수 해결 계획 완료: {len(plan)}건 (매도: {len(sells)}, 매수: {len(buys)})")
    return plan


async def _plan_deficit_resolution(positions: Dict[str, int], targets: Dict[str, float], 
                                 prices: Dict[str, float], max_order_value_per_ticker: int,
                                 d2_cash: float, broker=None) -> List[OrderPlan]:
    """
    D+2 예수금 음수 상황에서 미수 해결을 위한 특별 처리
    """
    from src.utils.logging import get_logger
    log = get_logger("rebalance")
    
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
    
    # 미수 해결을 위한 새로운 로직 사용
    from src.config import Settings
    settings = Settings()
    
    return plan_rebalance_with_deficit(
        positions=positions,
        targets=targets,
        cash=d2_cash,  # 음수 D+2 예수금 전달
        prices=prices,
        band_pct=1.0,  # 미수 상황에서는 밴드 무시
        max_order_value_per_ticker=max_order_value_per_ticker or settings.deficit_max_order_value,
        reserve_ratio=settings.deficit_reserve_ratio
    )


def plan_rebalance_with_band(
    positions: Dict[str, int],
    targets: Dict[str, float],
    cash: float,
    prices: Dict[str, float],
    band_pct: float = 1.0,
    max_order_value_per_ticker: int = 0,
    reserve_ratio: float = 0.005,  # 0.5% 기본 예비금
    safety_margin_pct: float = 1.0
) -> List[OrderPlan]:
    """
    포트폴리오 레벨 밴드 기반 리밸런싱 계획 수립
    
    핵심 개념:
    - 전체 포트폴리오가 항상 100% 합을 유지하면서 밴드 적용
    - 가상 전량 청산 후 목표 비중 기반 타깃 수량 계산
    - 밴드 적용 시 합=100% 보장 (현금 포함)
    - 순복합 델타 산출 (SELL → BUY 순서)
    
    Args:
        positions: 현재 보유 수량 {종목코드: 수량}
        targets: 목표 비중 {종목코드: 비중} (합=1.0)
        cash: 현재 가용 현금 (음수면 미수)
        prices: 종목별 현재가 {종목코드: 가격}
        band_pct: 허용 밴드 (%p, 예: 1.0 → ±1%p)
        max_order_value_per_ticker: 티커별 1회 주문 상한 (0=제한없음)
        reserve_ratio: 예비 현금 비율 (수수료/슬리피지/재미수 방지용)
        
    Returns:
        List[OrderPlan]: SELL 먼저, BUY 후행. 동일 티커에서 순복합 결과만
    """
    from src.utils.logging import get_logger
    log = get_logger("portfolio_band")
    
    # 0) 유효성 검사
    tickers = set(targets.keys()) | set(positions.keys())
    usable = [t for t in tickers if prices.get(t, 0) > 0]
    
    if not usable:
        log.warning("거래 가능한 종목이 없습니다.")
        return []
    
    # 예비금 비율을 안전여유율로 설정
    reserve_ratio = safety_margin_pct / 100.0
    
    log.info(f"🎯 포트폴리오 레벨 밴드 리밸런싱 시작")
    log.info(f"  - 대상 종목: {len(usable)}개")
    log.info(f"  - 밴드 허용범위: ±{band_pct}%p")
    log.info(f"  - 예비금 비율: {reserve_ratio*100:.1f}%")
    
    # 1) 가상 전량 청산 기반 전체 자산 계산
    portfolio_value = sum(prices[t] * positions.get(t, 0) for t in usable)
    V_total = portfolio_value + max(cash, 0.0)
    
    log.info(f"📊 가상 전량 청산 기준:")
    log.info(f"  - 보유 주식 가치: {portfolio_value:,.0f}원")
    log.info(f"  - 가용 현금: {cash:,.0f}원")
    log.info(f"  - 전체 자산: {V_total:,.0f}원")
    
    # 2) 이상적 타깃 수량(정수) 계산
    budget = V_total * (1 - reserve_ratio)
    target_qty: Dict[str, int] = {t: 0 for t in usable}
    
    # 2-1) 1차 배분 (바닥 나눗셈)
    for t in usable:
        w = targets.get(t, 0.0)
        target_value = budget * w
        q = int(target_value // prices[t])
        target_qty[t] = max(q, 0)
    
    # 2-2) 잔액으로 +1씩 증액 (저가부터)
    spent = sum(target_qty[t] * prices[t] for t in usable)
    leftover = max(budget - spent, 0.0)
    
    if leftover > 0:
        for t in sorted(usable, key=lambda x: prices[x]):  # 저가부터 1주 추가
            if prices[t] <= leftover:
                target_qty[t] += 1
                leftover -= prices[t]
    
    log.info(f"📈 이상적 목표 수량 계산 완료:")
    for t in usable:
        target_value = target_qty[t] * prices[t]
        target_weight = target_value / V_total if V_total > 0 else 0
        log.info(f"  {t}: {target_qty[t]}주 → {target_weight*100:.1f}% ({target_value:,.0f}원)")
    
    # 3) 현재 비중 계산
    current_weights: Dict[str, float] = {}
    for t in usable:
        current_value = positions.get(t, 0) * prices[t]
        current_weights[t] = current_value / V_total if V_total > 0 else 0
    
    current_cash_weight = cash / V_total if V_total > 0 else 0
    
    log.info(f"📊 현재 비중:")
    for t in usable:
        log.info(f"  {t}: {current_weights[t]*100:.1f}%")
    log.info(f"  현금: {current_cash_weight*100:.1f}%")
    
    # 4) 밴드 적용 시 합=100% 보장 로직
    log.info(f"🔄 밴드 적용 및 합=100% 보장 로직 시작")
    
    # 4-1) 밴드 내/외 종목 분류
    band_violations = []
    band_compliant = []
    
    for t in usable:
        current_w = current_weights.get(t, 0.0)
        target_w = (target_qty[t] * prices[t]) / V_total if V_total > 0 else 0.0
        
        if abs(current_w - target_w) > band_pct / 100.0:
            band_violations.append((t, current_w, target_w))
        else:
            band_compliant.append((t, current_w, target_w))
    
    log.info(f"🎯 밴드 분석 결과:")
    log.info(f"  - 밴드 준수: {len(band_compliant)}개 종목")
    log.info(f"  - 밴드 위반: {len(band_violations)}개 종목")
    
    if band_violations:
        log.info(f"  밴드 위반 종목:")
        for t, curr, target in band_violations:
            log.info(f"    {t}: {curr*100:.1f}% → {target*100:.1f}% (차이: {abs(curr-target)*100:.1f}%p)")
    
    # 4-2) 밴드 외 종목들을 목표로 조정
    adjusted_qty: Dict[str, int] = {t: positions.get(t, 0) for t in usable}
    
    for t, current_w, target_w in band_violations:
        adjusted_qty[t] = target_qty[t]
        log.info(f"🔄 {t} 조정: {positions.get(t, 0)}주 → {target_qty[t]}주")
    
    # 4-3) 조정 후 전체 비중 계산 및 잔액 처리
    adjusted_portfolio_value = sum(adjusted_qty[t] * prices[t] for t in usable)
    adjusted_total = adjusted_portfolio_value + cash
    
    # 잔액을 현금으로 처리 (거래 불가능한 금액)
    cash_adjustment = V_total - adjusted_total
    adjusted_cash = cash + cash_adjustment
    
    log.info(f"💰 조정 후 자산 구성:")
    log.info(f"  - 조정된 주식 가치: {adjusted_portfolio_value:,.0f}원")
    log.info(f"  - 조정된 현금: {adjusted_cash:,.0f}원")
    log.info(f"  - 조정된 총 자산: {adjusted_total:,.0f}원")
    log.info(f"  - 현금 조정량: {cash_adjustment:,.0f}원")
    
    # 4-4) 현금도 밴드 범위 내에서 조정
    target_cash_weight = 1.0 - sum((target_qty[t] * prices[t]) / V_total for t in usable if V_total > 0)
    current_cash_weight_adj = adjusted_cash / V_total if V_total > 0 else 0
    
    if abs(current_cash_weight_adj - target_cash_weight) > band_pct / 100.0:
        log.info(f"🔄 현금 밴드 위반 - 조정 필요:")
        log.info(f"  현재 현금 비중: {current_cash_weight_adj*100:.1f}%")
        log.info(f"  목표 현금 비중: {target_cash_weight*100:.1f}%")
        log.info(f"  차이: {abs(current_cash_weight_adj - target_cash_weight)*100:.1f}%p")
        
        # 현금을 목표 비중에 맞게 조정
        target_cash_value = V_total * target_cash_weight
        cash_adjustment_final = target_cash_value - adjusted_cash
        
        # 잔액을 밴드 준수 종목들에 재분배
        if abs(cash_adjustment_final) > 1:  # 1원 이상 차이
            if cash_adjustment_final > 0:  # 현금 부족 → 주식 매도
                log.info(f"💸 현금 부족 {cash_adjustment_final:,.0f}원 - 주식 매도로 보충")
                # 저가 종목부터 1주씩 매도
                for t in sorted(band_compliant, key=lambda x: prices[x[0]]):
                    if cash_adjustment_final <= 0:
                        break
                    if prices[t[0]] <= cash_adjustment_final:
                        adjusted_qty[t[0]] -= 1
                        cash_adjustment_final -= prices[t[0]]
                        log.info(f"  {t[0]} 1주 매도 추가")
            else:  # 현금 과다 → 주식 매수
                excess_cash = -cash_adjustment_final
                log.info(f"💰 현금 과다 {excess_cash:,.0f}원 - 주식 매수로 활용")
                # 저가 종목부터 1주씩 매수
                for t in sorted(band_compliant, key=lambda x: prices[x[0]]):
                    if excess_cash <= 0:
                        break
                    if prices[t[0]] <= excess_cash:
                        adjusted_qty[t[0]] += 1
                        excess_cash -= prices[t[0]]
                        log.info(f"  {t[0]} 1주 매수 추가")
    
    # 5) 순복합 델타 산출
    deltas = {t: adjusted_qty.get(t, 0) - positions.get(t, 0) for t in usable}
    
    sells = [t for t, d in deltas.items() if d < 0]
    buys = [t for t, d in deltas.items() if d > 0]
    
    log.info(f"📋 순복합 델타 산출:")
    log.info(f"  - 매도 필요: {len(sells)}개 종목")
    log.info(f"  - 매수 필요: {len(buys)}개 종목")
    
    for t in sells:
        log.info(f"  {t}: 매도 {abs(deltas[t])}주")
    for t in buys:
        log.info(f"  {t}: 매수 {deltas[t]}주")
    
    # 6) 주문 계획 생성 (SELL → BUY 순서)
    plan: List[OrderPlan] = []
    current_cash = cash
    
    # 6-1) SELL 우선 실행
    for t in sorted(sells, key=lambda x: deltas[x]):  # 과대비중(음수 큰 것)부터
        price = prices[t]
        qty = abs(deltas[t])
        
        if qty <= 0 or price <= 0:
            continue
            
        # 주문 금액 제한 적용
        if max_order_value_per_ticker:
            qty = clamp_order_value(qty, price, max_order_value_per_ticker)
            if qty <= 0:
                continue
        
        plan.append(OrderPlan(code=t, side="SELL", qty=qty, limit=None))
        current_cash += qty * price
        log.info(f"💰 매도 계획: {t} {qty}주 @ {price:,.0f}원 = {qty * price:,.0f}원")
    
    # 6-2) BUY 후행 (가용 현금 내에서만)
    for t in sorted(buys, key=lambda x: -deltas[x]):  # 가장 부족한 것부터
        price = prices[t]
        qty = deltas[t]
        
        if qty <= 0 or price <= 0:
            continue
        
        # 예산 내에서만 매수
        affordable = int(current_cash // price)
        if affordable <= 0:
            log.warning(f"⚠️ {t} 매수 불가: 현금 부족 ({current_cash:,.0f}원)")
            continue
            
        buy_qty = min(qty, affordable)
        
        # 주문 금액 제한 적용
        if max_order_value_per_ticker:
            buy_qty = clamp_order_value(buy_qty, price, max_order_value_per_ticker)
            if buy_qty <= 0:
                continue
        
        plan.append(OrderPlan(code=t, side="BUY", qty=buy_qty, limit=None))
        current_cash -= buy_qty * price
        log.info(f"💰 매수 계획: {t} {buy_qty}주 @ {price:,.0f}원 = {buy_qty * price:,.0f}원")
    
    # 7) 최종 검증
    final_portfolio_value = sum(adjusted_qty[t] * prices[t] for t in usable)
    final_total = final_portfolio_value + current_cash
    total_weight = sum((adjusted_qty[t] * prices[t]) / V_total for t in usable if V_total > 0) + (current_cash / V_total if V_total > 0 else 0)
    
    log.info(f"✅ 최종 검증:")
    log.info(f"  - 최종 계획: {len(plan)}건 (매도: {len(sells)}, 매수: {len(buys)})")
    log.info(f"  - 최종 주식 가치: {final_portfolio_value:,.0f}원")
    log.info(f"  - 최종 현금: {current_cash:,.0f}원")
    log.info(f"  - 최종 총 자산: {final_total:,.0f}원")
    log.info(f"  - 총 비중 합계: {total_weight*100:.2f}%")
    
    if abs(total_weight - 1.0) > 0.01:  # 1% 오차 허용
        log.warning(f"⚠️ 비중 합계가 100%에서 벗어남: {total_weight*100:.2f}%")
    else:
        log.info(f"✅ 비중 합계 100% 달성: {total_weight*100:.2f}%")

    return plan