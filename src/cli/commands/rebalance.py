from __future__ import annotations
import asyncio
import typer

from typing import Dict
from src.config import Settings
from src.utils.logging import get_logger
from src.services.report import format_plan

from src.adapters.kis.client import KISClient
from src.adapters.kis.domestic import KISDomestic
from src.services.brokers.kis import KISBroker
from src.services.portfolio import get_positions_and_cash, get_positions_with_daily_orders, get_prices
from src.services.rebalance_executor import build_plan, execute_plan
from src.services.guards import is_trading_day, is_market_open_now


log = get_logger("cli.rebalance")


def load_targets(path: str) -> Dict[str, float]:
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 새로운 구조 (targets/{broker}/{env}/{account}.json) 지원
    if "account_info" in data and "rebalance_config" in data:
        # 새로운 구조: 계좌별 설정 파일
        rebalance_config = data["rebalance_config"]
        account_info = data["account_info"]
        
        log.info(f"📋 계좌 설정 로드: {account_info.get('description', 'Unknown')}")
        log.info(f"📋 브로커: {account_info.get('broker', 'Unknown')}, 환경: {account_info.get('env', 'Unknown')}")
        log.info(f"📋 계좌: {account_info.get('account_8', 'Unknown')}-{account_info.get('account_pd', 'Unknown')}")
        
        return {
            "band_pct": float(rebalance_config.get("band_pct", 1.0)),
            "order_style": rebalance_config.get("order_style", "market"),
            "tickers": data["tickers"],
            "account_info": account_info
        }
    else:
        # 기존 구조: targets.example.json
        return {
            "band_pct": float(data.get("band_pct", 1.0)),
            "order_style": data.get("order_style", "market"),
            "tickers": data["tickers"],
        }

def find_targets_config(env: str = "dev", broker: str = "kis") -> str:
    """환경과 브로커에 따라 적절한 설정 파일 경로를 찾습니다."""
    from src.config import Settings
    st = Settings()
    
    # 환경별 계좌 정보 가져오기
    if env == "dev":
        account_8 = st.kis_account_8_dev
        account_pd = st.kis_account_pd_dev
    else:  # prod
        account_8 = st.kis_account_8_prod
        account_pd = st.kis_account_pd_prod
    
    # 설정 파일 경로 구성
    config_path = f"targets/{broker}/{env}/{account_8}.json"
    
    import os
    if os.path.exists(config_path):
        return config_path
    else:
        # 기본 설정 파일로 fallback
        return "targets.example.json"


async def _run(config: str, dry_run: bool, env: str = "dev", ignore_guards: bool = False, raw: bool = False, order_delay: float = 1.0, safety_mode: str = "conservative", strict_cancellation: bool = True, persistent_retry: bool = True, retry_threshold: float = 0.8):
    st = Settings()
    targets = load_targets(config)
    
    # 디버깅: raw 값 확인
    if raw:
        log.info(f"[DEBUG] raw=True, raw 모드로 실행합니다.")

    # DRY_RUN: CLI 플래그만 우선 적용 (환경변수 DRY_RUN은 기본값 용도로만 사용)
    if dry_run:
        log.info("[DRY_RUN] KIS API 호출 없이 시뮬레이션합니다.")
        
        # === 1~2단계: 샘플 보유 종목 + 주문가능현금 데이터 ===
        log.info("1~2단계: 샘플 보유 종목 및 주문가능현금 생성...")
        tickers = list(targets["tickers"].keys())
        positions = {c: st.default_dry_run_qty for c in tickers}
        cash = st.default_dry_run_cash
        d2_cash = None  # DRY_RUN에서는 D+2 예수금 없음
        log.info(f"보유 종목: {len(positions)}개 - {positions}")
        log.info(f"주문가능현금: {cash:,.0f}원 (dnca_tot_amt 기준)")
        
        # === 3단계: 샘플 가격 데이터 ===
        log.info("3단계: 샘플 가격 데이터 생성...")
        prices = {c: st.default_dry_run_price for c in tickers}
        log.info(f"가격 조회 완료: {len(prices)}개 종목")
        
        # === 4단계: 리밸런싱 계획 수립 ===
        log.info("4단계: 리밸런싱 계획 수립 중...")
        log.info(f"목표 비중: {targets['tickers']}")
        log.info(f"허용 밴드: {targets['band_pct']}%")
        
        plan = await build_plan(
            positions=positions,
            targets=targets["tickers"],
            cash=cash,
            prices=prices,
            band_pct=targets["band_pct"],
            max_order_value_per_ticker=st.max_order_value_per_ticker,
            d2_cash=d2_cash,
            broker=None,  # DRY_RUN에서는 broker 없음
        )
        
        if raw:
            import json
            typer.echo("=== 잔고/포지션 원본 ===")
            typer.echo(json.dumps({"positions": positions, "cash": cash}, ensure_ascii=False, indent=2))
            typer.echo("=== 가격 원본 ===")
            typer.echo(json.dumps(prices, ensure_ascii=False, indent=2))
            typer.echo("=== 계획 원본 ===")
            typer.echo(json.dumps([p.dict() for p in plan], ensure_ascii=False, indent=2))
        else:
            log.info(format_plan(plan))
        
        # === 4단계: 시뮬레이션 완료 ===
        log.info("4단계: DRY_RUN 모드 - 주문을 실행하지 않습니다.")
        return

    # 실거래 경로
    conf = st.resolve_kis(env)
    # 환경 설정 검증
    missing = [k for k in ("base","app_key","app_secret","account_8","account_pd") if not str(conf.get(k) or "").strip()]
    if missing:
        log.error(f"[설정 오류] 다음 설정이 비어 있습니다: {', '.join(missing)}. .env의 {env} 환경 값을 채워주세요.")
        return
    client = KISClient(conf["base"], conf["app_key"], conf["app_secret"])
    dom = KISDomestic(client, conf["account_8"], conf["account_pd"], env=env)
    broker = KISBroker(client, dom)

    # 가드
    if not ignore_guards:
        if not await is_trading_day(client, env=env):
            log.warning("오늘은 휴장일입니다. 리밸런싱을 건너뜁니다.")
            return
        if not await is_market_open_now(client, env=env):
            log.warning("현재는 정규장이 아닙니다. 정책에 따라 주문을 건너뜁니다.")
            return
    else:
        log.warning("[IGNORE_GUARDS] 영업일/장중 가드를 무시하고 진행합니다.")

    # === 1단계: 계좌조회 + 당일 주문체결 조회 (API 호출 최적화) ===
    log.info("1단계: 계좌조회 + 당일 주문체결 조회 - 종합 포지션 계산 중...")
    try:
        # 현재 보유 + 미체결 주문을 고려한 포지션 계산 (체결 주문은 이미 반영됨)
        current_positions, expected_positions, adjusted_cash, d2_cash, net_asset = await get_positions_with_daily_orders(broker)
        
        # 1단계 검증: 필수 데이터 확인
        if not current_positions and not expected_positions:
            log.error("❌ 1단계 실패: 보유 종목 정보를 가져올 수 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
        
        if adjusted_cash is None:
            log.error("❌ 1단계 실패: 주문가능현금 정보를 가져올 수 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        log.info(f"현재 보유 종목: {len(current_positions)}개 - {current_positions}")
        log.info(f"미체결 주문 반영 후 예상 포지션: {expected_positions}")
        log.info(f"주문가능현금: {adjusted_cash:,.0f}원 (이미 당일 체결 주문 반영됨)")
        
        # D+2 예수금 상태 확인
        if d2_cash is not None:
            if d2_cash < 0:
                log.warning(f"⚠️  D+2 예수금이 음수: {d2_cash:,.0f}원 (미수 발생)")
                log.info("🔧 미수 해결을 위한 전체 매도 후 목표 비중 재구성 계획을 수립합니다.")
            else:
                log.info(f"D+2 예수금: {d2_cash:,.0f}원 (정상)")
        
        # 리밸런싱에는 종합 포지션 사용
        positions = expected_positions
        cash = adjusted_cash
        log.info("✅ 1단계 성공: 계좌조회 및 포지션 계산 완료")
        
    except Exception as e:
        log.error(f"❌ 1단계 실패: 계좌조회/주문체결 조회 오류 - {e}")
        log.error("🚫 리밸런싱을 중단합니다.")
        return
    
    # === 2단계: 가격 조회 ===
    log.info("2단계: 대상 종목 가격 조회 중...")
    try:
        target_tickers = list(targets["tickers"].keys())
        if not target_tickers:
            log.error("❌ 2단계 실패: 리밸런싱 대상 종목이 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        prices = await get_prices(broker, target_tickers)
        
        # 2단계 검증: 가격 데이터 확인
        if not prices:
            log.error("❌ 2단계 실패: 가격 정보를 가져올 수 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        # 필수 종목 가격 확인
        missing_prices = [ticker for ticker in target_tickers if ticker not in prices or prices[ticker] <= 0]
        if missing_prices:
            log.error(f"❌ 2단계 실패: 다음 종목의 가격 정보가 없거나 유효하지 않습니다: {missing_prices}")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        log.info(f"가격 조회 완료: {len(prices)}개 종목")
        log.info("✅ 2단계 성공: 가격 조회 완료")
        
    except Exception as e:
        log.error(f"❌ 2단계 실패: 가격 조회 오류 - {e}")
        log.error("🚫 리밸런싱을 중단합니다.")
        return

    # raw 모드: 원본 데이터 출력
    if raw:
        import json
        typer.echo("=== 잔고/포지션 원본 ===")
        typer.echo(json.dumps({"positions": positions, "cash": cash}, ensure_ascii=False, indent=2))
        typer.echo("=== 가격 원본 ===")
        typer.echo(json.dumps(prices, ensure_ascii=False, indent=2))

    # === 3단계: 리밸런싱 계획 수립 ===
    log.info("3단계: 리밸런싱 계획 수립 중...")
    log.info(f"목표 비중: {targets['tickers']}")
    log.info(f"허용 밴드: {targets['band_pct']}%")
    log.info(f"종합 포지션 기준 리밸런싱 (현재보유 + 미체결)")
    log.info(f"현금 부족 방지: 주문 후 현금 0원 이상 유지")
    
    # D+2 예수금 값 디버깅
    if d2_cash is not None:
        log.info(f"🔍 D+2 예수금 값: {d2_cash:,.0f}원 (리밸런싱 계획에 전달)")
    
    try:
        # 3단계 검증: 계획 수립 전 필수 데이터 확인
        if not positions:
            log.error("❌ 3단계 실패: 포지션 정보가 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        if not targets["tickers"]:
            log.error("❌ 3단계 실패: 목표 비중 정보가 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        plan = await build_plan(
            positions=positions,
            targets=targets["tickers"],
            cash=cash,
            prices=prices,
            band_pct=targets["band_pct"],
            max_order_value_per_ticker=st.max_order_value_per_ticker,
            d2_cash=d2_cash,
            broker=broker,
        )
        
        # 3단계 검증: 계획 수립 결과 확인
        if plan is None:
            log.error("❌ 3단계 실패: 리밸런싱 계획을 수립할 수 없습니다.")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
            
        log.info("✅ 3단계 성공: 리밸런싱 계획 수립 완료")
        
    except Exception as e:
        log.error(f"❌ 3단계 실패: 리밸런싱 계획 수립 오류 - {e}")
        log.error("🚫 리밸런싱을 중단합니다.")
        return
    
    # 최종 현금 계산 및 로깅
    from src.core.cash_guard import calculate_final_cash
    from src.core.order_optimizer import calculate_commission_savings, estimate_commission_cost
    final_cash = calculate_final_cash(plan, cash, prices)
    
    # 현금 상태 로깅
    if cash < 0:
        log.info(f"⚠️  초기 현금이 음수: {cash:,.0f}원 (매도 주문으로 현금 확보 후 매수 진행)")
    log.info(f"주문 실행 후 예상 현금: {final_cash:,.0f}원")
    
    # 수수료 최적화 정보 로깅
    if plan:
        estimated_commission = estimate_commission_cost(plan, prices)
        log.info(f"예상 수수료: {estimated_commission:,.0f}원 (0.15% 기준)")
        log.info(f"수수료 최적화: 동일 종목 매도/매수 주문 통합으로 수수료 절약")
    
    if raw:
        typer.echo("=== 계획 원본 ===")
        typer.echo(json.dumps([p.dict() for p in plan], ensure_ascii=False, indent=2))
    else:
        log.info(format_plan(plan))

    # === 4단계: 실제 매매/매도 API 실행 ===
    if plan:
        log.info("4단계: 주문 실행 중...")
        log.info(f"실행할 주문: {len(plan)}건")
        log.info("(미체결 주문과 중복 검사 후 실행)")
        
        try:
            # 4단계 검증: 계획 유효성 확인
            if not isinstance(plan, list):
                log.error("❌ 4단계 실패: 주문 계획이 유효하지 않습니다.")
                log.error("🚫 리밸런싱을 중단합니다.")
                return
                
            if len(plan) == 0:
                log.info("4단계: 실행할 주문이 없습니다.")
                return
                
            # 주문 계획 상세 검증
            for i, order in enumerate(plan):
                if not hasattr(order, 'code') or not hasattr(order, 'side') or not hasattr(order, 'qty'):
                    log.error(f"❌ 4단계 실패: {i+1}번째 주문이 유효하지 않습니다.")
                    log.error("🚫 리밸런싱을 중단합니다.")
                    return
                    
                if order.qty <= 0:
                    log.error(f"❌ 4단계 실패: {i+1}번째 주문의 수량이 유효하지 않습니다: {order.qty}")
                    log.error("🚫 리밸런싱을 중단합니다.")
                    return
            
            results = await execute_plan(broker, plan, dry_run=False, order_delay_sec=order_delay)
            
            # 4단계 검증: 실행 결과 확인
            if results is None:
                log.error("❌ 4단계 실패: 주문 실행 결과를 받을 수 없습니다.")
                log.error("🚫 리밸런싱을 중단합니다.")
                return
                
            log.info(f"주문 실행 완료: {len(results)}건")
            log.info("✅ 4단계 성공: 주문 실행 완료")
            
        except Exception as e:
            log.error(f"❌ 4단계 실패: 주문 실행 오류 - {e}")
            log.error("🚫 리밸런싱을 중단합니다.")
            return
    else:
        log.info("4단계: 리밸런싱이 필요하지 않습니다.")
        results = []
    
    if raw:
        typer.echo("=== 주문 결과 원본 ===")
        typer.echo(json.dumps(results, ensure_ascii=False, indent=2))


def run(config: str, dry_run: bool, env: str = "dev", ignore_guards: bool = False, raw: bool = False, order_delay: float = 1.0, safety_mode: str = "conservative", strict_cancellation: bool = True, persistent_retry: bool = True, retry_threshold: float = 0.8):
    asyncio.run(_run(config, dry_run, env, ignore_guards, raw, order_delay, safety_mode, strict_cancellation, persistent_retry, retry_threshold))


