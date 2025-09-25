"""
계좌 상품코드별 API 설정 관리
확장성 있는 구조로 설계하여 새로운 상품코드 추가 시 쉽게 확장 가능
"""

from __future__ import annotations
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class AccountType(Enum):
    """계좌 유형 정의"""
    REGULAR = "01"      # 일반 위탁계좌
    PENSION = "22"      # 개인연금/퇴직연금 계좌


@dataclass
class APIConfig:
    """API 설정 정보"""
    path: str           # API 경로
    tr_id_key: str      # TR_ID 환경변수 키 (예: "BALANCE")
    description: str    # API 설명


@dataclass
class AccountAPIConfig:
    """계좌 유형별 API 설정"""
    balance: APIConfig
    daily_orders: APIConfig
    orderable_cash: APIConfig
    order_cash: APIConfig
    cancel_order: APIConfig


class APIConfigManager:
    """계좌 상품코드별 API 설정 관리자"""
    
    def __init__(self):
        self._configs: Dict[str, AccountAPIConfig] = {}
        self._initialize_configs()
    
    def _initialize_configs(self):
        """계좌 유형별 API 설정 초기화"""
        
        # 일반 위탁계좌 (01) 설정
        self._configs[AccountType.REGULAR.value] = AccountAPIConfig(
            balance=APIConfig(
                path=os.getenv("KIS_PATH_BALANCE_REGULAR", "/uapi/domestic-stock/v1/trading/inquire-balance"),
                tr_id_key="BALANCE",
                description="일반계좌 잔고조회"
            ),
            daily_orders=APIConfig(
                path=os.getenv("KIS_PATH_DAILY_ORDERS_REGULAR", "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"),
                tr_id_key="DAILY_ORDERS",
                description="일반계좌 일별주문체결조회"
            ),
            orderable_cash=APIConfig(
                path=os.getenv("KIS_PATH_ORDERABLE_CASH_REGULAR", "/uapi/domestic-stock/v1/trading/inquire-psbl-order"),
                tr_id_key="ORDERABLE_CASH",
                description="일반계좌 주문가능현금조회"
            ),
            order_cash=APIConfig(
                path=os.getenv("KIS_PATH_ORDER_CASH_REGULAR", "/uapi/domestic-stock/v1/trading/order-cash"),
                tr_id_key="ORDER_CASH",
                description="일반계좌 현금주문"
            ),
            cancel_order=APIConfig(
                path=os.getenv("KIS_PATH_CANCEL_ORDER_REGULAR", "/uapi/domestic-stock/v1/trading/order-rvsecncl"),
                tr_id_key="ORDER_CANCEL",
                description="일반계좌 주문취소"
            )
        )
        
        # 개인연금/퇴직연금 계좌 (22) 설정 - 일반계좌 API 사용
        self._configs[AccountType.PENSION.value] = AccountAPIConfig(
            balance=APIConfig(
                path=os.getenv("KIS_PATH_BALANCE_REGULAR", "/uapi/domestic-stock/v1/trading/inquire-balance"),
                tr_id_key="BALANCE",
                description="연금계좌 잔고조회 (일반계좌 API 사용)"
            ),
            daily_orders=APIConfig(
                path=os.getenv("KIS_PATH_DAILY_ORDERS_REGULAR", "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"),
                tr_id_key="DAILY_ORDERS",
                description="연금계좌 일별주문체결조회 (일반계좌 API 사용)"
            ),
            orderable_cash=APIConfig(
                path=os.getenv("KIS_PATH_ORDERABLE_CASH_REGULAR", "/uapi/domestic-stock/v1/trading/inquire-psbl-order"),
                tr_id_key="ORDERABLE_CASH",
                description="연금계좌 주문가능현금조회 (일반계좌 API 사용)"
            ),
            # 연금계좌는 주문 API 미지원
            order_cash=APIConfig(
                path="",  # 빈 문자열로 설정
                tr_id_key="",
                description="연금계좌 현금주문 (미지원)"
            ),
            cancel_order=APIConfig(
                path="",  # 빈 문자열로 설정
                tr_id_key="",
                description="연금계좌 주문취소 (미지원)"
            )
        )
    
    def get_api_config(self, account_product_code: str, api_type: str) -> APIConfig:
        """
        계좌 상품코드와 API 타입에 따른 설정 반환
        
        Args:
            account_product_code: 계좌 상품코드 (01, 22 등)
            api_type: API 타입 (balance, daily_orders, orderable_cash, order_cash, cancel_order)
        
        Returns:
            APIConfig: 해당 API 설정
            
        Raises:
            ValueError: 지원하지 않는 계좌 상품코드나 API 타입인 경우
        """
        if account_product_code not in self._configs:
            raise ValueError(f"지원하지 않는 계좌 상품코드: {account_product_code}. "
                           f"지원 코드: {list(self._configs.keys())}")
        
        account_config = self._configs[account_product_code]
        
        if not hasattr(account_config, api_type):
            raise ValueError(f"지원하지 않는 API 타입: {api_type}. "
                           f"지원 타입: {[attr for attr in dir(account_config) if not attr.startswith('_')]}")
        
        return getattr(account_config, api_type)
    
    def get_supported_account_types(self) -> list[str]:
        """지원하는 계좌 유형 목록 반환"""
        return list(self._configs.keys())
    
    def is_supported_account_type(self, account_product_code: str) -> bool:
        """계좌 유형 지원 여부 확인"""
        return account_product_code in self._configs
    
    def add_account_type(self, account_product_code: str, config: AccountAPIConfig):
        """
        새로운 계좌 유형 추가 (확장성)
        
        Args:
            account_product_code: 새로운 계좌 상품코드
            config: 해당 계좌 유형의 API 설정
        """
        self._configs[account_product_code] = config
    
    def get_account_type_name(self, account_product_code: str) -> str:
        """계좌 상품코드에 따른 계좌 유형명 반환"""
        type_mapping = {
            AccountType.REGULAR.value: "일반 위탁계좌",
            AccountType.PENSION.value: "개인연금/퇴직연금 계좌"
        }
        return type_mapping.get(account_product_code, f"알 수 없는 계좌 유형 ({account_product_code})")


# 전역 인스턴스
api_config_manager = APIConfigManager()


def get_api_config(account_product_code: str, api_type: str) -> APIConfig:
    """편의 함수: API 설정 조회"""
    return api_config_manager.get_api_config(account_product_code, api_type)


def get_tr_id(account_product_code: str, api_type: str, env: str = "dev") -> str:
    """
    계좌 상품코드와 환경에 따른 TR_ID 반환
    
    Args:
        account_product_code: 계좌 상품코드
        api_type: API 타입
        env: 환경 (dev/prod)
    
    Returns:
        str: TR_ID
    """
    config = get_api_config(account_product_code, api_type)
    tr_id_key = config.tr_id_key
    
    # 환경별 TR_ID 조회
    if env in ("prod", "production", "real", "live"):
        tr_id = os.getenv(f"KIS_TR_{tr_id_key}_PROD") or os.getenv(f"KIS_TR_{tr_id_key}")
    else:
        tr_id = os.getenv(f"KIS_TR_{tr_id_key}_DEV") or os.getenv(f"KIS_TR_{tr_id_key}")
    
    if not tr_id:
        raise ValueError(f"TR_ID not found: KIS_TR_{tr_id_key}_DEV/PROD or KIS_TR_{tr_id_key} must be set in .env")
    
    return tr_id


def get_api_path(account_product_code: str, api_type: str) -> str:
    """API 경로 반환"""
    config = get_api_config(account_product_code, api_type)
    return config.path


def is_pension_account(account_product_code: str) -> bool:
    """연금계좌 여부 확인"""
    return account_product_code == AccountType.PENSION.value


def is_order_api_supported(account_product_code: str, api_type: str) -> bool:
    """
    계좌 유형에서 해당 API 사용 가능 여부 확인
    
    Args:
        account_product_code: 계좌 상품코드
        api_type: API 타입
    
    Returns:
        bool: API 사용 가능 여부
    """
    if is_pension_account(account_product_code):
        # 연금계좌는 조회 API만 지원 (일반계좌 API 사용)
        return api_type in ["balance", "daily_orders", "orderable_cash"]
    else:
        # 일반계좌는 모든 API 지원
        return True


def get_unsupported_api_message(account_product_code: str, api_type: str) -> str:
    """
    지원하지 않는 API에 대한 안내 메시지 반환
    
    Args:
        account_product_code: 계좌 상품코드
        api_type: API 타입
    
    Returns:
        str: 안내 메시지
    """
    account_type_name = api_config_manager.get_account_type_name(account_product_code)
    
    if api_type == "order_cash":
        return f"❌ {account_type_name}에서는 주문(매수/매도) API가 지원되지 않습니다."
    elif api_type == "cancel_order":
        return f"❌ {account_type_name}에서는 주문취소 API가 지원되지 않습니다."
    else:
        return f"❌ {account_type_name}에서는 {api_type} API가 지원되지 않습니다."
