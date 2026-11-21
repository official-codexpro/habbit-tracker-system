from django.urls import path

from . import views

app_name = "learning"

urlpatterns = [
    path("", views.learning_dashboard, name="dashboard"),
    path("history/", views.learning_history, name="history"),
    path("api/dashboard/", views.dashboard_api, name="dashboard_api"),
    path("api/history/", views.history_api, name="history_api"),
    path("api/goals/", views.goals_api, name="goals_api"),
    path("api/goals/<int:goal_id>/", views.goal_detail_api, name="goal_detail_api"),
    path("api/goals/<int:goal_id>/<str:action>/", views.goal_status_api, name="goal_status_api"),
    path("api/skills/", views.skills_api, name="skills_api"),
    path("api/skills/<int:skill_id>/", views.skill_detail_api, name="skill_detail_api"),
    path("api/skills/<int:skill_id>/proficiency/", views.skill_proficiency_api, name="skill_proficiency_api"),
    path("api/courses/", views.courses_api, name="courses_api"),
    path("api/courses/<int:course_id>/", views.course_detail_api, name="course_detail_api"),
    path("api/courses/<int:course_id>/topics/", views.topics_api, name="topics_api"),
    path("api/courses/<int:course_id>/<str:action>/", views.course_status_api, name="course_status_api"),
    path("api/topics/<int:topic_id>/", views.topic_detail_api, name="topic_detail_api"),
    path("api/topics/<int:topic_id>/<str:action>/", views.topic_status_api, name="topic_status_api"),
    path("api/topics/<int:topic_id>/reorder/", views.topic_reorder_api, name="topic_reorder_api"),
    path("api/sessions/", views.sessions_api, name="sessions_api"),
    path("api/sessions/<int:session_id>/", views.session_detail_api, name="session_detail_api"),
]
