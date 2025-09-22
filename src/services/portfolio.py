from __future__ import annotations
from typing import Dict, Tuple, List

from src.services.brokers.base import Broker
from src.services.daily_orders import parse_daily_orders, get_pending_orders, get_pending_positions


async def get_positions_and_cash(broker: Broker) -> tuple[dict[str, int], float, float, float]:
    """브로커 잔고 응답에서 보유수량 dict, 주문가능현금, D+2예수금, 순자산금액을 파싱한다."""
    bal = await broker.fetch_balance()

    # 포지션 파싱
    positions: Dict[str, int] = {}
    items = bal.get("output1") or bal.get("output") or []
    if isinstance(items, list):
        for it in items:
            code = it.get("pdno") or it.get("종목번호") or it.get("PDNO")
            try:
                qty = int(float(it.get("hldg_qty") or it.get("보유수량") or it.get("HLDG_QTY") or 0))
            except Exception:
                qty = 0
            if code:
                positions[code] = qty

    # 현금/예수금 파싱(가능한 공통키 시도)
    def _pick(d: dict, keys: list[str]):
        for k in keys:
            if k in d and d.get(k) not in (None, ""):
                return d.get(k)
        low = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            v = low.get(k.lower())
            if v not in (None, ""):
                return v
        return None

    summary_raw = bal.get("output2")
    if isinstance(summary_raw, list) and summary_raw:
        summary = summary_raw[0] if isinstance(summary_raw[0], dict) else {}
    elif isinstance(summary_raw, dict):
        summary = summary_raw
    else:
        summary = bal.get("output") or {}
        if not isinstance(summary, dict):
            summary = {}

    # balance 명령과 동일한 로직으로 예수금 파싱
    ord_cash = _pick(summary, [
        "ord_psbl_cash", "ORD_PSBL_CASH", "주문가능현금",
        "ord_psbl_cash_amt", "ord_psbl_amt", "주문가능현금액",
    ])
    dep_total = _pick(summary, [
        "dnca_tot_amt", "DNCA_TOT_AMT", "예수금총액",
        "dpsast_totamt", "DPSAST_TOTAMT", "예탁자산총액"
    ])
    
    # D+1 예수금 (다음날 정산 예수금)
    nxdy_excc = _pick(summary, [
        "nxdy_excc_amt", "NXDY_EXCC_AMT", "D+1예수금"
    ])
    
    # D+2 예수금 (2일 후 정산 예수금) - 실제 주문 가능 금액
    d2_excc = _pick(summary, [
        "d2_excc_amt", "D2_EXCC_AMT", "D+2예수금",
        "nxdy_excc_amt2", "NXDY_EXCC_AMT2", "다음날예수금2",
        "prvs_rcdl_excc_amt", "PRVS_RCDL_EXCC_AMT", "이전정산예수금"
    ])
    
    # 실전 거래 관행에 따른 예수금 우선순위
    # 1순위: ord_psbl_cash (주문가능현금) - 현재 시점 실시간으로 매수 가능한 금액
    # 2순위: nxdy_excc_amt (D+2 예수금) - 실제 익일 기준으로 출금 또는 매수 가능한 금액  
    # 3순위: nxdy_excc (D+1 예수금) - 참고용
    # 4순위: dnca_tot_amt (총예수금) - 계좌 내 모든 현금성 자산의 총합 (즉시 사용 불가능할 수 있음)
    
    # 단순화된 우선순위: 주문가능현금 > D+2예수금 > D+1예수금 > 총예수금
    cash_value = ord_cash or d2_excc or nxdy_excc or dep_total
    
    # 사용된 예수금 필드 로깅 (실전 거래 관행 기준)
    cash_source = ""
    if ord_cash is not None:
        cash_source = "주문가능현금 (실거래 기준 최우선)"
    elif d2_excc is not None:
        if float(d2_excc) >= 0:
            cash_source = "D+2예수금 (익일 출금/매수 가능)"
        else:
            cash_source = "D+2예수금 (음수)"
    elif nxdy_excc is not None:
        cash_source = "D+1예수금 (참고용)"
    elif dep_total is not None:
        cash_source = "총예수금 (계좌 총 현금, 즉시 사용 불가능할 수 있음)"
    else:
        cash_source = "기본값(0)"
    
    try:
        cash = float(cash_value) if cash_value is not None else 0.0
    except Exception:
        cash = 0.0
    
    # D+2 예수금 값도 반환 (미수 해결을 위해)
    try:
        d2_cash_value = float(d2_excc) if d2_excc is not None else None
    except Exception:
        d2_cash_value = None

    # 순자산금액 파싱 (nass_amt)
    nass_amt = _pick(summary, [
        "nass_amt", "NASS_AMT", "순자산금액",
        "tot_evlu_amt", "TOT_EVLU_AMT", "총평가금액"
    ])
    
    try:
        net_asset_value = float(nass_amt) if nass_amt is not None else 0.0
    except Exception:
        net_asset_value = 0.0

    # 로깅 (디버깅용)
    from src.utils.logging import get_logger
    log = get_logger("portfolio")
    log.debug(f"예수금 파싱: {cash_source} = {cash:,.0f}원")
    if d2_cash_value is not None:
        log.debug(f"D+2 예수금: {d2_cash_value:,.0f}원")
    log.debug(f"순자산금액: {net_asset_value:,.0f}원")

    return positions, cash, d2_cash_value, net_asset_value


async def get_positions_with_daily_orders(broker: Broker) -> Tuple[Dict[str, int], Dict[str, int], float, float, float]:
    """
    현재 보유 포지션 + 미체결 주문을 고려한 예상 포지션을 반환
    
    Args:
        broker: 브로커 인스턴스
    
    Returns:
        Tuple[Dict[str, int], Dict[str, int], float, float, float]:
        - 현재 보유 포지션 {종목코드: 수량} (이미 당일 체결 주문 반영됨)
        - 미체결 주문 고려 예상 포지션 {종목코드: 수량}  
        - 주문가능현금 (이미 당일 체결 주문 반영됨)
        - D+2 예수금 (미수 해결을 위해)
        - 순자산금액 (리밸런싱 기준)
    """
    # 1. 현재 잔고 조회
    positions, cash, d2_cash, net_asset = await get_positions_and_cash(broker)
    
    # 2. 당일 주문체결 조회
    try:
        daily_response = await broker.fetch_daily_orders()
        daily_orders = parse_daily_orders(daily_response)
        
        # 3. 미체결 주문만 추출
        pending_orders = get_pending_orders(daily_orders)
        pending_positions = get_pending_positions(pending_orders)
        
        # 4. 최종 포지션 계산
        # 현재 포지션(이미 당일 체결 주문 반영됨) + 미체결 주문만 추가
        expected_positions = positions.copy()
        
        # 미체결 주문만 반영 (체결된 주문은 이미 현재 포지션에 포함됨)
        for code, pending_qty in pending_positions.items():
            expected_positions[code] = expected_positions.get(code, 0) + pending_qty
        
        # 현금은 그대로 사용 (체결 주문으로 인한 현금 변동은 이미 반영됨)
        adjusted_cash = cash
        
        return positions, expected_positions, adjusted_cash, d2_cash, net_asset
        
    except Exception as e:
        # 일별 주문 조회 실패 시 현재 포지션만 반환
        from src.utils.logging import get_logger
        log = get_logger("portfolio")
        log.warning(f"일별 주문 조회 실패: {e}, 현재 포지션만 사용")
        return positions, positions.copy(), cash, d2_cash, net_asset


async def get_positions_with_pending(broker: Broker) -> Tuple[Dict[str, int], Dict[str, int], float]:
    """
    기존 함수와의 호환성을 위한 래퍼 함수
    """
    return await get_positions_with_daily_orders(broker)


async def get_positions(broker: Broker) -> Dict[str, int]:
    """브로커 잔고 응답에서 보유수량만 파싱한다."""
    bal = await broker.fetch_balance()

    # 포지션 파싱
    positions: Dict[str, int] = {}
    items = bal.get("output1") or bal.get("output") or []
    if isinstance(items, list):
        for it in items:
            code = it.get("pdno") or it.get("종목번호") or it.get("PDNO")
            try:
                qty = int(float(it.get("hldg_qty") or it.get("보유수량") or it.get("HLDG_QTY") or 0))
            except Exception:
                qty = 0
            if code:
                positions[code] = qty

    return positions


async def get_orderable_cash(broker: Broker) -> float:
    """브로커 주문가능현금 조회 API에서 주문가능현금을 파싱한다."""
    from src.utils.logging import get_logger
    log = get_logger("portfolio")
    
    try:
        # 주문가능조회 API 호출
        cash_data = await broker.fetch_orderable_cash()
        
        # 응답에서 주문가능현금 파싱
        def _pick(d: dict, keys: list[str]):
            for k in keys:
                if k in d and d.get(k) not in (None, ""):
                    return d.get(k)
            low = {str(k).lower(): v for k, v in d.items()}
            for k in keys:
                v = low.get(k.lower())
                if v not in (None, ""):
                    return v
            return None

        summary_raw = cash_data.get("output2")
        if isinstance(summary_raw, list) and summary_raw:
            summary = summary_raw[0] if isinstance(summary_raw[0], dict) else {}
        elif isinstance(summary_raw, dict):
            summary = summary_raw
        else:
            summary = cash_data.get("output") or {}
            if not isinstance(summary, dict):
                summary = {}

        # 주문가능현금 파싱
        ord_cash = _pick(summary, [
            "ord_psbl_cash", "ORD_PSBL_CASH", "주문가능현금",
            "ord_psbl_cash_amt", "ord_psbl_amt", "주문가능현금액",
        ])
        
        try:
            cash = float(ord_cash) if ord_cash is not None else 0.0
        except Exception:
            cash = 0.0
            
        log.info(f"주문가능현금 조회 성공: {cash:,.0f}원")
        return cash
        
    except Exception as e:
        log.error(f"주문가능현금 조회 실패: {e}")
        return 0.0


async def get_prices(broker: Broker, codes: List[str]) -> dict[str, float]:
    return await broker.fetch_prices(codes)


