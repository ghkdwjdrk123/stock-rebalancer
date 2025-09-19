"""
트랜잭션 보호 서비스

비트랜잭션 환경에서의 안전장치를 제공합니다.
"""
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from src.utils.logging import get_logger

log = get_logger("transaction_protection")

@dataclass
class ExecutionCheckpoint:
    """실행 체크포인트"""
    order_index: int
    order_info: Dict[str, Any]
    timestamp: float
    status: str  # "PENDING", "SUCCESS", "FAILED"

class TransactionProtectionManager:
    """트랜잭션 보호 관리자"""
    
    def __init__(self, broker, checkpoint_interval: int = 1):
        self.broker = broker
        self.checkpoint_interval = checkpoint_interval
        self.checkpoints: List[ExecutionCheckpoint] = []
        
    async def execute_with_checkpoints(self, orders: List[Any]) -> Dict[str, Any]:
        """체크포인트를 통한 안전한 실행"""
        log.info(f"🛡️ 체크포인트 기반 실행 시작: {len(orders)}건")
        
        results = {
            "total_orders": len(orders),
            "successful_orders": 0,
            "failed_orders": 0,
            "checkpoints": [],
            "rollback_required": False,
            "partial_execution": False
        }
        
        for i, order in enumerate(orders):
            # 체크포인트 생성
            checkpoint = ExecutionCheckpoint(
                order_index=i,
                order_info={
                    "code": order.code,
                    "side": order.side,
                    "qty": order.qty,
                    "limit": order.limit
                },
                timestamp=asyncio.get_event_loop().time(),
                status="PENDING"
            )
            self.checkpoints.append(checkpoint)
            
            try:
                log.info(f"📍 체크포인트 {i+1}/{len(orders)}: {order.side} {order.code} x {order.qty}")
                
                # 주문 실행
                result = await self.broker.order_cash(
                    code=order.code,
                    side=order.side,
                    qty=order.qty,
                    price=order.limit
                )
                
                if result and result.get("success"):
                    checkpoint.status = "SUCCESS"
                    results["successful_orders"] += 1
                    log.info(f"✅ 체크포인트 {i+1} 성공")
                else:
                    checkpoint.status = "FAILED"
                    results["failed_orders"] += 1
                    log.error(f"❌ 체크포인트 {i+1} 실패")
                    
                    # 실패 시 부분 실행 감지
                    if results["successful_orders"] > 0:
                        results["partial_execution"] = True
                        log.warning("⚠️ 부분 실행 감지 - 롤백 필요성 검토")
                    
            except Exception as e:
                checkpoint.status = "FAILED"
                results["failed_orders"] += 1
                log.error(f"❌ 체크포인트 {i+1} 예외: {e}")
                
                # 예외 시 부분 실행 감지
                if results["successful_orders"] > 0:
                    results["partial_execution"] = True
                    log.warning("⚠️ 부분 실행 감지 - 롤백 필요성 검토")
            
            # 체크포인트 저장
            results["checkpoints"].append(checkpoint.__dict__)
            
            # 주문 간 지연
            if i < len(orders) - 1:
                await asyncio.sleep(1.0)
        
        # 최종 분석
        success_rate = (results["successful_orders"] / results["total_orders"]) * 100
        
        if results["partial_execution"]:
            log.warning(f"⚠️ 부분 실행 완료: {results['successful_orders']}/{results['total_orders']}건 성공 ({success_rate:.1f}%)")
            results["rollback_required"] = await self._should_rollback(results)
        else:
            log.info(f"✅ 완전 실행: {results['successful_orders']}/{results['total_orders']}건 성공 ({success_rate:.1f}%)")
        
        return results
    
    async def _should_rollback(self, results: Dict[str, Any]) -> bool:
        """롤백 필요성 판단"""
        success_rate = (results["successful_orders"] / results["total_orders"]) * 100
        
        # 50% 미만 성공 시 롤백 권장
        if success_rate < 50:
            log.error(f"🚨 성공률 {success_rate:.1f}% - 롤백 강력 권장")
            return True
        
        # 70% 미만 성공 시 롤백 검토
        elif success_rate < 70:
            log.warning(f"⚠️ 성공률 {success_rate:.1f}% - 롤백 검토 필요")
            return True
        
        return False
    
    async def generate_rollback_plan(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """롤백 계획 생성"""
        rollback_plan = []
        
        for checkpoint_data in results["checkpoints"]:
            if checkpoint_data["status"] == "SUCCESS":
                order_info = checkpoint_data["order_info"]
                
                # 반대 방향 주문 생성
                opposite_side = "SELL" if order_info["side"] == "BUY" else "BUY"
                rollback_order = {
                    "code": order_info["code"],
                    "side": opposite_side,
                    "qty": order_info["qty"],
                    "limit": order_info["limit"],
                    "reason": "ROLLBACK"
                }
                rollback_plan.append(rollback_order)
        
        if rollback_plan:
            log.info(f"🔄 롤백 계획 생성: {len(rollback_plan)}건")
        else:
            log.info("ℹ️ 롤백할 성공 주문이 없습니다.")
            
        return rollback_plan

class ConservativeExecutionManager:
    """보수적 실행 관리자 (단계별 확인)"""
    
    def __init__(self, broker, confirmation_required: bool = True):
        self.broker = broker
        self.confirmation_required = confirmation_required
        
    async def execute_conservatively(self, orders: List[Any]) -> Dict[str, Any]:
        """보수적 실행 (단계별 확인)"""
        log.info(f"🛡️ 보수적 실행 시작: {len(orders)}건")
        
        # 매도 주문과 매수 주문 분리
        sell_orders = [o for o in orders if o.side == "SELL"]
        buy_orders = [o for o in orders if o.side == "BUY"]
        
        results = {
            "sell_orders": {"total": len(sell_orders), "success": 0, "failed": 0},
            "buy_orders": {"total": len(buy_orders), "success": 0, "failed": 0},
            "overall_success": False
        }
        
        # 1단계: 매도 주문만 실행
        if sell_orders:
            log.info(f"📤 1단계: 매도 주문 {len(sell_orders)}건 실행")
            sell_results = await self._execute_batch(sell_orders, "SELL")
            results["sell_orders"]["success"] = sum(1 for r in sell_results if r["success"])
            results["sell_orders"]["failed"] = len(sell_results) - results["sell_orders"]["success"]
            
            # 매도 실패 시 전체 중단
            if results["sell_orders"]["failed"] > 0:
                log.error("❌ 매도 주문 실패 - 전체 실행 중단")
                return results
        
        # 2단계: 매수 주문 실행 (매도 성공 후에만)
        if buy_orders:
            log.info(f"📥 2단계: 매수 주문 {len(buy_orders)}건 실행")
            buy_results = await self._execute_batch(buy_orders, "BUY")
            results["buy_orders"]["success"] = sum(1 for r in buy_results if r["success"])
            results["buy_orders"]["failed"] = len(buy_results) - results["buy_orders"]["success"]
        
        # 전체 성공 여부 판단
        total_success = results["sell_orders"]["success"] + results["buy_orders"]["success"]
        total_orders = len(orders)
        results["overall_success"] = (total_success == total_orders)
        
        success_rate = (total_success / total_orders) * 100
        log.info(f"🎯 보수적 실행 완료: {total_success}/{total_orders}건 성공 ({success_rate:.1f}%)")
        
        return results
    
    async def _execute_batch(self, orders: List[Any], side: str) -> List[Dict[str, Any]]:
        """배치 실행"""
        results = []
        
        for i, order in enumerate(orders):
            log.info(f"📋 {side} 주문 {i+1}/{len(orders)}: {order.code} x {order.qty}")
            
            try:
                result = await self.broker.order_cash(
                    code=order.code,
                    side=order.side,
                    qty=order.qty,
                    price=order.limit
                )
                
                if result and result.get("success"):
                    results.append({"success": True, "order_id": result.get("order_id")})
                    log.info(f"✅ {side} 주문 성공: {order.code}")
                else:
                    results.append({"success": False, "error": "API_ERROR"})
                    log.error(f"❌ {side} 주문 실패: {order.code}")
                    
            except Exception as e:
                results.append({"success": False, "error": str(e)})
                log.error(f"❌ {side} 주문 예외: {order.code} - {e}")
            
            # 주문 간 지연
            if i < len(orders) - 1:
                await asyncio.sleep(1.0)
        
        return results
