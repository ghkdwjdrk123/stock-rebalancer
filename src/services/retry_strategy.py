"""
재시도 전략 서비스

이상 감지 시 지속적으로 재시도하는 메커니즘을 제공합니다.
"""
import asyncio
import time
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from enum import Enum
from src.utils.logging import get_logger

log = get_logger("retry_strategy")

class RetryReason(Enum):
    """재시도 사유"""
    API_ERROR = "api_error"
    NETWORK_ERROR = "network_error"
    PARTIAL_EXECUTION = "partial_execution"
    CANCELLATION_FAILED = "cancellation_failed"
    ORDER_FAILED = "order_failed"
    DATA_VALIDATION = "data_validation"

@dataclass
class RetryConfig:
    """재시도 설정"""
    max_attempts: int = 5  # 최대 재시도 횟수
    base_delay: float = 2.0  # 기본 지연 시간(초)
    max_delay: float = 60.0  # 최대 지연 시간(초)
    backoff_multiplier: float = 1.5  # 지연 시간 증가 배수
    jitter: bool = True  # 지연 시간 랜덤화
    success_threshold: float = 0.8  # 성공 임계값 (80% 이상 성공 시 완료)
    abort_on_critical: bool = False  # 치명적 오류 시 중단 여부

@dataclass
class RetryAttempt:
    """재시도 시도 정보"""
    attempt_number: int
    timestamp: float
    reason: RetryReason
    success_count: int
    total_count: int
    success_rate: float
    delay_used: float

class PersistentRetryManager:
    """지속적 재시도 관리자"""
    
    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
        self.attempts: List[RetryAttempt] = []
        self.start_time = time.time()
        
    def calculate_delay(self, attempt_number: int) -> float:
        """지연 시간 계산 (지수 백오프 + 지터)"""
        delay = min(
            self.config.base_delay * (self.config.backoff_multiplier ** attempt_number),
            self.config.max_delay
        )
        
        if self.config.jitter:
            # 지터: ±25% 랜덤 변동
            import random
            jitter_factor = random.uniform(0.75, 1.25)
            delay *= jitter_factor
            
        return delay
    
    def should_continue_retry(self, success_count: int, total_count: int) -> Tuple[bool, str]:
        """재시도 계속 여부 판단"""
        success_rate = success_count / total_count if total_count > 0 else 0
        
        # 성공률이 임계값 이상이면 완료
        if success_rate >= self.config.success_threshold:
            return False, f"성공률 {success_rate:.1%}로 목표 달성"
        
        # 최대 시도 횟수 초과
        if len(self.attempts) >= self.config.max_attempts:
            return False, f"최대 재시도 횟수 {self.config.max_attempts}회 초과"
        
        # 경과 시간이 너무 길면 중단 (30분)
        if time.time() - self.start_time > 1800:
            return False, "재시도 시간 초과 (30분)"
        
        return True, f"성공률 {success_rate:.1%}로 재시도 계속"
    
    async def execute_with_retry(self, 
                                operation: Callable,
                                validation_func: Callable = None,
                                operation_name: str = "작업") -> Dict[str, Any]:
        """재시도와 함께 작업 실행"""
        
        log.info(f"🔄 {operation_name} 지속적 재시도 시작 (최대 {self.config.max_attempts}회)")
        
        attempt_number = 0
        while attempt_number < self.config.max_attempts:
            attempt_number += 1
            
            try:
                log.info(f"📋 {operation_name} 시도 {attempt_number}/{self.config.max_attempts}")
                
                # 작업 실행
                result = await operation()
                
                # 검증 함수가 있으면 결과 검증
                if validation_func:
                    is_valid, message = await validation_func(result)
                    if not is_valid:
                        log.warning(f"⚠️ {operation_name} 검증 실패: {message}")
                        
                        # 재시도 시도 기록
                        attempt = RetryAttempt(
                            attempt_number=attempt_number,
                            timestamp=time.time(),
                            reason=RetryReason.DATA_VALIDATION,
                            success_count=0,
                            total_count=1,
                            success_rate=0.0,
                            delay_used=0.0
                        )
                        self.attempts.append(attempt)
                        
                        # 재시도 계속 여부 확인
                        should_continue, reason = self.should_continue_retry(0, 1)
                        if not should_continue:
                            log.error(f"❌ {operation_name} 최종 실패: {reason}")
                            return {
                                "success": False,
                                "message": f"{operation_name} 재시도 실패: {reason}",
                                "attempts": len(self.attempts),
                                "total_time": time.time() - self.start_time
                            }
                        
                        # 지연 후 재시도
                        delay = self.calculate_delay(attempt_number - 1)
                        log.info(f"⏳ {delay:.1f}초 후 재시도...")
                        await asyncio.sleep(delay)
                        continue
                
                # 성공
                log.info(f"✅ {operation_name} 성공 (시도 {attempt_number}회)")
                return {
                    "success": True,
                    "result": result,
                    "attempts": attempt_number,
                    "total_time": time.time() - self.start_time,
                    "message": f"{operation_name} 성공"
                }
                
            except Exception as e:
                log.warning(f"⚠️ {operation_name} 시도 {attempt_number} 실패: {e}")
                
                # 재시도 시도 기록
                attempt = RetryAttempt(
                    attempt_number=attempt_number,
                    timestamp=time.time(),
                    reason=RetryReason.API_ERROR,
                    success_count=0,
                    total_count=1,
                    success_rate=0.0,
                    delay_used=0.0
                )
                self.attempts.append(attempt)
                
                # 재시도 계속 여부 확인
                should_continue, reason = self.should_continue_retry(0, 1)
                if not should_continue:
                    log.error(f"❌ {operation_name} 최종 실패: {reason}")
                    return {
                        "success": False,
                        "error": str(e),
                        "attempts": len(self.attempts),
                        "total_time": time.time() - self.start_time,
                        "message": f"{operation_name} 재시도 실패: {reason}"
                    }
                
                # 지연 후 재시도
                delay = self.calculate_delay(attempt_number - 1)
                log.info(f"⏳ {delay:.1f}초 후 재시도...")
                await asyncio.sleep(delay)
        
        # 최대 시도 횟수 초과
        log.error(f"❌ {operation_name} 최대 재시도 횟수 초과")
        return {
            "success": False,
            "message": f"{operation_name} 최대 재시도 횟수 초과",
            "attempts": len(self.attempts),
            "total_time": time.time() - self.start_time
        }

class BatchRetryManager:
    """배치 작업 재시도 관리자"""
    
    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
        self.attempts: List[RetryAttempt] = []
        self.start_time = time.time()
        
    async def execute_batch_with_retry(self,
                                     batch_operation: Callable,
                                     batch_name: str = "배치 작업") -> Dict[str, Any]:
        """배치 작업 재시도 실행"""
        
        log.info(f"🔄 {batch_name} 지속적 재시도 시작 (성공률 {self.config.success_threshold:.0%} 목표)")
        
        attempt_number = 0
        while attempt_number < self.config.max_attempts:
            attempt_number += 1
            
            try:
                log.info(f"📋 {batch_name} 시도 {attempt_number}/{self.config.max_attempts}")
                
                # 배치 작업 실행
                results = await batch_operation()
                
                # 성공/실패 분석
                success_count = sum(1 for r in results if r.get("success", False))
                total_count = len(results)
                success_rate = success_count / total_count if total_count > 0 else 0
                
                # 재시도 시도 기록
                attempt = RetryAttempt(
                    attempt_number=attempt_number,
                    timestamp=time.time(),
                    reason=RetryReason.PARTIAL_EXECUTION if success_rate < 1.0 else RetryReason.API_ERROR,
                    success_count=success_count,
                    total_count=total_count,
                    success_rate=success_rate,
                    delay_used=0.0
                )
                self.attempts.append(attempt)
                
                log.info(f"📊 {batch_name} 결과: {success_count}/{total_count}건 성공 ({success_rate:.1%})")
                
                # 성공률 확인 (총 개수가 0인 경우는 정상으로 처리)
                if total_count == 0:
                    log.info(f"✅ {batch_name} 완료 - 처리할 항목이 없음")
                    return {
                        "success": True,
                        "results": results,
                        "success_rate": 1.0,  # 0개 항목은 100% 성공으로 처리
                        "attempts": attempt_number,
                        "total_time": time.time() - self.start_time,
                        "message": f"{batch_name} 완료 - 처리할 항목이 없음"
                    }
                elif success_rate >= self.config.success_threshold:
                    log.info(f"✅ {batch_name} 목표 달성 (성공률 {success_rate:.1%})")
                    return {
                        "success": True,
                        "results": results,
                        "success_rate": success_rate,
                        "attempts": attempt_number,
                        "total_time": time.time() - self.start_time,
                        "message": f"{batch_name} 성공 (성공률 {success_rate:.1%})"
                    }
                
                # 재시도 계속 여부 확인
                should_continue, reason = self.should_continue_retry(success_count, total_count)
                if not should_continue:
                    log.error(f"❌ {batch_name} 최종 실패: {reason}")
                    return {
                        "success": False,
                        "results": results,
                        "success_rate": success_rate,
                        "attempts": len(self.attempts),
                        "total_time": time.time() - self.start_time,
                        "message": f"{batch_name} 재시도 실패: {reason}"
                    }
                
                # 지연 후 재시도
                delay = self.calculate_delay(attempt_number - 1)
                log.info(f"⏳ {delay:.1f}초 후 재시도... (목표 성공률: {self.config.success_threshold:.0%})")
                await asyncio.sleep(delay)
                
            except Exception as e:
                log.warning(f"⚠️ {batch_name} 시도 {attempt_number} 예외: {e}")
                
                # 재시도 시도 기록
                attempt = RetryAttempt(
                    attempt_number=attempt_number,
                    timestamp=time.time(),
                    reason=RetryReason.API_ERROR,
                    success_count=0,
                    total_count=1,
                    success_rate=0.0,
                    delay_used=0.0
                )
                self.attempts.append(attempt)
                
                # 재시도 계속 여부 확인
                should_continue, reason = self.should_continue_retry(0, 1)
                if not should_continue:
                    log.error(f"❌ {batch_name} 최종 실패: {reason}")
                    return {
                        "success": False,
                        "error": str(e),
                        "attempts": len(self.attempts),
                        "total_time": time.time() - self.start_time,
                        "message": f"{batch_name} 재시도 실패: {reason}"
                    }
                
                # 지연 후 재시도
                delay = self.calculate_delay(attempt_number - 1)
                log.info(f"⏳ {delay:.1f}초 후 재시도...")
                await asyncio.sleep(delay)
        
        # 최대 시도 횟수 초과
        log.error(f"❌ {batch_name} 최대 재시도 횟수 초과")
        return {
            "success": False,
            "message": f"{batch_name} 최대 재시도 횟수 초과",
            "attempts": len(self.attempts),
            "total_time": time.time() - self.start_time
        }
    
    def should_continue_retry(self, success_count: int, total_count: int) -> Tuple[bool, str]:
        """재시도 계속 여부 판단"""
        success_rate = success_count / total_count if total_count > 0 else 0
        
        # 성공률이 임계값 이상이면 완료
        if success_rate >= self.config.success_threshold:
            return False, f"성공률 {success_rate:.1%}로 목표 달성"
        
        # 최대 시도 횟수 초과
        if len(self.attempts) >= self.config.max_attempts:
            return False, f"최대 재시도 횟수 {self.config.max_attempts}회 초과"
        
        # 경과 시간이 너무 길면 중단 (30분)
        if time.time() - self.start_time > 1800:
            return False, "재시도 시간 초과 (30분)"
        
        return True, f"성공률 {success_rate:.1%}로 재시도 계속"
    
    def calculate_delay(self, attempt_number: int) -> float:
        """지연 시간 계산 (지수 백오프 + 지터)"""
        delay = min(
            self.config.base_delay * (self.config.backoff_multiplier ** attempt_number),
            self.config.max_delay
        )
        
        if self.config.jitter:
            # 지터: ±25% 랜덤 변동
            import random
            jitter_factor = random.uniform(0.75, 1.25)
            delay *= jitter_factor
            
        return delay
