# src/adapters/kis/domestic.py
from __future__ import annotations
import os
from typing import Any, Dict
from src.adapters.kis.client import KISClient

PATH_BALANCE = os.getenv("KIS_PATH_BALANCE", "/uapi/domestic-stock/v1/trading/inquire-balance")

PATH_ORDER_CASH = os.getenv("KIS_PATH_ORDER_CASH", "/uapi/domestic-stock/v1/trading/order-cash")

PATH_PRICE = os.getenv("KIS_PATH_PRICE", "/uapi/domestic-stock/v1/quotations/inquire-price")

PATH_ORDERABLE_CASH = os.getenv("KIS_PATH_ORDERABLE_CASH", "/uapi/domestic-stock/v1/trading/inquire-psbl-order")

PATH_DAILY_ORDERS = os.getenv("KIS_PATH_DAILY_ORDERS", "/uapi/domestic-stock/v1/trading/inquire-daily-ccld")

PATH_CANCEL_ORDER = os.getenv("KIS_PATH_CANCEL_ORDER", "/uapi/domestic-stock/v1/trading/order-rvsecncl")


class KISDomestic:
    def __init__(self, client: KISClient, account8: str, pd_code: str, env: str = "dev"):
        self.c = client
        self.acc8 = account8
        self.pd = pd_code
        self.env = (env or "dev").strip().lower()

    def _tr(self, key: str) -> str:
        # key 예: BALANCE, ORDER_BUY, ORDER_SELL, PRICE
        # 환경별 TR_ID를 .env에서 가져오기 (환경변수가 없으면 에러)
        if self.env in ("prod", "production", "real", "live"):
            tr_id = os.getenv(f"KIS_TR_{key}_PROD") or os.getenv(f"KIS_TR_{key}")
        else:
            tr_id = os.getenv(f"KIS_TR_{key}_DEV") or os.getenv(f"KIS_TR_{key}")
        
        if not tr_id:
            raise ValueError(f"TR_ID not found: KIS_TR_{key}_DEV/PROD or KIS_TR_{key} must be set in .env")
        
        return tr_id

    async def inquire_balance(self) -> Dict[str, Any]:
        # OFL_YN: 모의=Y, 실전=N
        ofl_yn = "Y" if self.env in ("dev", "development", "mock", "test") else "N"
        params = {"CANO": self.acc8, "ACNT_PRDT_CD": self.pd,
                  "AFHR_FLPR_YN":"N","OFL_YN":ofl_yn, "INQR_DVSN":"02","UNPR_DVSN":"01",
                  "FUND_STTL_ICLD_YN":"N","FNCG_AMT_AUTO_RDPT_YN":"N","PRCS_DVSN":"00",
                  "CTX_AREA_FK100":"","CTX_AREA_NK100":""}
        # TR_ID를 .env에서 가져오기
        tr = self._tr("BALANCE")
        return await self.c.get(PATH_BALANCE, tr_id=tr, params=params)

    async def inquire_price(self, code: str) -> Dict[str, Any]:
        params = {"FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":code}
        # TR_ID를 .env에서 가져오기
        tr = self._tr("PRICE")
        return await self.c.get(PATH_PRICE, tr_id=tr, params=params)

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
        # TR_ID를 .env에서 가져오기
        tr = self._tr("ORDERABLE_CASH")
        return await self.c.get(PATH_ORDERABLE_CASH, tr_id=tr, params=params)

    async def inquire_daily_orders(self, date: str = ""):
        """
        주식일별주문체결조회 - 미체결 주문 포함
        Args:
            date: 조회일자 (YYYYMMDD, 빈 문자열이면 당일)
        """
        from src.utils.logging import get_logger
        log = get_logger("kis.domestic")
        
        # 조회일자가 없으면 당일로 설정
        if not date:
            from datetime import datetime
            date = datetime.now().strftime("%Y%m%d")
        
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
        
        tr = self._tr("DAILY_ORDERS")
        log.info(f"일별 주문체결 조회 - 날짜: {date}, TR_ID: {tr}")
        return await self.c.get(PATH_DAILY_ORDERS, tr_id=tr, params=params)

    async def order_cash(self, code: str, qty: int, price: float | None, side: str):
        from src.utils.logging import get_logger
        log = get_logger("kis.domestic")
        
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
        
        # TR_ID를 .env에서 가져오기
        if side.upper() == "BUY":
            tr_id = self._tr("ORDER_BUY")
        else:
            tr_id = self._tr("ORDER_SELL")
        
        # 디버깅: 주문 파라미터 로깅
        log.info(f"주문 파라미터 - TR_ID: {tr_id}, Body: {body}, Side: {side}")
        
        return await self.c.post(PATH_ORDER_CASH, tr_id=tr_id, body=body, need_hash=True)

    async def cancel_order(self, order_id: str, code: str, qty: int):
        """
        미체결 주문 취소
        Args:
            order_id: 주문번호 (ord_gno_brno)
            code: 종목코드
            qty: 취소할 수량
        """
        from src.utils.logging import get_logger
        log = get_logger("kis.domestic")
        
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
        
        # 취소 주문의 TR_ID (정식 정정취소주문 TR_ID)
        tr_id = self._tr("ORDER_CANCEL")
        
        log.info(f"주문 취소 파라미터 - TR_ID: {tr_id}, Body: {body}")
        
        return await self.c.post(PATH_CANCEL_ORDER, tr_id=tr_id, body=body, need_hash=True)
