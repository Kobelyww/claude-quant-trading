from django.urls import path
from . import views

urlpatterns = [
    path("", views.backtest_list, name="backtest_list"),
    path("run/", views.backtest_run, name="backtest_run"),
    path("<int:run_id>/", views.backtest_detail, name="backtest_detail"),
    path("<int:run_id>/status/", views.backtest_status, name="backtest_status"),
    path("compare/", views.backtest_compare, name="backtest_compare"),
]
