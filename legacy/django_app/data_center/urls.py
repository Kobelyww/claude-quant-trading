from django.urls import path
from . import views

urlpatterns = [
    path("", views.symbol_list, name="data_list"),
    path("add/", views.symbol_add, name="data_add"),
    path("fetch/<int:symbol_id>/", views.symbol_fetch, name="data_fetch"),
    path("<int:symbol_id>/chart/", views.symbol_chart, name="data_chart"),
    path("<int:symbol_id>/delete/", views.symbol_delete, name="data_delete"),
]
