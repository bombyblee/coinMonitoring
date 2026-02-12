from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class FuturesSnapshot:
    symbol: str
    last_price: float
    mark_price: float | None
    index_price: float | None
    funding_rate: float | None
    next_funding_time: datetime | None

def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
