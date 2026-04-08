import asyncio
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes

_ORDER_TYPE_EMOJI = {
    "LIMIT": "📋",
    "MARKET": "⚡",
    "STOP_MARKET": "🛑",
    "TAKE_PROFIT_MARKET": "🎯",
    "STOP": "🛑",
    "TAKE_PROFIT": "🎯",
    "TRAILING_STOP_MARKET": "📉",
}

_HELP_TEXT = """\
🤖 CoinMonitor 사용 가이드

📌 슬래시 커맨드
  /start      자동 리포트 재개
  /stop       자동 리포트 중지
  /orders     현재 오픈 주문 조회
  /strategy   전략 현황 조회
  /help       이 도움말 표시

──────────────────────────
📊 매수/매도 주문 (허용 유저만)
  BUY <심볼> <USDT>              시장가 매수
    예) BUY BTCUSDT 100
  BUY <심볼> <USDT> @ <가격>     지정가 매수
    예) BUY BTCUSDT 100 @ 95000
  SELL <심볼> <USDT>             시장가 매도
  SELL <심볼> <USDT> @ <가격>    지정가 매도

──────────────────────────
🎯 TP / SL 주문  (포지션 번호는 리포트 기준)

  [가격 기준] → Binance 실주문 (Open Orders 표시)
  <번호> tp <가격> <티커>
    예) 1 tp 97000 btc
  <번호> sl <가격> <티커>
    예) 1 sl 93000 btc

  [손익 기준] → 로컬 모니터 (USDT 손익 도달 시 청산)
  <번호> tp <금액> usdt
    예) 1 tp 100 usdt
  <번호> sl <금액> usdt
    예) 1 sl -50 usdt

  sltp list          로컬 트리거 목록
  sltp cancel <ID>   로컬 트리거 취소

──────────────────────────
📈 워치리스트 (OHLCV 1분봉 자동 수집)
  watchlist              현재 목록 조회
  watchlist add <심볼>   심볼 추가 (최대 10개)
    예) watchlist add SOLUSDT
  watchlist del <심볼>   심볼 제거
    예) watchlist del SOLUSDT

──────────────────────────
🤖 전략 관리
  strategy                  실행 중 / 전체 전략 현황
  strategy add <이름>        전략 활성화
    예) strategy add RsiReversal
  strategy del <이름>        전략 비활성화
    예) strategy del EmaCross

──────────────────────────
⚙️ 설정
  freq <초>          PnL 리포트 주기 변경
    예) freq 300\
"""


def make_handlers(state, messenger):
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.start()
        await messenger.post_message(
            str(update.effective_chat.id),
            "▶️ 시스템 재개\n리포트 · 전략 · 자동매매 · 드로우다운 가드 모두 활성화됨"
        )

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.stop()
        await messenger.post_message(
            str(update.effective_chat.id),
            "⏸ 시스템 전체 중지\n리포트 · 전략 시그널 · 자동/수동 주문 · 드로우다운 가드 모두 비활성화됨\n재개: /start"
        )

    return start_cmd, stop_cmd


def make_orders_handler(trader, messenger):
    async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        try:
            orders = await trader.get_open_orders()
        except Exception as e:
            await messenger.post_message(chat_id, f"❌ 주문 조회 실패: {e}")
            return

        if not orders:
            await messenger.post_message(chat_id, "📭 현재 오픈 주문 없음")
            return

        # 심볼 기준 정렬
        orders.sort(key=lambda o: (o.get("symbol", ""), o.get("orderId", 0)))

        lines = [f"📋 오픈 주문 ({len(orders)}건)"]
        for o in orders:
            sym = o.get("symbol", "?")
            side = o.get("side", "?")
            otype = o.get("type", "?")
            emoji = _ORDER_TYPE_EMOJI.get(otype, "📄")
            stop_px = float(o.get("stopPrice", 0.0))
            limit_px = float(o.get("price", 0.0))
            orig_qty = o.get("origQty", "?")
            order_id = o.get("orderId", "?")

            # 가격 표시: stop 주문은 stopPrice, 지정가는 price
            if stop_px > 0:
                px_str = f"stop@{stop_px}"
            elif limit_px > 0:
                px_str = f"@{limit_px}"
            else:
                px_str = "MARKET"

            lines.append(
                f"{emoji} {sym} {side} {otype}\n"
                f"   qty={orig_qty}  {px_str}  id={order_id}"
            )

        await messenger.post_message(chat_id, "\n".join(lines))

    return orders_cmd


def make_help_handler(messenger):
    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await messenger.post_message(str(update.effective_chat.id), _HELP_TEXT)

    return help_cmd
