from django.urls import path

from . import views

app_name = "responses"

urlpatterns = [
    path("start/", views.start, name="start"),
]
