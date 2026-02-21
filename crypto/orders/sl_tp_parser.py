import re
from dataclasses import dataclass

@dataclass(frozen=True)
class SlTpIntent:
    pos_index: int    # 1-based 포지션 번호
    direction: str    # "TP" or "SL"
    target: float     # 목표값 (USDT 손익 or 가격)
    basis: str        # "USDT" or 코인 티커 (e.g. "BTC", "ETH")

# 패턴: <번호> <tp|sl> <타겟값> <기준>
# 예) 1 tp 100 usdt  /  2 sl 66000 btc  /  1 sl -50 usdt
_PAT = re.compile(
    r"^\s*(\d+)\s+(tp|sl)\s+(-?[0-9]*\.?[0-9]+)\s+([A-Za-z]+)\s*$",
    re.IGNORECASE,
)

def parse_sl_tp_intent(text: str) -> SlTpIntent:
    m = _PAT.match(text.strip())
    if not m:
        raise ValueError(
            "형식: <번호> <tp|sl> <타겟> <usdt|btc|eth...>\n"
            "예) 1 tp 100 usdt  /  2 sl 66000 btc  /  1 sl -50 usdt"
        )

    pos_index = int(m.group(1))
    direction = m.group(2).upper()
    target = float(m.group(3))
    basis = m.group(4).upper()

    if pos_index <= 0:
        raise ValueError("잔고 번호는 1 이상이어야 함")

    return SlTpIntent(
        pos_index=pos_index,
        direction=direction,
        target=target,
        basis=basis,
    )
