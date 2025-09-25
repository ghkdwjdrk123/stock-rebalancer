# src/adapters/kis/domestic.py
from __future__ import annotations
import os
from typing import Any, Dict
from src.adapters.kis.client import KISClient
from src.adapters.kis.api_config import get_api_path, get_tr_id, api_config_manager, is_order_api_supported, get_unsupported_api_message, is_pension_account

# 가격 조회는 계좌 유형과 무관하므로 기존 방식 유지
PATH_PRICE = os.getenv("KIS_PATH_PRICE", "/uapi/domestic-stock/v1/quotations/inquire-price")


class KISDomestic:
    def __init__(self, client: KISClient, account8: str, pd_code: str, env: str = "dev"):
        self.c = client
        self.acc8 = account8
        self.pd = pd_code
        self.env = (env or "dev").strip().lower()
        
        # 계좌 유형 확인 및 로깅
        from src.utils.logging import get_logger
        self.log = get_logger("kis.domestic")
        
        if not api_config_manager.is_supported_account_type(pd_code):
            raise ValueError(f"지원하지 않는 계좌 상품코드: {pd_code}. "
                           f"지원 코드: {api_config_manager.get_supported_account_types()}")
        
        account_type_name = api_config_manager.get_account_type_name(pd_code)
        self.log.info(f"계좌 유형: {account_type_name} (상품코드: {pd_code})")

    def _get_tr_id(self, api_type: str) -> str:
        """계좌 상품코드와 환경에 따른 TR_ID 반환"""
        return get_tr_id(self.pd, api_type, self.env)
    
    def _get_api_path(self, api_type: str) -> str:
        """계좌 상품코드에 따른 API 경로 반환"""
        return get_api_path(self.pd, api_type)

    async def inquire_balance(self) -> Dict[str, Any]:
        # OFL_YN: 모의=Y, 실전=N
        ofl_yn = "Y" if self.env in ("dev", "development", "mock", "test") else "N"
        
        # 모든 계좌 유형에서 일반계좌 API 사용
        params = {
            "CANO": self.acc8, 
            "ACNT_PRDT_CD": self.pd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": ofl_yn,
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        # 계좌 유형에 따른 API 경로와 TR_ID 사용
        api_path = self._get_api_path("balance")
        tr_id = self._get_tr_id("balance")
        
        self.log.info(f"잔고 조회 - API: {api_path}, TR_ID: {tr_id}")
        return await self.c.get(api_path, tr_id=tr_id, params=params)

    async def inquire_price(self, code: str) -> Dict[str, Any]:
        params = {"FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":code}
        # 가격 조회는 계좌 유형과 무관하므로 기존 방식 유지
        if self.env in ("prod", "production", "real", "live"):
            tr_id = os.getenv("KIS_TR_PRICE_PROD") or os.getenv("KIS_TR_PRICE")
        else:
            tr_id = os.getenv("KIS_TR_PRICE_DEV") or os.getenv("KIS_TR_PRICE")
        return await self.c.get(PATH_PRICE, tr_id=tr_id, params=params)

    async def inquire_orderable_cash(self) -> Dict[str, Any]:
        """주문가능현금 조회"""
        # OFL_YN: 모의=Y, 실전=N
        ofl_yn = "Y" if self.env in ("dev", "development", "mock", "test") else "N"
        params = {
            "CANO": self.acc8,
            "ACNT_PRDT_CD": self.pd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": ofl_yn,
            "INQR_DVSN": "00",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        # 계좌 유형에 따른 API 경로와 TR_ID 사용
        api_path = self._get_api_path("orderable_cash")
        tr_id = self._get_tr_id("orderable_cash")
        
        self.log.info(f"주문가능현금 조회 - API: {api_path}, TR_ID: {tr_id}")
        return await self.c.get(api_path, tr_id=tr_id, params=params)

    async def inquire_daily_orders(self, date: str = ""):
        """
        주식일별주문체결조회 - 미체결 주문 포함
        Args:
            date: 조회일자 (YYYYMMDD, 빈 문자열이면 당일)
        """
        # 조회일자가 없으면 당일로 설정
        if not date:
            from datetime import datetime
            date = datetime.now().strftime("%Y%m%d")
        
        # 모든 계좌 유형에서 일반계좌 API 사용
        params = {
            "CANO": self.acc8,
            "ACNT_PRDT_CD": self.pd,
            "INQR_STRT_DT": date,
            "INQR_END_DT": date,
            "SLL_BUY_DVSN_CD": "00",  # 전체 (매수+매도)
            "INQR_DVSN": "00",  # 전체 (체결+미체결)
            "PDNO": "",  # 전체 종목
            "CCLD_DVSN": "00",  # 전체 (체결+미체결)
            "ORD_GNO_BRNO": "",  # 전체 주문번호
            "ODNO": "",  # 전체 주문번호
            "INQR_DVSN_3": "00",  # 전체
            "INQR_DVSN_1": "",  # 빈값
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        # 계좌 유형에 따른 API 경로와 TR_ID 사용
        api_path = self._get_api_path("daily_orders")
        tr_id = self._get_tr_id("daily_orders")
        
        self.log.info(f"일별 주문체결 조회 - 날짜: {date}, API: {api_path}, TR_ID: {tr_id}")
        return await self.c.get(api_path, tr_id=tr_id, params=params)

    async def order_cash(self, code: str, qty: int, price: float | None, side: str):
        # 연금계좌 주문 API 지원 여부 확인
        if not is_order_api_supported(self.pd, "order_cash"):
            message = get_unsupported_api_message(self.pd, "order_cash")
            self.log.error(message)
            raise ValueError(message)
        
        # 시장가 주문 시 더미 값 사용 (공식 가이드 권장)
        if price is None:
            ord_dvsn = "01"  # 시장가
            ord_unpr = "1"   # 시장가 주문 시 더미 값 (공식 FAQ 권장)
        else:
            ord_dvsn = "00"  # 지정가
            ord_unpr = str(int(price))  # 정수로 변환
        
        body = {"CANO": self.acc8, "ACNT_PRDT_CD": self.pd, "PDNO": code,
                "ORD_DVSN": ord_dvsn, "ORD_QTY": str(qty),
                "ORD_UNPR": ord_unpr}
        
        # 계좌 유형에 따른 API 경로 사용
        api_path = self._get_api_path("order_cash")
        
        # TR_ID를 .env에서 가져오기 (주문은 기존 방식 유지)
        if side.upper() == "BUY":
            tr_key = "ORDER_BUY"
        else:
            tr_key = "ORDER_SELL"
        
        if self.env in ("prod", "production", "real", "live"):
            tr_id = os.getenv(f"KIS_TR_{tr_key}_PROD") or os.getenv(f"KIS_TR_{tr_key}")
        else:
            tr_id = os.getenv(f"KIS_TR_{tr_key}_DEV") or os.getenv(f"KIS_TR_{tr_key}")
        
        # 디버깅: 주문 파라미터 로깅
        self.log.info(f"주문 파라미터 - API: {api_path}, TR_ID: {tr_id}, Body: {body}, Side: {side}")
        
        return await self.c.post(api_path, tr_id=tr_id, body=body, need_hash=True)

    async def cancel_order(self, order_id: str, code: str, qty: int):
        """
        미체결 주문 취소
        Args:
            order_id: 주문번호 (ord_gno_brno)
            code: 종목코드
            qty: 취소할 수량
        """
        # 연금계좌 주문취소 API 지원 여부 확인
        if not is_order_api_supported(self.pd, "cancel_order"):
            message = get_unsupported_api_message(self.pd, "cancel_order")
            self.log.error(message)
            raise ValueError(message)
        
        body = {
            "CANO": self.acc8,
            "ACNT_PRDT_CD": self.pd,
            "ORGN_ODNO": order_id,      # 원주문번호 (미체결 주문번호)
            "ORD_DVSN": "00",           # 주문구분 (원주문과 동일하게 유지)
            "RVSE_CNCL_DVSN_CD": "02",  # 정정취소구분코드 (02: 취소)
            "ORD_QTY": str(qty),        # 취소할 수량
            "ORD_UNPR": "0",            # 주문단가 (취소시 0)
            "QTY_ALL_ORD_YN": "N"       # 전체수량주문여부 (N: 부분취소)
        }
        
        # 계좌 유형에 따른 API 경로 사용
        api_path = self._get_api_path("cancel_order")
        
        # 취소 주문의 TR_ID
        if self.env in ("prod", "production", "real", "live"):
            tr_id = os.getenv("KIS_TR_ORDER_CANCEL_PROD") or os.getenv("KIS_TR_ORDER_CANCEL")
        else:
            tr_id = os.getenv("KIS_TR_ORDER_CANCEL_DEV") or os.getenv("KIS_TR_ORDER_CANCEL")
        
        self.log.info(f"주문 취소 파라미터 - API: {api_path}, TR_ID: {tr_id}, Body: {body}")
        
        return await self.c.post(api_path, tr_id=tr_id, body=body, need_hash=True)
