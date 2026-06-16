from django.urls import path
from . import views

urlpatterns = [
    path("", views.strategy_list, name="strategy_list"),
    path("create/", views.strategy_create, name="strategy_create"),
    path("ai-generate/", views.strategy_ai_generate, name="strategy_ai_generate"),
    path("<int:strategy_id>/", views.strategy_detail, name="strategy_detail"),
    path("<int:strategy_id>/edit/", views.strategy_edit, name="strategy_edit"),
    path("<int:strategy_id>/delete/", views.strategy_delete, name="strategy_delete"),
]
