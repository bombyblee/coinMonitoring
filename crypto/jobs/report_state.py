class ReportState:
    def __init__(self):
        self.enabled = True
        self.trading_paused = False
        self.drawdown_enabled = False
        self.price_freq_sec = 600
        self.pnl_freq_sec = 600

    def start(self):
        self.enabled = True
        self.trading_paused = False

    def stop(self):
        self.enabled = False
        self.trading_paused = True