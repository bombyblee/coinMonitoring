from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

_HELP = (
    "📌 오토리스트 명령어\n"
    "  autolist               — 현재 목록 조회\n"
    "  autolist add <심볼>    — 전략 실행 심볼 추가 (워치리스트 없으면 자동 추가)\n"
    "  autolist del <심볼>    — 전략 실행 심볼 제거\n\n"
    "※ 오토리스트에 있는 심볼만 전략 시그널 대상이 됩니다.\n"
    "  OHLCV 수집은 워치리스트 기준으로 계속 유지됩니다."
)

_MAX_WATCHLIST = 10


def make_autolist_handler(autolist, watchlist, messenger, ohlcv_job=None):
    """
    autolist           — 현재 목록 조회
    autolist add <심볼> — 추가 (워치리스트에 없으면 자동으로 워치리스트에도 추가)
    autolist del <심볼> — 제거
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        chat_id = str(update.effective_chat.id)
        parts = (update.message.text or "").strip().split()

        # ── 목록 조회 ────────────────────────────────────────────────────────
        if len(parts) == 1:
            syms = autolist.symbols()
            if not syms:
                await messenger.post_message(chat_id, "📌 오토리스트가 비어 있습니다.\n(전략이 어떤 심볼도 실행하지 않음)")
            else:
                lines = [f"{i}. {s}" for i, s in enumerate(syms, 1)]
                await messenger.post_message(
                    chat_id,
                    f"📌 오토리스트 ({len(syms)}개)\n" + "\n".join(lines)
                )
            return

        if len(parts) < 3:
            await messenger.post_message(chat_id, _HELP)
            return

        action = parts[1].lower()
        symbol = parts[2].upper()

        # ── 추가 ─────────────────────────────────────────────────────────────
        if action == "add":
            wl_added_msg = ""
            if symbol not in watchlist:
                if len(watchlist) >= _MAX_WATCHLIST:
                    await messenger.post_message(
                        chat_id,
                        f"❌ 워치리스트가 가득 찼습니다 (최대 {_MAX_WATCHLIST}개).\n"
                        f"먼저 `watchlist del <심볼>`로 하나를 제거하세요."
                    )
                    return
                watchlist.add(symbol)
                if ohlcv_job is not None:
                    await ohlcv_job._init_symbol(symbol)
                    candles = ohlcv_job.store.max_len
                    wl_added_msg = f"  (워치리스트에도 추가, {candles}봉 로드)"
                else:
                    wl_added_msg = "  (워치리스트에도 추가)"

            if autolist.add(symbol):
                await messenger.post_message(
                    chat_id,
                    f"✅ {symbol} 오토리스트 추가{wl_added_msg}\n현재 {len(autolist.symbols())}개"
                )
            else:
                await messenger.post_message(chat_id, f"ℹ️ {symbol} 은 이미 오토리스트에 있습니다.")
            return

        # ── 제거 ─────────────────────────────────────────────────────────────
        if action in ("del", "remove", "rm"):
            if autolist.remove(symbol):
                await messenger.post_message(
                    chat_id,
                    f"✅ {symbol} 오토리스트 제거\n현재 {len(autolist.symbols())}개"
                )
            else:
                await messenger.post_message(chat_id, f"ℹ️ {symbol} 은 오토리스트에 없습니다.")
            return

        await messenger.post_message(chat_id, _HELP)

    return handler
