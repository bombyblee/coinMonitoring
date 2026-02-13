import asyncio, time
from datetime import datetime, timezone

class PnlReporterJob:
    def __init__(self, trader, messenger, state):
        self.trader = trader        # BinanceFuturesTrader (UMFutures 래퍼)
        self.messenger = messenger
        self.state = state
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

        # 펀딩비 조회 window (최근부터 누적)
        self._last_income_ms = int(time.time() * 1000) - 6 * 60 * 60 * 1000  # 최근 6시간

    async def start(self, chat_id: str):
        self._stop.clear()
        self._task = asyncio.create_task(self._run(chat_id))

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    async def _fetch_funding_fee(self, symbol: str | None = None) -> float:
        # binance-futures-connector wiki 기준: get_income_history(incomeType="FUNDING_FEE") :contentReference[oaicite:3]{index=3}
        def _call():
            return self.trader.client.get_income_history(
                incomeType="FUNDING_FEE",
                symbol=symbol,
                startTime=self._last_income_ms,
                limit=1000,
            )
        rows = await asyncio.to_thread(_call)
        total = 0.0
        newest = self._last_income_ms
        for r in rows:
            total += float(r.get("income", 0.0))
            newest = max(newest, int(r.get("time", newest)))
        self._last_income_ms = newest + 1
        return total

    async def _run(self, chat_id: str):
        while not self._stop.is_set():
            sec = self.state.pnl_freq_sec

            try:
                # 1) account summary
                acc = await asyncio.to_thread(self.trader.client.account)
                wallet = float(acc.get("totalWalletBalance", 0.0))
                upnl = float(acc.get("totalUnrealizedProfit", 0.0))
                margin_bal = float(acc.get("totalMarginBalance", 0.0))

                # 2) positions (non-zero only)
                pos = await asyncio.to_thread(self.trader.client.get_position_risk)
                live = []
                for p in pos:
                    amt = float(p.get("positionAmt", 0.0))
                    if abs(amt) < 1e-12:
                        continue
                    sym = p["symbol"]
                    entry = float(p.get("entryPrice", 0.0))
                    u = float(p.get("unRealizedProfit", 0.0))
                    lev = p.get("leverage")
                    liq = p.get("liquidationPrice")
                    live.append((sym, amt, entry, u, lev, liq))

                # 3) funding (최근 window 누적)
                funding = await self._fetch_funding_fee(symbol=None)

                lines = [
                    "📊 Futures 상태 리포트",
                    f"wallet={wallet:.2f}  marginBal={margin_bal:.2f}  uPnL={upnl:.2f}",
                    f"funding(Δ)={funding:.4f} USDT",
                ]
                if not live:
                    lines.append("positions: (none)")
                else:
                    lines.append("positions:")
                    for sym, amt, entry, u, lev, liq in live:
                        lines.append(f"- {sym} amt={amt} entry={entry} uPnL={u:.2f} lev={lev} liq={liq}")

                await self.messenger.post_message(chat_id, "\n".join(lines))

            except Exception as e:
                await self.messenger.post_message(chat_id, f"❌ PnL 리포트 실패: {e}")

            await asyncio.sleep(sec)
