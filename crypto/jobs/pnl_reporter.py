# jobs/pnl_job.py
from __future__ import annotations
import asyncio, time
from crypto.jobs.base import ReporterJobBase

class PnlReporterJob(ReporterJobBase):
    def __init__(self, trader, messenger, state, market_api=None):
        super().__init__(messenger=messenger, state=state)
        self.trader = trader
        self.market_api = market_api
        self._last_income_ms = int(time.time() * 1000) - 48 * 60 * 60 * 1000
        self._cumulative_funding = 0.0
        self._funding_interval_cache: dict[str, int] = {}  # symbol → fundingIntervalHours

    def _get_interval_h(self, symbol: str) -> int:
        if not self._funding_interval_cache:
            try:
                rows = self.trader.client.sign_request("GET", "/fapi/v1/fundingInfo", {})
                self._funding_interval_cache = {r["symbol"]: int(r["fundingIntervalHours"]) for r in rows}
            except Exception:
                pass
        return self._funding_interval_cache.get(symbol, 8)

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
        delta = 0.0
        newest = self._last_income_ms
        for r in rows:
            delta += float(r.get("income", 0.0))
            newest = max(newest, int(r.get("time", newest)))
        if rows:
            self._last_income_ms = newest + 1
        self._cumulative_funding += delta
        return delta

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

    async def _fetch_funding_rates(self, symbols: list[str]) -> dict[str, dict]:
        """보유 심볼별 펀딩 정보 조회. symbol → {rate, interval_h}"""
        async def _one(sym: str):
            try:
                r = await asyncio.to_thread(self.trader.client.mark_price, symbol=sym)
                rate = float(r.get("lastFundingRate", 0.0))
                interval_h = await asyncio.to_thread(self._get_interval_h, sym)
                return sym, {"rate": rate, "interval_h": interval_h}
            except Exception:
                return sym, {"rate": 0.0, "interval_h": 8}
        pairs = await asyncio.gather(*[_one(s) for s in symbols])
        return dict(pairs)

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

        # 3) last prices + funding rates
        last_map, rate_map = await asyncio.gather(
            self._fetch_last_prices(symbols),
            self._fetch_funding_rates(symbols),
        )

        # 4) 실제 지급된 funding fee 누적
        funding_delta = await self._fetch_funding_fee(symbol=None)

        # 5) 시간당 펀딩 비용 합산
        hourly_usdt = 0.0
        hourly_pct = 0.0
        for sym, amt, entry, u, lev, liq in live:
            last = last_map.get(sym)
            ref_price = last if (last and last == last) else entry
            notional = abs(amt) * ref_price
            info = rate_map.get(sym, {"rate": 0.0, "interval_h": 8})
            rate_per_h = info["rate"] / info["interval_h"]
            direction = 1 if amt > 0 else -1          # LONG=지불, SHORT=수취
            hourly_usdt += notional * rate_per_h * direction
            hourly_pct  += rate_per_h * direction * 100

        funding_str = f"funding  누적={self._cumulative_funding:+.4f} USDT"
        if funding_delta != 0.0:
            funding_str += f"  (Δ{funding_delta:+.4f})"
        if symbols:
            funding_str += f"\n         시간당  {hourly_pct:+.4f}%/h  ≈ {hourly_usdt:+.4f} USDT/h"

        lines = [
            "📊 Futures 상태 리포트",
            f"wallet={wallet:.2f}  marginBal={margin_bal:.2f}  uPnL={upnl:.2f}",
            funding_str,
        ]

        if not live:
            lines.append("positions: (none)")
        else:
            lines.append("positions:")
            for i, (sym, amt, entry, u, lev, liq) in enumerate(live, start=1):
                last = last_map.get(sym)
                if last is None or (isinstance(last, float) and last != last):
                    last_str = "?"
                    ref_price = entry
                else:
                    last_str = f"{last}"
                    ref_price = last
                amt_usdt = amt * ref_price
                info = rate_map.get(sym, {"rate": 0.0, "interval_h": 8})
                rate_str = f"{info['rate']*100:+.4f}%/{info['interval_h']}h"
                lines.append(
                    f"{i}. {sym} amt={amt_usdt:.2f}U entry={entry} last={last_str} uPnL={u:.2f} lev={lev} liq={liq} fr={rate_str}"
                )

        await self.messenger.post_message(chat_id, "\n".join(lines))
