from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

@dataclass(frozen=True)
class SymbolRules:
    step_size: Decimal
    min_qty: Decimal | None

def _to_decimal(x) -> Decimal:
    return Decimal(str(x))

def load_symbol_rules(client, symbol: str) -> SymbolRules:
    info = client.exchange_info()
    sym = next(s for s in info["symbols"] if s["symbol"] == symbol)

    lot = next(f for f in sym["filters"] if f["filterType"] == "LOT_SIZE")
    step = _to_decimal(lot["stepSize"])
    minq = _to_decimal(lot["minQty"]) if "minQty" in lot else None
    return SymbolRules(step_size=step, min_qty=minq)

def quantize_qty(qty: float, rules: SymbolRules) -> float:
    q = _to_decimal(qty)
    step = rules.step_size
    if step == 0:
        return float(q)
    # qty를 stepSize 배수로 내림
    q2 = (q / step).to_integral_value(rounding=ROUND_DOWN) * step
    return float(q2)
