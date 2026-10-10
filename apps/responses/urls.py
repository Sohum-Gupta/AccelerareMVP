from django.urls import path

from . import views

app_name = "responses"

urlpatterns = [
    path("start/", views.start, name="start"),
    path("history/", views.history, name="history"),
    path("<int:pk>/", views.resume, name="resume"),
    path("<int:pk>/page/<int:number>/", views.page, name="page"),
    path("<int:pk>/save/", views.save_answer, name="save_answer"),
    path("<int:pk>/next/", views.next_page, name="next_page"),
    path("<int:pk>/review/", views.review, name="review"),
    path("<int:pk>/submit/", views.submit, name="submit"),
    path("<int:pk>/result/", views.result, name="result"),
]
