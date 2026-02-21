"""
SL/TP 서비스.

모든 주문(가격 기준 / USDT 손익 기준 모두)을 Binance에 실주문으로 전송.

USDT 손익 기준 변환 공식:
  target_price = entry_price + target_usdt / positionAmt
  - LONG  (positionAmt > 0): TP → entry 위, SL → entry 아래
  - SHORT (positionAmt < 0): TP → entry 아래, SL → entry 위
  → positionAmt 부호가 방향을 자동으로 처리
"""

from __future__ import annotations
import asyncio


def _get_live_positions(pos_list: list[dict]) -> list[dict]:
    return [p for p in pos_list if abs(float(p.get("positionAmt", 0.0))) > 1e-12]


def _usdt_to_price(entry: float, target_usdt: float, pos_amt: float) -> float:
    """USDT 손익 목표를 가격으로 환산."""
    return round(entry + target_usdt / pos_amt, 2)


class SlTpMonitor:
    def __init__(self, trader, messenger, poll_interval: float = 5.0):
        self.trader = trader
        self.messenger = messenger
        self.poll_interval = poll_interval  # 하위 호환 유지용

    async def start(self) -> None:
        pass  # 로컬 모니터 불필요 — 모든 주문이 Binance로 전송됨

    async def stop(self) -> None:
        pass

    async def register(self, intent, chat_id: str = "") -> str:  # noqa: ARG002
        """
        SlTpIntent → Binance TAKE_PROFIT_MARKET / STOP_MARKET 주문 전송.

        basis="USDT"  → target_usdt를 가격으로 환산 후 전송
        basis=티커     → 입력 가격을 그대로 전송
        """
        pos_list = await asyncio.to_thread(self.trader.client.get_position_risk)
        live = _get_live_positions(pos_list)

        if intent.pos_index > len(live):
            raise ValueError(
                f"포지션 #{intent.pos_index} 없음 (현재 열린 포지션: {len(live)}개)"
            )

        p = live[intent.pos_index - 1]
        symbol = p["symbol"]
        amt = float(p["positionAmt"])
        pos_side = "LONG" if amt > 0 else "SHORT"
        entry = float(p.get("entryPrice", 0.0))
        upnl = float(p.get("unRealizedProfit", 0.0))
        close_side = "SELL" if amt > 0 else "BUY"

        # ── 가격 결정 ──────────────────────────────────────────────────
        if intent.basis == "USDT":
            stop_price = _usdt_to_price(entry, intent.target, amt)
            basis_desc = f"{intent.target:+.2f} USDT 손익 → 가격 {stop_price}"
        else:
            # 가격 직접 입력: 티커 검증
            expected_ticker = symbol.replace("USDT", "").replace("BUSD", "")
            if intent.basis != expected_ticker:
                raise ValueError(
                    f"기준 티커 불일치: 포지션 심볼={symbol}, 입력기준={intent.basis}\n"
                    f"힌트) {expected_ticker.lower()} 또는 usdt 를 사용하세요"
                )
            stop_price = intent.target
            basis_desc = f"가격 {stop_price}"

        if stop_price <= 0:
            raise ValueError(f"환산된 목표 가격이 0 이하입니다: {stop_price:.2f}")

        # ── Binance 주문 전송 ──────────────────────────────────────────
        if intent.direction == "TP":
            resp = await self.trader.new_take_profit_order(symbol, close_side, stop_price)
        else:  # SL
            resp = await self.trader.new_stop_loss_order(symbol, close_side, stop_price)

        order_id = resp.get("orderId", "?")
        return (
            f"✅ {intent.direction} 주문 전송 (Binance)\n"
            f"포지션: #{intent.pos_index} {symbol} ({pos_side})\n"
            f"entry={entry}  현재 uPnL={upnl:.2f} USDT\n"
            f"기준: {basis_desc}\n"
            f"orderId={order_id}"
        )

    def list_triggers(self, chat_id: str) -> str:
        return "ℹ️ 등록된 TP/SL은 Binance에서 관리됩니다.\n/orders 로 확인하세요."

    async def cancel(self, trigger_id: int, chat_id: str) -> str:
        raise ValueError("Binance 주문 취소는 /orders 확인 후 sltp cancel <orderId> <symbol> 을 사용하세요.")
