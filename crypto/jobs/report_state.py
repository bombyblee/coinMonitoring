class ReportState:
    def __init__(self):
        self.enabled = True

    def start(self):
        self.enabled = True

    def stop(self):
        self.enabled = False