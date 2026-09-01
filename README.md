# CoinMonitoring — 바이낸스 선물 자동매매 봇

바이낸스 USD-M 선물 시장을 대상으로, 다중 전략 신호 감지 → Telegram 알림 → 자동/수동 주문 실행까지 일괄 처리하는 Python 비동기 트레이딩 봇입니다.

---

## 주요 기능

- **다중 전략 동시 모니터링** — Technical / Event-driven 전략이 병렬 실행
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
├── main.py
├── requirements.txt
├── .env
│
├── strategies/              # 전략 정의
│   ├── base.py
│   ├── technical/           # 기술적 지표 기반 전략
│   └── event/               # 이벤트 드리븐 전략
│
├── crypto/                  # 핵심 인프라
│   ├── binance/             # API 래퍼 (주문, 시세, 유저 스트림)
│   ├── market_data/         # OHLCV 저장소, 워치리스트, 청산 스트림
│   ├── orders/              # 주문 실행, 체결 알림, TP/SL 관리
│   ├── jobs/                # 백그라운드 잡 (PnL 보고, DrawdownGuard)
│   ├── strategies/          # 신호 실행, 전략 러너, 거래 기록
│   └── config.py
│
└── messenger_bot/           # Telegram 봇 명령어 핸들러
```

---

## 트레이딩 전략

### Technical Indicator 기반

| 전략 | 설명 |
|------|------|
| **MomentumBurst** | 다봉 연속 상승/하락 + 거래량 폭등 |
| **RsiReversal** | RSI 극값 + Z-score 기반 평균회귀 |
| **EmaCross** | EMA 골든/데드 크로스 |
| **LevelAware** | 피벗 지지·저항 + ADX 레짐 판별 (브레이크아웃/평균회귀) |

### Event-Driven 기반

| 전략 | 설명 |
|------|------|
| **LiquidationTrap** | 대규모 청산 이벤트 + 호가 depth 비율로 역추세 진입 |

---

## 사전 요구사항

- Python 3.10 이상
- 바이낸스 선물(USD-M) API 키 (거래 권한 필요)
- Telegram Bot Token + Chat ID

---

## 설치 및 실행

```bash
git clone <repo-url>
cd CoinMonitoring
pip install -r requirements.txt
```

프로젝트 루트에 `.env` 파일을 생성합니다.

```env
TELEGRAM_TOKEN=<봇_토큰>
TELEGRAM_CHAT_ID=<채팅_ID>

BINANCE_API_KEY=<API_키>
BINANCE_API_SECRET=<API_시크릿>

MAX_USDT_PER_ORDER=200
AUTO_TRADE_USDT=50
DRAWDOWN_THRESHOLD_USDT=200
WATCHLIST_SYMBOLS=BTCUSDT,ETHUSDT
REPORT_INTERVAL_SEC=600
```

```bash
python main.py
```

---

## Telegram 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` / `/stop` | 보고 시작/중지 |
| `/orders` | 미체결 주문 조회 |
| `BUY BTCUSDT 100` | 시장가 롱 $100 |
| `SELL ETHUSDT 50 @ 3200` | 지정가 숏 $50 at 3200 |
| `strategy add <name>` | 전략 활성화 |
| `strategy del <name>` | 전략 비활성화 |
| `strategy auto on` | 신호 자동 실행 활성화 |
| `watchlist add/del <symbol>` | 워치리스트 관리 |
| `autolist add/del <symbol>` | 자동매매 대상 심볼 관리 |
| `positive` / `swing` | 대기 신호 진입 (TP+SL / SL만) |
| `close <symbol>` | 포지션 수동 청산 |
| `freq <초>` | P&L 보고 주기 변경 |

---

## 주의사항

- 실제 자금이 투입되는 선물 거래 봇입니다. 반드시 소액으로 테스트 후 사용하세요.
- `DRAWDOWN_THRESHOLD_USDT` 설정으로 최대 손실을 제한하세요.
- API 키는 절대 외부에 노출하지 마세요. `.env` 파일을 `.gitignore`에 추가하세요.
- 전략 신호는 참고용이며, 투자 손실에 대한 책임은 사용자에게 있습니다.
