import logging
from datetime import date

from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .services import (
    get_analytics_dashboard,
    get_category_analytics,
    get_daily_analytics,
    get_difficulty_analytics,
    get_learning_analytics,
    get_monthly_analytics,
    get_overview_analytics,
    get_period_comparison,
    get_performance_trends,
    get_weekly_analytics,
)

logger = logging.getLogger(__name__)


def _request_date(request, key="date"):
    value = request.GET.get(key)
    if value is None:
        return timezone.localdate()
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Date must use the YYYY-MM-DD format.") from error
    if parsed.isoformat() != value:
        raise ValueError("Date must use the YYYY-MM-DD format.")
    return parsed


def _api_get(request, operation, description):
    if request.method != "GET":
        return JsonResponse(
            {"error": "This endpoint only accepts GET requests."},
            status=405,
            headers={"Allow": "GET"},
        )
    try:
        payload = operation()
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    except DatabaseError:
        logger.exception("Database error while %s analytics.", description)
        return JsonResponse(
            {"error": "Analytics could not be loaded. Please try again."},
            status=500,
        )
    return JsonResponse(payload)


@require_GET
def analytics_home(request):
    try:
        overview = get_overview_analytics()
    except DatabaseError:
        logger.exception("Database error while loading the analytics page.")
        return render(
            request,
            "analytics/index.html",
            {
                "active_section": "analytics",
                "current_date": timezone.localdate(),
                "analytics_error": "Analytics data is temporarily unavailable.",
                "analytics_config": _analytics_config(),
            },
            status=503,
        )
    return render(
        request,
        "analytics/index.html",
        {
            "active_section": "analytics",
            "current_date": timezone.localdate(),
            "player_progress": overview["player_progress"],
            "analytics_today": timezone.localdate(),
            "analytics_config": _analytics_config(),
        },
    )


def _analytics_config():
    return {
        "today": timezone.localdate().isoformat(),
        "urls": {
            "dashboard": reverse("analytics:dashboard_api"),
            "daily": reverse("analytics:daily_api"),
            "weekly": reverse("analytics:weekly_api"),
            "monthly": reverse("analytics:monthly_api"),
            "trends": reverse("analytics:trends_api"),
            "comparison": reverse("analytics:comparison_api"),
        },
    }


def overview_api(request):
    return _api_get(request, get_overview_analytics, "loading overview")


def daily_api(request):
    return _api_get(
        request,
        lambda: get_daily_analytics(_request_date(request)),
        "loading daily analytics",
    )


def weekly_api(request):
    return _api_get(
        request,
        lambda: get_weekly_analytics(_request_date(request)),
        "loading weekly analytics",
    )


def monthly_api(request):
    return _api_get(
        request,
        lambda: get_monthly_analytics(_request_date(request)),
        "loading monthly analytics",
    )


def categories_api(request):
    return _api_get(
        request,
        get_category_analytics,
        "loading category analytics",
    )


def difficulty_api(request):
    return _api_get(
        request,
        get_difficulty_analytics,
        "loading difficulty analytics",
    )


def trends_api(request):
    period = request.GET.get("range", "30d")
    return _api_get(
        request,
        lambda: get_performance_trends(period),
        "loading performance trends",
    )


def comparison_api(request):
    period = request.GET.get("period", "week")
    return _api_get(
        request,
        lambda: get_period_comparison(period),
        "comparing analytics periods",
    )


def insights_api(request):
    def load_insights():
        return {"insights": get_analytics_dashboard()["insights"]}

    return _api_get(request, load_insights, "generating analytics insights")


def dashboard_api(request):
    return _api_get(
        request,
        get_analytics_dashboard,
        "loading analytics dashboard",
    )


@require_GET
def learning_api(request):
    def operation():
        return get_learning_analytics()

    return _api_get(request, operation, "loading learning analytics")
