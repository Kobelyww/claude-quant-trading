from django.db import models


class AppSetting(models.Model):
    key = models.CharField(max_length=50, unique=True)
    value = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return f"{self.key}={self.value}"
