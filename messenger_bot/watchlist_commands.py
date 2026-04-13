from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

_MAX_SYMBOLS = 10

_HELP = (
    "📋 워치리스트 명령어\n"
    "  watchlist          — 현재 목록 조회\n"
    "  watchlist add <심볼>  — 심볼 추가 (최대 10개)\n"
    "  watchlist del <심볼>  — 심볼 제거"
)


def make_watchlist_handler(watchlist, ohlcv_job, autolist=None):
    """
    watchlist  — 현재 심볼 목록
    watchlist add BTCUSDT  — 추가 (최대 10개, 다음 tick에 자동 초기화)
    watchlist del BTCUSDT  — 제거
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        parts = (update.message.text or "").strip().split()
        # parts[0] == "watchlist"

        # ── 목록 조회 ────────────────────────────────────────────────────────
        if len(parts) == 1:
            syms = watchlist.symbols()
            if not syms:
                await update.message.reply_text("워치리스트가 비어 있습니다.")
            else:
                lines = [f"{i}. {s}" for i, s in enumerate(syms, 1)]
                await update.message.reply_text(
                    f"📋 워치리스트 ({len(syms)}/{_MAX_SYMBOLS})\n" + "\n".join(lines)
                )
            return

        if len(parts) < 3:
            await update.message.reply_text(_HELP)
            return

        action = parts[1].lower()
        symbol = parts[2].upper()

        # ── 추가 ─────────────────────────────────────────────────────────────
        if action == "add":
            if len(watchlist) >= _MAX_SYMBOLS:
                await update.message.reply_text(
                    f"❌ 워치리스트가 가득 찼습니다 (최대 {_MAX_SYMBOLS}개).\n"
                    "먼저 `watchlist del <심볼>`로 하나를 제거하세요."
                )
                return

            added = watchlist.add(symbol)
            if not added:
                await update.message.reply_text(f"ℹ️ {symbol} 은 이미 워치리스트에 있습니다.")
                return

            # 즉시 초기화 (다음 tick을 기다리지 않음)
            await ohlcv_job._init_symbol(symbol)
            candles = ohlcv_job.store.max_len
            await update.message.reply_text(
                f"✅ {symbol} 추가 완료 ({candles}봉 로드됨)\n"
                f"현재 {len(watchlist)}/{_MAX_SYMBOLS}개"
            )
            return

        # ── 제거 ─────────────────────────────────────────────────────────────
        if action in ("del", "remove", "rm"):
            removed = watchlist.remove(symbol)
            if not removed:
                await update.message.reply_text(f"ℹ️ {symbol} 은 워치리스트에 없습니다.")
                return
            # store에서도 즉시 제거
            ohlcv_job.store.remove(symbol)
            # autolist에도 있으면 함께 제거
            auto_removed = autolist.remove(symbol) if autolist else False
            auto_tag = "  (오토리스트에서도 제거됨)" if auto_removed else ""
            await update.message.reply_text(
                f"✅ {symbol} 제거 완료{auto_tag}\n"
                f"현재 {len(watchlist)}/{_MAX_SYMBOLS}개"
            )
            return

        await update.message.reply_text(_HELP)

    return handler
