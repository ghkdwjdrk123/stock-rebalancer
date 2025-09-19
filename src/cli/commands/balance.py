from __future__ import annotations
import typer
import asyncio

from src.config import Settings
from src.utils.logging import get_logger
from src.adapters.kis.client import KISClient
from src.adapters.kis.domestic import KISDomestic
from src.services.brokers.kis import KISBroker
from src.services.portfolio import get_positions_and_cash


log = get_logger("cli.balance")


async def _run(raw: bool = False, env: str = "dev"):
    st = Settings()
    conf = st.resolve_kis(env)
    client = KISClient(conf["base"], conf["app_key"], conf["app_secret"], env=env)
    dom = KISDomestic(client, conf["account_8"], conf["account_pd"], env=env)
    broker = KISBroker(client, dom)

    bal = await broker.fetch_balance()
    
    # --raw 옵션이 있을 때만 원문 JSON 출력
    if raw:
        import json as _json
        typer.echo(_json.dumps(bal, ensure_ascii=False, indent=2))
        return

    # 상세 출력 형식 (이전 구현과 동일)
    def _fmt_money(v):
        try:
            iv = int(float(v))
            return f"{iv:,} 원"
        except Exception:
            return str(v)

    # 현금/예수금 요약
    summary_raw = bal.get("output2")
    if isinstance(summary_raw, list) and summary_raw:
        summary = summary_raw[0] if isinstance(summary_raw[0], dict) else {}
    elif isinstance(summary_raw, dict):
        summary = summary_raw
    else:
        summary = bal.get("output") or {}
        if not isinstance(summary, dict):
            summary = {}

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

    ord_cash = _pick(summary, [
        "ord_psbl_cash", "ORD_PSBL_CASH", "주문가능현금",
        "ord_psbl_cash_amt", "ord_psbl_amt", "주문가능현금액"
    ])
    dep_total = _pick(summary, [
        "dnca_tot_amt", "DNCA_TOT_AMT", "예수금총액",
        "dpsast_totamt", "DPSAST_TOTAMT", "예탁자산총액"
    ])
    nr_recv = _pick(summary, [
        "nrcvb_lqdty_amt", "NRCVB_LQDTY_AMT", "미수금"
    ])
    nxdy_excc = _pick(summary, [
        "nxdy_excc_amt", "NXDY_EXCC_AMT", "D+1예수금"
    ])
    prvs_excc = _pick(summary, [
        "prvs_rcdl_excc_amt", "PRVS_RCDL_EXCC_AMT", "D+2예수금"
    ])

    # 구분선: 현금 요약
    if any([ord_cash, dep_total, nr_recv, nxdy_excc, prvs_excc]):
        typer.echo("================ 현금/예수금 요약 ================")
    if ord_cash:
        typer.echo(f"주문가능현금: {_fmt_money(ord_cash)}")
    if dep_total:
        typer.echo(f"총 예수금: {_fmt_money(dep_total)}")
    if nr_recv:
        typer.echo(f"미수금: {_fmt_money(nr_recv)}")
    if nxdy_excc:
        typer.echo(f"D+1 예수금: {_fmt_money(nxdy_excc)}")
    if prvs_excc:
        typer.echo(f"D+2 예수금: {_fmt_money(prvs_excc)}")

    # 총 보유 금액 계산
    total_holdings = _pick(summary, [
        "scts_evlu_amt", "SCTS_EVLU_AMT", "주식평가금액"
    ])
    if total_holdings is None:
        items = bal.get("output1")
        if not isinstance(items, list):
            tmp = bal.get("output")
            items = tmp if isinstance(tmp, list) else []
        if isinstance(items, list) and items:
            try:
                total_holdings = sum(int(float(it.get("evlu_amt") or it.get("EVLU_AMT") or 0)) for it in items)
            except Exception:
                total_holdings = None

    # 보유 종목 목록
    items = bal.get("output1")
    if not isinstance(items, list):
        tmp = bal.get("output")
        items = tmp if isinstance(tmp, list) else []
    
    if isinstance(items, list):
        typer.echo("---------------- 보유 종목 ----------------")
        typer.echo(f"보유 종목 수: {len(items)}")
        if items:
            for it in items:
                code = it.get("pdno") or it.get("종목번호") or it.get("PDNO")
                name = it.get("prdt_name") or it.get("종목명") or it.get("PRDT_NAME")
                qty = it.get("hldg_qty") or it.get("보유수량") or it.get("HLDG_QTY")
                evl_prc = it.get("evlu_amt") or it.get("평가금액") or it.get("EVLU_AMT")
                disp = f"{name}({code})" if (name and code) else (code or name or "-")
                typer.echo(f" - {disp} | 수량: {qty} | 평가금액: {_fmt_money(evl_prc)}")
        else:
            typer.echo("보유 종목이 없습니다.")
        # 보유 종목 섹션 구분선 및 총 보유 금액 출력
        typer.echo("------------------------------------------")
        if total_holdings is not None:
            typer.echo(f"총 보유 금액: {_fmt_money(total_holdings)}")
    else:
        # 스키마 상이 시 원본 전체 출력 (디버깅용)
        typer.echo("응답 스키마가 예상과 다릅니다. --raw 옵션으로 원문을 확인하세요.")


def run(raw: bool = False, env: str = "dev"):
    asyncio.run(_run(raw, env))


