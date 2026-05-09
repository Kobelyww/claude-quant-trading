from django.db import models


class BacktestRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "等待中"),
        ("running", "运行中"),
        ("done", "已完成"),
        ("failed", "失败"),
    ]

    symbol = models.ForeignKey("data_center.Symbol", on_delete=models.CASCADE)
    strategy = models.ForeignKey("strategies.Strategy", on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    initial_cash = models.FloatField(default=100000)
    result_json = models.JSONField(default=dict, blank=True)
    equity_curve = models.JSONField(default=list, blank=True)
    trades_json = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.symbol.code} - {self.strategy.name} ({self.created_at:%Y-%m-%d %H:%M})"

    @property
    def total_return(self):
        if self.result_json:
            return self.result_json.get("总收益率", "N/A")
        return "N/A"

    @property
    def sharpe(self):
        if self.result_json:
            return self.result_json.get("夏普比率", "N/A")
        return "N/A"
