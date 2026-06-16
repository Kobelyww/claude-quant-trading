from django.urls import path
from . import views

urlpatterns = [
    path("", views.analysis_list, name="analysis_list"),
    path("run/", views.analysis_run, name="analysis_run"),
    path("<int:report_id>/", views.analysis_detail, name="analysis_detail"),
]
