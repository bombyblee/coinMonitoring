# jobs/pnl_job.py
from __future__ import annotations
import asyncio, time
from crypto.jobs.base import ReporterJobBase

class PnlReporterJob(ReporterJobBase):
    def __init__(self, trader, messenger, state, market_api=None):
        super().__init__(messenger=messenger, state=state)
        self.trader = trader
        self.market_api = market_api  # ✅ 추가: last price 조회용
        self._last_income_ms = int(time.time() * 1000) - 6 * 60 * 60 * 1000

    def interval_sec(self) -> int:
        return int(getattr(self.state, "pnl_freq_sec", 600))

    async def _fetch_funding_fee(self, symbol: str | None = None) -> float:
        def _call():
            params = dict(
                incomeType="FUNDING_FEE",
                startTime=self._last_income_ms,
                limit=1000,
            )
            if symbol:
                params["symbol"] = symbol
            return self.trader.client.get_income_history(**params)
        rows = await asyncio.to_thread(_call)
        total = 0.0
        newest = self._last_income_ms
        for r in rows:
            total += float(r.get("income", 0.0))
            newest = max(newest, int(r.get("time", newest)))
        self._last_income_ms = newest + 1
        return total

    async def _fetch_last_prices(self, symbols: list[str]) -> dict[str, float]:
        """
        symbols의 last price를 dict로 반환.
        market_api가 아래 중 하나를 제공한다고 가정하고 최대한 활용:
        - fetch_last_prices(symbols) -> dict[symbol]=price
        - fetch_last_price(symbol) -> float
        없으면 빈 dict 반환
        """
        if not self.market_api or not symbols:
            return {}

        # 1) bulk 메서드가 있으면 그게 베스트
        bulk = getattr(self.market_api, "fetch_last_prices", None)
        if callable(bulk):
            return await asyncio.to_thread(bulk, symbols)

        # 2) 없으면 심볼별로 호출
        one = getattr(self.market_api, "fetch_last_price", None)
        if not callable(one):
            return {}

        async def _one(sym: str):
            try:
                px = await asyncio.to_thread(one, sym)
                return sym, float(px)
            except Exception:
                return sym, float("nan")

        pairs = await asyncio.gather(*[_one(s) for s in symbols])
        return {s: p for s, p in pairs}

    async def _tick(self, chat_id: str) -> None:
        # 1) account summary
        acc = await asyncio.to_thread(self.trader.client.account)
        wallet = float(acc.get("totalWalletBalance", 0.0))
        upnl = float(acc.get("totalUnrealizedProfit", 0.0))
        margin_bal = float(acc.get("totalMarginBalance", 0.0))

        # 2) positions (non-zero only)
        pos = await asyncio.to_thread(self.trader.client.get_position_risk)
        live = []
        symbols = []
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
            symbols.append(sym)

        # ✅ 2.5) last prices (positions만)
        last_map = await self._fetch_last_prices(symbols)

        # 3) funding
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
            for i, (sym, amt, entry, u, lev, liq) in enumerate(live, start=1):
                last = last_map.get(sym)
                # last가 없거나 nan이면 '?' 처리
                if last is None or (isinstance(last, float) and last != last):  # nan 체크
                    last_str = "?"
                    ref_price = entry
                else:
                    last_str = f"{last}"
                    ref_price = last
                # positionAmt(코인 단위)를 USDT 기준으로 변환
                amt_usdt = amt * ref_price
                lines.append(
                    f"{i}. {sym} amt={amt_usdt:.2f}U entry={entry} last={last_str} uPnL={u:.2f} lev={lev} liq={liq}"
                )

        await self.messenger.post_message(chat_id, "\n".join(lines))
