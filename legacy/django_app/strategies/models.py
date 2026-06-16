from django.db import models


class Strategy(models.Model):
    TYPE_CHOICES = [
        ("ma_cross", "双均线交叉"),
        ("momentum", "动量策略"),
        ("mean_reversion", "均值回归"),
        ("grid", "网格交易"),
        ("custom", "自定义"),
    ]

    name = models.CharField(max_length=100)
    strategy_type = models.CharField(max_length=50, choices=TYPE_CHOICES, default="ma_cross")
    params = models.JSONField(default=dict, blank=True)
    code = models.TextField(blank=True, help_text="自定义策略Python代码")
    is_ai_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_strategy_type_display()})"

    def get_params_display(self):
        if not self.params:
            return "-"
        return ", ".join(f"{k}={v}" for k, v in self.params.items())
