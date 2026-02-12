from datetime import timezone
from crypto.binance.models import FuturesSnapshot

def format_snapshot(snapshot: FuturesSnapshot) -> str:
    nft = snapshot.next_funding_time
    nft_kst = None
    if nft:
        nft_kst = nft.astimezone(timezone.utc).astimezone()  # 시스템 로컬(KST면 KST)

    lines = [
        f"🟧 Binance Futures Report",
        f"• Symbol: {snapshot.symbol} (Perpetual)",
        f"• Last: {snapshot.last_price:,.2f}",
    ]
    if snapshot.mark_price is not None:
        lines.append(f"• Mark: {snapshot.mark_price:,.2f}")
    if snapshot.index_price is not None:
        lines.append(f"• Index: {snapshot.index_price:,.2f}")
    if snapshot.funding_rate is not None:
        lines.append(f"• Funding: {snapshot.funding_rate*100:.4f}%")
    if nft_kst is not None:
        lines.append(f"• Next funding: {nft_kst.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    return "\n".join(lines)
