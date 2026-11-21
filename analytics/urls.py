from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.analytics_home, name="home"),
    path("api/dashboard/", views.dashboard_api, name="dashboard_api"),
    path("api/overview/", views.overview_api, name="overview_api"),
    path("api/daily/", views.daily_api, name="daily_api"),
    path("api/weekly/", views.weekly_api, name="weekly_api"),
    path("api/monthly/", views.monthly_api, name="monthly_api"),
    path("api/categories/", views.categories_api, name="categories_api"),
    path("api/difficulty/", views.difficulty_api, name="difficulty_api"),
    path("api/trends/", views.trends_api, name="trends_api"),
    path("api/comparison/", views.comparison_api, name="comparison_api"),
    path("api/insights/", views.insights_api, name="insights_api"),
    path("api/learning/", views.learning_api, name="learning_api"),
]
