from django.db import models


class Symbol(models.Model):
    MARKET_CHOICES = [
        ("a_stock", "A股"),
        ("us_stock", "美股"),
        ("crypto", "加密货币"),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100, blank=True)
    market = models.CharField(max_length=20, choices=MARKET_CHOICES, default="a_stock")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["market", "code"]

    def __str__(self):
        return f"{self.code} ({self.name or self.get_market_display()})"

    @property
    def data_count(self):
        return self.marketdata_set.count()

    @property
    def date_range(self):
        qs = self.marketdata_set.aggregate(
            first=models.Min("date"), last=models.Max("date")
        )
        return qs["first"], qs["last"]


class MarketData(models.Model):
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE)
    date = models.DateField()
    open = models.FloatField()
    high = models.FloatField()
    low = models.FloatField()
    close = models.FloatField()
    volume = models.FloatField()

    class Meta:
        unique_together = ["symbol", "date"]
        ordering = ["date"]
