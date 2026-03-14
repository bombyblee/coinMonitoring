from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from crypto.strategies import MomentumBurst, RsiReversal, EmaCross

# 전략 레지스트리: name → (class, 설명, tp_mult, sl_mult)
_REGISTRY: dict[str, tuple] = {
    "MomentumBurst": (MomentumBurst, "단기 모멘텀 버스트 — 3봉 상승/하락 + 거래량 급증(×1.8) + EMA 추세", 3.5, 3.0),
    "RsiReversal":   (RsiReversal,   "RSI 반전 — 과매도/과매수 탈출 + zscore 극단(±1.5) + 거래량",         1.5, 1.5),
    "EmaCross":      (EmaCross,      "EMA 골든/데드크로스 — ema5×ema20 돌파 + RSI 범위 + 거래량(×1.3)",    4.0, 2.5),
}


def _status_text(runner) -> str:
    active_names = {s.name for s in runner.strategies}

    active_lines = []
    inactive_lines = []
    for name, (_, desc, tp, sl) in _REGISTRY.items():
        auto_usdt = runner._auto.get(name)
        auto_tag  = f"  🤖 auto {auto_usdt:.0f}U" if auto_usdt is not None else ""
        line = f"  • {name}  TP×{tp}/SL×{sl}{auto_tag}\n    {desc}"
        if name in active_names:
            active_lines.append(line)
        else:
            inactive_lines.append(line)

    parts = ["📊 전략 현황"]
    parts.append(f"\n▶ 실행 중 ({len(active_lines)}개):")
    parts.extend(active_lines if active_lines else ["  (없음)"])
    parts.append(f"\n⏹ 비활성 ({len(inactive_lines)}개):")
    parts.extend(inactive_lines if inactive_lines else ["  (없음)"])
    parts.append(
        "\nstrategy add/del <이름>\n"
        "strategy <이름> auto [USDT]  /  strategy <이름> auto off"
    )
    return "\n".join(parts)


def make_strategy_handler(runner, messenger):
    """
    텍스트 명령 처리:
      'strategy'                     → 현황 조회
      'strategy add <이름>'           → 전략 추가
      'strategy del <이름>'           → 전략 제거
      'strategy <이름> auto [USDT]'   → 자동 진입 활성화
      'strategy <이름> auto off'      → 자동 진입 비활성화
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        chat_id = str(update.effective_chat.id)
        parts   = (update.message.text or "").strip().split()
        sub     = parts[1].lower() if len(parts) > 1 else ""
        name    = parts[2] if len(parts) > 2 else ""

        # strategy add <이름>
        if sub == "add":
            if name not in _REGISTRY:
                await messenger.post_message(
                    chat_id, f"❌ 알 수 없는 전략: {name}\n사용 가능: {', '.join(_REGISTRY)}"
                )
                return
            cls = _REGISTRY[name][0]
            if runner.add_strategy(cls()):
                await messenger.post_message(chat_id, f"✅ {name} 전략 추가됨")
            else:
                await messenger.post_message(chat_id, f"⚠️ {name} 이미 실행 중")

        # strategy del <이름>
        elif sub == "del":
            if runner.remove_strategy(name):
                runner.unset_auto(name)   # 전략 제거 시 auto도 같이 해제
                await messenger.post_message(chat_id, f"✅ {name} 전략 제거됨")
            else:
                await messenger.post_message(chat_id, f"❌ {name} 전략을 찾을 수 없음")

        # strategy <이름> auto [USDT|off]
        elif len(parts) >= 3 and parts[2].lower() == "auto":
            strategy_name = parts[1]   # 대소문자 유지
            arg = parts[3].lower() if len(parts) > 3 else ""

            if arg == "off":
                if runner.unset_auto(strategy_name):
                    await messenger.post_message(chat_id, f"✅ {strategy_name} 자동 진입 해제")
                else:
                    await messenger.post_message(chat_id, f"⚠️ {strategy_name} 자동 진입이 설정돼 있지 않음")
            else:
                try:
                    usdt = float(arg) if arg else runner.executor.auto_usdt
                except (ValueError, AttributeError):
                    usdt = 50.0
                if runner.set_auto(strategy_name, usdt):
                    await messenger.post_message(
                        chat_id, f"🤖 {strategy_name} 자동 진입 활성화 ({usdt:.0f} USDT)\n"
                                 f"시그널 발생 시 즉시 positive 주문"
                    )
                else:
                    await messenger.post_message(
                        chat_id, f"❌ {strategy_name} 전략이 실행 중이 아님\n"
                                 f"먼저 strategy add {strategy_name}"
                    )

        # strategy (현황)
        else:
            await messenger.post_message(chat_id, _status_text(runner))

    return handler


def make_strategy_cmd(runner, messenger):
    """/strategy 슬래시 커맨드 — 현황 조회."""

    async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        await messenger.post_message(str(update.effective_chat.id), _status_text(runner))

    return cmd
