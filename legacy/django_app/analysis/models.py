from django.db import models


class AnalysisReport(models.Model):
    TYPE_CHOICES = [
        ("full", "全面分析"),
        ("technical", "技术面"),
        ("regime", "市场状态"),
        ("risk", "风险评估"),
    ]

    symbol = models.ForeignKey("data_center.Symbol", on_delete=models.CASCADE)
    report_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="full")
    content = models.TextField(blank=True)
    metrics_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.symbol.code} - {self.get_report_type_display()} ({self.created_at:%Y-%m-%d})"
