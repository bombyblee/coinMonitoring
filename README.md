# CoinMonitoring — 바이낸스 선물 자동매매 봇

바이낸스 USD-M 선물 시장을 대상으로, 다중 전략 신호 감지 → Telegram 알림 → 자동/수동 주문 실행까지 일괄 처리하는 Python 비동기 트레이딩 봇입니다.

---

## 주요 기능

- **다중 전략 동시 모니터링** — 4가지 전략이 1분마다 병렬 실행
- **Telegram 양방향 제어** — 명령어로 전략 추가/제거, 수동 주문, 보고서 조회
- **자동 주문 실행** — 신호 확인 후 진입 + TP/SL 주문을 바이낸스에 자동 제출
- **실시간 체결 알림** — WebSocket 유저 스트림으로 체결 즉시 Telegram 푸시
- **손실 방어 (DrawdownGuard)** — 계좌 손실이 임계값 초과 시 모든 포지션 강제 청산
- **거래 기록** — 진입~청산 이력을 CSV로 저장, 수수료 포함 PnL 자동 계산
- **P&L 정기 보고** — 미실현 손익·포지션·펀딩비를 주기적으로 Telegram 전송

---

## 프로젝트 구조

```
CoinMonitoring/
├── main.py                      # 진입점 — 전체 비동기 태스크 초기화 및 실행
├── requirements.txt
├── .env                         # API 키 및 환경 설정 (직접 작성 필요)
│
├── crypto/
│   ├── config.py                # .env 로드 → AppConfig 데이터클래스
│   ├── binance/
│   │   ├── futures_trader.py    # 시장가/지정가/TP·SL 주문 래퍼
│   │   ├── futures_market_api.py# 시세·캔들 데이터 조회
│   │   ├── user_stream.py       # WebSocket 유저 스트림 (체결 이벤트)
│   │   └── symbol_rules.py      # 거래소 필터 (최소 수량, 틱 사이즈)
│   │
│   ├── market_data/
│   │   ├── ohlcv_store.py       # 인메모리 OHLCV + 30여 개 지표 자동 계산
│   │   ├── ohlcv_job.py         # 60초마다 1분봉 갱신 백그라운드 잡
│   │   └── watchlist.py         # 모니터링 심볼 목록 관리
│   │
│   ├── strategies/
│   │   ├── base.py              # BaseStrategy / Signal 데이터클래스
│   │   ├── momentum_burst.py    # 3봉 모멘텀 + 거래량 폭등 전략
│   │   ├── rsi_reversal.py      # RSI 극값 평균회귀 전략
│   │   ├── ema_cross.py         # EMA 골든/데드 크로스 전략
│   │   ├── level_aware.py       # 피벗 레벨 + 시장 레짐 복합 전략
│   │   ├── level_finder.py      # 피벗 High/Low 지지·저항 탐색
│   │   ├── regime_detector.py   # ADX 기반 모멘텀/평균회귀 레짐 판별
│   │   ├── runner.py            # 전략 폴링 루프 + 신호 라우팅
│   │   ├── execution.py         # 신호 → 시장가 진입 + TP/SL 주문
│   │   └── trade_logger.py      # 진입~청산 추적 + CSV 기록
│   │
│   ├── orders/
│   │   ├── service.py           # 리스크 체크, 수량 계산, 주문 실행
│   │   ├── sl_tp_monitor.py     # TP/SL 주문 바이낸스 제출
│   │   └── fill_notifier.py     # 체결 이벤트 → Telegram 알림
│   │
│   └── jobs/
│       ├── pnl_reporter.py      # 미실현 PnL·포지션·펀딩비 보고
│       └── drawdown_guard.py    # 손실 임계값 초과 시 전체 포지션 강제 청산
│
└── messenger_bot/
    ├── TelegramBot.py           # 메시지 발송 래퍼
    ├── telegram_commands.py     # /start /stop /orders /help
    ├── trade_commands.py        # BUY/SELL 텍스트 명령 파싱
    ├── strategy_commands.py     # strategy add/del/auto 명령
    ├── watchlist_commands.py    # watchlist add/del 명령
    ├── sl_tp_commands.py        # TP/SL 설정 명령 파싱
    ├── signal_commands.py       # positive / swing 신호 확인
    └── text_router.py           # 텍스트 메시지 → 핸들러 라우팅
```

---

## 트레이딩 전략

### 1. MomentumBurst (5분봉)
3봉 연속 0.25% 이상 상승 + 거래량 급등(1.8×) + EMA 정배열 + RSI < 78 조건이 동시에 충족될 때 롱 진입.
반대 조건에서 숏 진입. TP 3.5×ATR / SL 3.0×ATR.

### 2. RsiReversal (1분봉)
RSI가 30선을 상향 돌파 + Z-score < -1.5 + 거래량 증가 → 롱 진입 (과매도 반등).
RSI가 70선을 하향 돌파 + Z-score > 1.5 → 숏 진입 (과매수 반락).
TP 2.5×ATR / SL 2.5×ATR.

### 3. EmaCross (5분봉)
EMA5가 EMA20을 상향 돌파(골든크로스) + RSI 40~70 + 거래량 1.3× → 롱 진입.
EMA5가 EMA20을 하향 돌파(데드크로스) → 포지션 청산.
TP 4.0×ATR / SL 4.0×ATR.

### 4. LevelAware (1분봉 + 15분봉 레벨)
15분봉 기준 피벗 High/Low로 지지·저항 구간 탐색. ADX로 시장 레짐 판별:
- **모멘텀(ADX ≥ 25)**: 저항 돌파 시 롱 / 지지 붕괴 시 숏 (브레이크아웃)
- **평균회귀(ADX ≤ 20)**: 지지 근처 RSI < 40 → 롱 / 저항 근처 RSI > 60 → 숏

TP 3.0×ATR / SL 2.5×ATR.

---

## 사전 요구사항

- Python 3.10 이상
- 바이낸스 선물(USD-M) API 키 (거래 권한 필요)
- Telegram Bot Token + Chat ID

---

## 설치 및 실행

### 1. 저장소 클론 및 의존성 설치

```bash
git clone <repo-url>
cd CoinMonitoring
pip install -r requirements.txt
```

### 2. `.env` 파일 작성

프로젝트 루트에 `.env` 파일을 생성합니다.

```env
# Telegram
TELEGRAM_TOKEN=<봇_토큰>
TELEGRAM_CHAT_ID=<채팅_ID>

# Binance Futures API
BINANCE_API_KEY=<API_키>
BINANCE_API_SECRET=<API_시크릿>

# 리스크 설정
MAX_USDT_PER_ORDER=200          # 주문당 최대 USDT
AUTO_TRADE_USDT=50              # 자동매매 기본 포지션 크기
ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT # 허용 심볼 (콤마 구분)
DRAWDOWN_THRESHOLD_USDT=200     # 강제청산 손실 임계값

# 초기 워치리스트
WATCHLIST_SYMBOLS=BTCUSDT,ETHUSDT

# 보고 주기 (초)
REPORT_INTERVAL_SEC=600
```

### 3. 실행

```bash
python main.py
```

정상 기동 시 Telegram으로 시작 메시지가 전송되며, 이후 명령어로 제어합니다.

---

## Telegram 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 보고 시작 |
| `/stop` | 보고 중지 |
| `/orders` | 미체결 주문 조회 |
| `/help` | 명령어 목록 |
| `BUY BTCUSDT 100` | BTCUSDT 시장가 롱 $100 |
| `SELL ETHUSDT 50 @ 3200` | ETHUSDT 지정가 숏 $50 at 3200 |
| `strategy add momentum_burst` | 전략 활성화 |
| `strategy del ema_cross` | 전략 비활성화 |
| `strategy auto on` | 신호 자동 실행 활성화 |
| `watchlist add SOLUSDT` | 워치리스트 심볼 추가 |
| `watchlist del SOLUSDT` | 워치리스트 심볼 제거 |
| `freq 300` | P&L 보고 주기를 300초로 변경 |
| `positive` | 대기 중인 신호 확인 (진입 실행) |
| `swing` | 스윙 모드로 신호 실행 (SL만, TP 없음) |

---

## 실행 흐름

```
main.py 기동
  ├─ OhlcvJob        — 60초마다 1분봉 갱신
  ├─ StrategyRunner  — 60초마다 전략 신호 감지 → Telegram 알림
  ├─ UserDataStream  — WebSocket 체결 이벤트 실시간 수신
  ├─ PnlReporterJob  — 주기적 PnL·포지션 보고
  ├─ DrawdownGuard   — 30초마다 손실 감시
  ├─ TradeLogger     — 진입~청산 추적 + CSV 기록
  └─ Telegram App    — 명령어 수신 및 처리
```

---

## 주의사항

- 실제 자금이 투입되는 선물 거래 봇입니다. 반드시 소액으로 테스트 후 사용하세요.
- `DRAWDOWN_THRESHOLD_USDT` 설정으로 최대 손실을 제한하세요.
- API 키는 절대 외부에 노출하지 마세요. `.env` 파일을 `.gitignore`에 추가하세요.
- 전략 신호는 참고용이며, 투자 손실에 대한 책임은 사용자에게 있습니다.
