from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


def _status_text(liq_trap) -> str:
    al = liq_trap.autolist.symbols() if liq_trap.autolist else ["전체"]
    auto_tag = f"  🤖 auto {liq_trap.auto_usdt:.0f}U" if liq_trap.auto_usdt is not None else "  (수동 확인)"
    return (
        f"⚡ LiquidationTrap 현황\n"
        f"  TP×{liq_trap.tp_mult} / SL×{liq_trap.sl_mult}{auto_tag}\n"
        f"  depth비율≥{liq_trap.book_ratio:.0%}  minDepth=${liq_trap.min_depth_usdt:,.0f}\n"
        f"  윈도우 {liq_trap.window_sec:.0f}s  쿨다운 {liq_trap.cooldown_sec:.0f}s\n"
        f"  탐지: 워치리스트 전체  |  자동진입 허용: {', '.join(al)}\n"
        "\n[커맨드]\n"
        "liqtrap auto <USDT>  → 자동 진입 활성화\n"
        "liqtrap auto off     → 자동 진입 해제\n"
        "liqtrap tp <배율>    → TP 배율 변경\n"
        "liqtrap sl <배율>    → SL 배율 변경"
    )


def make_liqtrap_handler(liq_trap, messenger):
    """
    텍스트 명령 처리:
      'liqtrap'                → 현황 조회
      'liqtrap auto <USDT>'    → 자동 진입 활성화
      'liqtrap auto off'       → 자동 진입 해제
      'liqtrap tp <배율>'      → TP 배율 변경
      'liqtrap sl <배율>'      → SL 배율 변경
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        chat_id = str(update.effective_chat.id)
        parts   = (update.message.text or "").strip().split()
        sub     = parts[1].lower() if len(parts) > 1 else ""
        arg     = parts[2].lower() if len(parts) > 2 else ""

        # liqtrap auto <USDT|off>
        if sub == "auto":
            if arg == "off":
                liq_trap.auto_usdt = None
                await messenger.post_message(chat_id, "✅ LiquidationTrap 자동 진입 해제")
            else:
                try:
                    usdt = float(arg) if arg else getattr(liq_trap.executor, "auto_usdt", 50.0)
                    if usdt <= 0:
                        raise ValueError
                except ValueError:
                    await messenger.post_message(chat_id, "❌ 양수 USDT 금액을 입력하세요 (예: liqtrap auto 50)")
                    return
                liq_trap.auto_usdt = usdt
                await messenger.post_message(
                    chat_id,
                    f"🤖 LiquidationTrap 자동 진입 활성화 ({usdt:.0f} USDT)\n"
                    f"신호 발생 시 즉시 주문"
                )

        # liqtrap tp/sl <배율>
        elif sub in ("tp", "sl"):
            try:
                value = float(arg)
                if value <= 0:
                    raise ValueError
            except ValueError:
                await messenger.post_message(chat_id, "❌ 배율은 양수 숫자여야 합니다")
                return
            setattr(liq_trap, f"{sub}_mult", value)
            await messenger.post_message(
                chat_id,
                f"✅ LiquidationTrap {sub.upper()} 배율 → ×{value}\n"
                f"현재: TP×{liq_trap.tp_mult} / SL×{liq_trap.sl_mult}"
            )

        # liqtrap (현황)
        else:
            await messenger.post_message(chat_id, _status_text(liq_trap))

    return handler
