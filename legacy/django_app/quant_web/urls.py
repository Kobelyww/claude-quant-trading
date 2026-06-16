from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("data/", include("data_center.urls")),
    path("strategies/", include("strategies.urls")),
    path("backtest/", include("backtest.urls")),
    path("analysis/", include("analysis.urls")),
]
