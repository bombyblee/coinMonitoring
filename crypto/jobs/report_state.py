class ReportState:
    def __init__(self):
        self.enabled = True
        self.price_freq_sec = 600
        self.pnl_freq_sec = 600

    def start(self):
        self.enabled = True

    def stop(self):
        self.enabled = False