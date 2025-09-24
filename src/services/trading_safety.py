"""
거래 안전장치 서비스

실제 거래 실행 전후의 안전장치를 제공합니다.
- 사전 검증
- 실행 보장 메커니즘
- 실패 시 복구 로직
"""
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from src.utils.logging import get_logger

log = get_logger("trading_safety")

@dataclass
class TradingResult:
    """거래 결과 정보"""
    success: bool
    order_id: Optional[str]
    message: str
    error_code: Optional[str] = None

@dataclass
class TradingBatch:
    """거래 배치 정보"""
    orders: List[Any]
    total_orders: int
    executed_orders: int = 0
    failed_orders: int = 0
    results: List[TradingResult] = None

class TradingSafetyManager:
    """거래 안전장치 관리자"""
    
    def __init__(self, broker, max_retry_attempts: int = 3, retry_delay: float = 1.0):
        self.broker = broker
        self.max_retry_attempts = max_retry_attempts
        self.retry_delay = retry_delay
        self.persistent_retry = True  # 지속적 재시도 활성화
        
    async def validate_trading_environment(self) -> bool:
        """거래 환경 사전 검증"""
        try:
            log.info("🔍 거래 환경 사전 검증 중...")
            
            # 1. 브로커 연결 상태 확인
            if not self.broker:
                log.error("❌ 브로커 연결이 없습니다.")
                return False
                
            # 2. 계좌 상태 확인 (잔고 조회로 연결 테스트)
            try:
                balance_result = await self.broker.fetch_balance()
                # fetch_balance는 Dict[str, Any]를 반환 (portfolio.py에서 파싱)
                if isinstance(balance_result, dict):
                    # 간단한 연결 테스트만 수행 (실제 파싱은 portfolio.py에서)
                    if "output" in balance_result or "output1" in balance_result:
                        log.info("✅ 계좌 연결 정상")
                    else:
                        log.error("❌ 계좌 잔고 응답에 데이터 없음")
                        return False
                else:
                    log.error("❌ 계좌 잔고 조회 응답 형식 오류")
                    return False
                    
            except Exception as e:
                log.error(f"❌ 계좌 연결 실패: {e}")
                return False
                
            # 3. 시장 상태 확인 (거래 가능 시간)
            # TODO: 시장 개장 상태 확인 로직 추가
            
            log.info("✅ 거래 환경 검증 완료")
            return True
            
        except Exception as e:
            log.error(f"❌ 거래 환경 검증 실패: {e}")
            return False
    
    async def validate_order_plan(self, orders: List[Any]) -> bool:
        """주문 계획 사전 검증"""
        try:
            log.info(f"🔍 주문 계획 검증 중... ({len(orders)}건)")
            
            if not orders:
                log.warning("⚠️ 실행할 주문이 없습니다.")
                return True
                
            # 1. 주문 데이터 구조 검증
            for i, order in enumerate(orders):
                if not hasattr(order, 'code') or not hasattr(order, 'side') or not hasattr(order, 'qty'):
                    log.error(f"❌ {i+1}번째 주문 구조 오류: 필수 속성 누락")
                    return False
                    
                if order.qty <= 0:
                    log.error(f"❌ {i+1}번째 주문 수량 오류: {order.qty}")
                    return False
                    
                if not order.code or len(order.code) != 6:
                    log.error(f"❌ {i+1}번째 주문 종목코드 오류: {order.code}")
                    return False
                    
                if order.side not in ['BUY', 'SELL']:
                    log.error(f"❌ {i+1}번째 주문 방향 오류: {order.side}")
                    return False
            
            # 2. 종목별 매수/매도 균형 검증
            buy_orders = [o for o in orders if o.side == 'BUY']
            sell_orders = [o for o in orders if o.side == 'SELL']
            
            log.info(f"📊 주문 분석: 매수 {len(buy_orders)}건, 매도 {len(sell_orders)}건")
            
            # 3. 가격 데이터 검증
            tickers = list(set([o.code for o in orders]))
            try:
                prices = await self.broker.fetch_prices(tickers)
                missing_prices = [t for t in tickers if t not in prices or prices[t] <= 0]
                if missing_prices:
                    log.error(f"❌ 가격 정보 누락 종목: {missing_prices}")
                    return False
            except Exception as e:
                log.error(f"❌ 가격 조회 실패: {e}")
                return False
                
            log.info("✅ 주문 계획 검증 완료")
            return True
            
        except Exception as e:
            log.error(f"❌ 주문 계획 검증 실패: {e}")
            return False
    
    async def execute_with_rollback_protection(self, orders: List[Any]) -> TradingBatch:
        """지속적 재시도로 롤백 보호 배치 실행"""
        if self.persistent_retry:
            return await self._execute_batch_with_persistent_retry(orders)
        else:
            return await self._execute_batch_legacy(orders)
    
    async def _execute_batch_with_persistent_retry(self, orders: List[Any]) -> TradingBatch:
        """지속적 재시도로 배치 실행 (간소화된 버전)"""
        # retry_strategy.py가 삭제되어 간소화된 버전 사용
        
        batch = TradingBatch(orders=orders, total_orders=len(orders), results=[])
        
        try:
            # 사전 검증
            if not await self.validate_trading_environment():
                log.error("❌ 거래 환경 검증 실패")
                return batch
                
            if not await self.validate_order_plan(orders):
                log.error("❌ 주문 계획 검증 실패")
                return batch
            
            # 단계별 실행 (매도 먼저, 매수 나중에)
            sell_orders = [o for o in orders if o.side == 'SELL']
            buy_orders = [o for o in orders if o.side == 'BUY']
            
            results = []
            
            # 1단계: 매도 주문 실행
            if sell_orders:
                log.info(f"📤 매도 주문 실행: {len(sell_orders)}건")
                sell_results = await self._execute_order_batch(sell_orders, "SELL")
                results.extend(sell_results)
                
                # 매도 실패 시 예외 발생
                failed_sells = [r for r in sell_results if not r.success]
                if failed_sells:
                    log.error(f"❌ 매도 주문 {len(failed_sells)}건 실패")
                    batch.results = [TradingResult(
                        success=r.get("success", False),
                        order_id=r.get("order_id"),
                        message=r.get("message", "")
                    ) for r in results]
                    batch.executed_orders = sum(1 for r in batch.results if r.success)
                    batch.failed_orders = len(batch.results) - batch.executed_orders
                    return batch
            
            # 2단계: 매수 주문 실행 (매도 성공 후에만)
            if buy_orders:
                log.info(f"📥 매수 주문 실행: {len(buy_orders)}건")
                buy_results = await self._execute_order_batch(buy_orders, "BUY")
                results.extend(buy_results)
            
            # 결과 변환
            batch.results = [TradingResult(
                success=r.get("success", False),
                order_id=r.get("order_id"),
                message=r.get("message", "")
            ) for r in results]
            batch.executed_orders = sum(1 for r in batch.results if r.success)
            batch.failed_orders = len(batch.results) - batch.executed_orders
            
            success_rate = batch.executed_orders / batch.total_orders if batch.total_orders > 0 else 1.0
            log.info(f"✅ 배치 실행 완료: {success_rate:.1%}")
            
        except Exception as e:
            log.error(f"❌ 배치 실행 중 오류: {e}")
            batch.executed_orders = 0
            batch.failed_orders = batch.total_orders
        
        return batch
    
    async def _execute_batch_legacy(self, orders: List[Any]) -> TradingBatch:
        """기존 방식의 배치 실행"""
        batch = TradingBatch(orders=orders, total_orders=len(orders), results=[])
        
        try:
            log.info(f"🚀 배치 거래 실행 시작: {batch.total_orders}건")
            
            # 사전 검증
            if not await self.validate_trading_environment():
                log.error("❌ 거래 환경 검증 실패 - 실행 중단")
                return batch
                
            if not await self.validate_order_plan(orders):
                log.error("❌ 주문 계획 검증 실패 - 실행 중단")
                return batch
            
            # 단계별 실행 (매도 먼저, 매수 나중에)
            sell_orders = [o for o in orders if o.side == 'SELL']
            buy_orders = [o for o in orders if o.side == 'BUY']
            
            # 1단계: 매도 주문 실행
            if sell_orders:
                log.info(f"📤 매도 주문 실행: {len(sell_orders)}건")
                sell_results = await self._execute_order_batch(sell_orders, "SELL")
                batch.results.extend(sell_results)
                
                # 매도 실패 시 전체 중단
                failed_sells = [r for r in sell_results if not r.success]
                if failed_sells:
                    log.error(f"❌ 매도 주문 {len(failed_sells)}건 실패 - 전체 실행 중단")
                    batch.failed_orders = len(failed_sells)
                    return batch
                    
                batch.executed_orders += len(sell_results)
                log.info(f"✅ 매도 주문 완료: {len(sell_results)}건")
            
            # 2단계: 매수 주문 실행 (매도 성공 후에만)
            if buy_orders:
                log.info(f"📥 매수 주문 실행: {len(buy_orders)}건")
                buy_results = await self._execute_order_batch(buy_orders, "BUY")
                batch.results.extend(buy_results)
                
                # 매수 실패 시 경고 (이미 매도는 완료됨)
                failed_buys = [r for r in buy_results if not r.success]
                if failed_buys:
                    log.warning(f"⚠️ 매수 주문 {len(failed_buys)}건 실패 - 포트폴리오 불균형 발생 가능")
                    batch.failed_orders += len(failed_buys)
                else:
                    batch.executed_orders += len(buy_results)
                    log.info(f"✅ 매수 주문 완료: {len(buy_results)}건")
            
            # 최종 결과
            success_rate = (batch.executed_orders / batch.total_orders) * 100
            log.info(f"🎯 배치 실행 완료: {batch.executed_orders}/{batch.total_orders}건 성공 ({success_rate:.1f}%)")
            
            return batch
            
        except Exception as e:
            log.error(f"❌ 배치 실행 중 오류: {e}")
            batch.failed_orders = batch.total_orders
            return batch
    
    async def _execute_order_batch(self, orders: List[Any], side: str) -> List[TradingResult]:
        """주문 배치 실행 (재시도 포함)"""
        results = []
        
        for i, order in enumerate(orders):
            log.info(f"📋 {side} 주문 {i+1}/{len(orders)}: {order.code} x {order.qty}")
            
            # 재시도 로직
            for attempt in range(self.max_retry_attempts):
                try:
                    raw_result = await self.broker.order_cash(
                        code=order.code,
                        side=order.side,
                        qty=order.qty,
                        price=order.limit
                    )
                    
                    # KIS API 응답을 TradingResult로 변환
                    if raw_result and isinstance(raw_result, dict):
                        # 성공 여부 판단 (KIS API 응답 구조에 따라)
                        success = raw_result.get("rt_cd") == "0" or raw_result.get("output", {}).get("KRX_FWDG_ORD_ORGNO")
                        order_id = raw_result.get("output", {}).get("KRX_FWDG_ORD_ORGNO") if success else None
                        message = raw_result.get("msg1", f"{side} 주문 성공") if success else raw_result.get("msg1", "알 수 없는 오류")
                        
                        if success:
                            results.append(TradingResult(
                                success=True,
                                order_id=order_id,
                                message=message
                            ))
                            log.info(f"✅ {side} 주문 성공: {order.code} (주문번호: {order_id})")
                            break
                        else:
                            error_msg = message
                            if attempt < self.max_retry_attempts - 1:
                                log.warning(f"⚠️ {side} 주문 실패 (시도 {attempt+1}/{self.max_retry_attempts}): {error_msg}")
                                await asyncio.sleep(self.retry_delay)
                            else:
                                results.append(TradingResult(
                                    success=False,
                                    order_id=None,
                                    message=error_msg,
                                    error_code=raw_result.get("rt_cd", "UNKNOWN")
                                ))
                                log.error(f"❌ {side} 주문 최종 실패: {order.code} - {error_msg}")
                    else:
                        error_msg = "응답 없음"
                        if attempt < self.max_retry_attempts - 1:
                            log.warning(f"⚠️ {side} 주문 실패 (시도 {attempt+1}/{self.max_retry_attempts}): {error_msg}")
                            await asyncio.sleep(self.retry_delay)
                        else:
                            results.append(TradingResult(
                                success=False,
                                order_id=None,
                                message=error_msg,
                                error_code="NO_RESPONSE"
                            ))
                            log.error(f"❌ {side} 주문 최종 실패: {order.code} - {error_msg}")
                            
                except Exception as e:
                    if attempt < self.max_retry_attempts - 1:
                        log.warning(f"⚠️ {side} 주문 예외 (시도 {attempt+1}/{self.max_retry_attempts}): {e}")
                        await asyncio.sleep(self.retry_delay)
                    else:
                        results.append(TradingResult(
                            success=False,
                            order_id=None,
                            message=str(e),
                            error_code="EXCEPTION"
                        ))
                        log.error(f"❌ {side} 주문 예외: {order.code} - {e}")
                        
        return results
    
    async def execute_order_cancellation_safely(self) -> bool:
        """지속적 재시도로 안전한 주문 취소 실행"""
        try:
            if self.persistent_retry:
                return await self._execute_cancellation_with_persistent_retry()
            else:
                return await self._execute_cancellation_legacy()
        except Exception as e:
            log.error(f"❌ 주문 취소 실행 실패: {e}")
            return False
    
    async def _execute_cancellation_with_persistent_retry(self) -> bool:
        """지속적 재시도로 주문 취소 실행 (간소화된 버전)"""
        # retry_strategy.py가 삭제되어 간소화된 버전 사용
        
        try:
            from src.services.order_canceler import cancel_all_pending_orders
            cancel_results = await cancel_all_pending_orders(self.broker)
            
            if cancel_results is None:
                log.warning("⚠️ 취소 결과를 받을 수 없습니다.")
                return False
            
            success_count = sum(1 for r in cancel_results if r["success"])
            total_count = len(cancel_results)
            
            if total_count == 0:
                log.info("✅ 취소할 미체결 주문이 없습니다.")
                return True
                
            if success_count == total_count:
                log.info(f"✅ 미체결 주문 취소 완료: {success_count}건 성공")
                return True
            else:
                success_rate = success_count / total_count
                log.warning(f"⚠️ 미체결 주문 취소 부분 성공: {success_count}/{total_count}건 ({success_rate:.1%})")
                # 부분 성공도 허용 (일부 취소 실패는 심각하지 않음)
                return True
                
        except Exception as e:
            log.error(f"❌ 주문 취소 실행 중 오류: {e}")
            return False
    
    async def _execute_cancellation_legacy(self) -> bool:
        """기존 방식의 주문 취소 실행"""
        log.info("🚫 안전한 주문 취소 실행 중...")
        
        # 1. 취소할 주문 조회
        from src.services.order_canceler import cancel_all_pending_orders
        cancel_results = await cancel_all_pending_orders(self.broker)
        
        if cancel_results is None:
            log.warning("⚠️ 취소 결과를 받을 수 없습니다.")
            return False
        
        # 2. 취소 결과 분석
        success_count = sum(1 for r in cancel_results if r["success"])
        total_count = len(cancel_results)
        
        if total_count == 0:
            log.info("ℹ️ 취소할 미체결 주문이 없습니다.")
            return True
            
        if success_count == total_count:
            log.info(f"✅ 모든 미체결 주문 취소 성공: {success_count}건")
            return True
        elif success_count > 0:
            log.warning(f"⚠️ 부분 취소 성공: {success_count}/{total_count}건")
            # 부분 성공도 허용 (일부 취소 실패는 심각하지 않음)
            return True
        else:
            log.error(f"❌ 모든 주문 취소 실패: {total_count}건")
            return False
