from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from crypto.strategies import MomentumBurst, RsiReversal, EmaCross

# ── 전략 레지스트리 ────────────────────────────────────────────────────────────
# TP/SL 배율은 각 전략 클래스의 tp_mult / sl_mult 클래스 속성으로 관리.
# 텔레그램 커맨드로 런타임 변경 가능: strategy <이름> tp/sl <배율>
_REGISTRY: dict[str, tuple] = {
    #  이름            클래스          설명
    "MomentumBurst": (MomentumBurst, "단기 모멘텀 버스트 — 3봉 상승/하락 + 거래량 급증(×1.8) + EMA 추세 | 5min"),
    "RsiReversal":   (RsiReversal,   "RSI 반전 — 과매도/과매수 탈출 + zscore 극단(±1.5) + 거래량 | 1min"),
    "EmaCross":      (EmaCross,      "EMA 골든/데드크로스 — ema5×ema20 돌파 + RSI 범위 + 거래량(×1.3) | 5min"),
}

_REGISTRY_LOWER: dict[str, str] = {k.lower(): k for k in _REGISTRY}


def _resolve_name(raw: str) -> str | None:
    """대소문자 무관하게 레지스트리 키를 반환. 없으면 None."""
    return _REGISTRY_LOWER.get(raw.lower())


def _get_tp_sl(name: str, runner) -> tuple[float, float]:
    """실행 중인 전략 인스턴스의 tp/sl 반환. 없으면 클래스 기본값."""
    instance = next((s for s in runner.strategies if s.name == name), None)
    if instance:
        return instance.tp_mult, instance.sl_mult
    cls = _REGISTRY[name][0]
    return cls.tp_mult, cls.sl_mult


def _status_text(runner) -> str:
    active_names = {s.name for s in runner.strategies}

    active_lines = []
    inactive_lines = []
    for name, (_, desc) in _REGISTRY.items():
        tp, sl = _get_tp_sl(name, runner)
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
        "\n[커맨드]\n"
        "strategy add/del <이름>\n"
        "strategy <이름> tp/sl <배율>   → TP/SL 배율 변경\n"
        "strategy <이름> auto [USDT]  /  strategy <이름> auto off\n"
        "strategy auto off  → 전체 자동 진입 해제"
    )
    return "\n".join(parts)


def make_strategy_handler(runner, messenger):
    """
    텍스트 명령 처리:
      'strategy'                     → 현황 조회
      'strategy add <이름>'           → 전략 추가
      'strategy del <이름>'           → 전략 제거
      'strategy <이름> tp <배율>'     → TP 배율 변경
      'strategy <이름> sl <배율>'     → SL 배율 변경
      'strategy <이름> auto [USDT]'   → 자동 진입 활성화
      'strategy <이름> auto off'      → 자동 진입 비활성화
      'strategy auto off'             → 전체 자동 진입 해제
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        chat_id  = str(update.effective_chat.id)
        parts    = (update.message.text or "").strip().split()
        sub      = parts[1].lower() if len(parts) > 1 else ""
        raw_name = parts[2] if len(parts) > 2 else ""

        # ── strategy add <이름> ──────────────────────────────────────────────
        if sub == "add":
            name = _resolve_name(raw_name)
            if name is None:
                await messenger.post_message(
                    chat_id, f"❌ 알 수 없는 전략: {raw_name}\n사용 가능: {', '.join(_REGISTRY)}"
                )
                return
            cls = _REGISTRY[name][0]
            if runner.add_strategy(cls()):
                await messenger.post_message(chat_id, f"✅ {name} 전략 추가됨")
            else:
                await messenger.post_message(chat_id, f"⚠️ {name} 이미 실행 중")

        # ── strategy del <이름> ──────────────────────────────────────────────
        elif sub == "del":
            name = _resolve_name(raw_name) or raw_name
            if runner.remove_strategy(name):
                runner.unset_auto(name)
                await messenger.post_message(chat_id, f"✅ {name} 전략 제거됨")
            else:
                await messenger.post_message(chat_id, f"❌ {name} 전략을 찾을 수 없음")

        # ── strategy auto off  → 전체 자동 진입 해제 ────────────────────────
        elif sub == "auto" and (len(parts) < 3 or raw_name.lower() == "off"):
            cleared = list(runner._auto.keys())
            runner._auto.clear()
            if cleared:
                await messenger.post_message(
                    chat_id, f"✅ 전체 자동 진입 해제 ({', '.join(cleared)})"
                )
            else:
                await messenger.post_message(chat_id, "⚠️ 자동 진입이 설정된 전략 없음")

        # ── strategy <이름> tp/sl <배율> ─────────────────────────────────────
        elif len(parts) >= 4 and raw_name.lower() in ("tp", "sl"):
            strategy_name = _resolve_name(parts[1]) or parts[1]
            field = raw_name.lower()   # "tp" or "sl"
            try:
                value = float(parts[3])
                if value <= 0:
                    raise ValueError
            except ValueError:
                await messenger.post_message(chat_id, "❌ 배율은 양수 숫자여야 합니다")
                return

            instance = next((s for s in runner.strategies if s.name == strategy_name), None)
            if instance is None:
                # 비활성 전략이면 클래스 기본값을 변경 (다음 add 시 반영)
                cls = _REGISTRY.get(strategy_name, (None,))[0]
                if cls is None:
                    await messenger.post_message(chat_id, f"❌ 알 수 없는 전략: {strategy_name}")
                    return
                setattr(cls, f"{field}_mult", value)
                await messenger.post_message(
                    chat_id,
                    f"📝 {strategy_name} {field.upper()} 기본값 → ×{value}\n"
                    f"(현재 비활성 — 다음 add 시 적용)"
                )
            else:
                setattr(instance, f"{field}_mult", value)
                tp, sl = instance.tp_mult, instance.sl_mult
                await messenger.post_message(
                    chat_id,
                    f"✅ {strategy_name} {field.upper()} 배율 → ×{value}\n"
                    f"현재: TP×{tp} / SL×{sl}"
                )

        # ── strategy <이름> auto [USDT|off] ──────────────────────────────────
        elif len(parts) >= 3 and raw_name.lower() == "auto":
            strategy_name = _resolve_name(parts[1]) or parts[1]
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

        # ── strategy (현황) ──────────────────────────────────────────────────
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
