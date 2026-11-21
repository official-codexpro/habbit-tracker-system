from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gamification.models import DailyStreak, PlayerProfile, XPTransaction
from tasks.models import Task, TaskCategory, TaskCompletion

from .services import (
    get_analytics_dashboard,
    get_daily_analytics,
    get_monthly_analytics,
    get_overview_analytics,
    get_performance_trends,
    get_period_comparison,
    get_weekly_analytics,
)


class AnalyticsServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.player = PlayerProfile.objects.get(singleton_key=1)
        self.learning = TaskCategory.objects.create(name="Learning")
        self.health = TaskCategory.objects.create(name="Health")

    def make_occurrence(
        self,
        title,
        category,
        scheduled_date,
        *,
        status=TaskCompletion.Status.PENDING,
        difficulty=Task.Difficulty.NORMAL,
        completion_cycle=0,
    ):
        task = Task.objects.create(
            title=title,
            category=category,
            difficulty=difficulty,
            start_date=scheduled_date,
        )
        return TaskCompletion.objects.create(
            task=task,
            scheduled_date=scheduled_date,
            status=status,
            completed_at=timezone.now() if status == TaskCompletion.Status.COMPLETED else None,
            completion_cycle=completion_cycle,
        )

    def make_xp_transaction(
        self,
        transaction_type,
        amount,
        *,
        occurrence=None,
        completion_cycle=0,
        balance_after=0,
    ):
        return XPTransaction.objects.create(
            player=self.player,
            task_completion=occurrence,
            completion_cycle=completion_cycle,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=balance_after,
            description="Analytics test record",
        )

    def test_dashboard_aggregates_real_records_and_is_read_only(self):
        completed = self.make_occurrence(
            "Study Django",
            self.learning,
            self.today,
            status=TaskCompletion.Status.COMPLETED,
            difficulty=Task.Difficulty.HARD,
            completion_cycle=1,
        )
        self.make_occurrence(
            "Walk outside",
            self.health,
            self.today,
            status=TaskCompletion.Status.SKIPPED,
            difficulty=Task.Difficulty.EASY,
        )
        self.make_occurrence(
            "Read a chapter",
            self.learning,
            self.today - timedelta(days=1),
        )
        self.make_xp_transaction(
            XPTransaction.Type.EARNED,
            20,
            occurrence=completed,
            completion_cycle=1,
            balance_after=20,
        )
        self.make_xp_transaction(
            XPTransaction.Type.BONUS,
            10,
            balance_after=30,
        )
        self.player.total_xp = 30
        self.player.save(update_fields=["total_xp", "updated_at"])
        DailyStreak.objects.create(
            player=self.player,
            activity_date=self.today,
            qualifying_activity_count=1,
            is_active_day=True,
        )

        before = (
            Task.objects.count(),
            TaskCompletion.objects.count(),
            DailyStreak.objects.count(),
            XPTransaction.objects.count(),
            PlayerProfile.objects.count(),
        )
        data = get_analytics_dashboard()
        after = (
            Task.objects.count(),
            TaskCompletion.objects.count(),
            DailyStreak.objects.count(),
            XPTransaction.objects.count(),
            PlayerProfile.objects.count(),
        )

        overview = data["overview"]
        self.assertEqual(before, after)
        self.assertEqual(overview["scheduled_missions"], 3)
        self.assertEqual(overview["completed_missions"], 1)
        self.assertEqual(overview["pending_missions"], 1)
        self.assertEqual(overview["skipped_missions"], 1)
        self.assertEqual(overview["missed_missions"], 1)
        self.assertEqual(overview["completion_rate"], 33.3)
        self.assertEqual(overview["total_xp_balance"], 30)
        self.assertEqual(overview["lifetime_xp_earned"], 30)
        self.assertEqual(overview["current_streak"], 1)
        self.assertEqual(data["daily"]["completed"], 1)
        week_start = self.today - timedelta(days=self.today.weekday())
        expected_weekly = 2 + int(self.today - timedelta(days=1) >= week_start)
        self.assertEqual(data["weekly"]["scheduled_missions"], expected_weekly)
        self.assertEqual(data["monthly"]["completed"], 1)
        self.assertEqual(data["categories"]["strongest_category"]["category"], "Learning")
        self.assertEqual(data["difficulty"]["difficulties"][2]["xp_net"], 20)
        self.assertEqual(data["trends"]["period"], "30d")
        self.assertIn("RECOMMENDATION", [item["type"] for item in data["insights"]])

    def test_undo_uses_current_occurrence_state_and_signed_xp_ledger(self):
        occurrence = self.make_occurrence(
            "Practice typing",
            self.learning,
            self.today - timedelta(days=1),
            completion_cycle=1,
        )
        self.make_xp_transaction(
            XPTransaction.Type.EARNED,
            25,
            occurrence=occurrence,
            completion_cycle=1,
            balance_after=25,
        )
        self.make_xp_transaction(
            XPTransaction.Type.REVERSED,
            -25,
            occurrence=occurrence,
            completion_cycle=1,
            balance_after=0,
        )

        overview = get_overview_analytics()

        self.assertEqual(overview["completed_missions"], 0)
        self.assertEqual(overview["pending_missions"], 1)
        self.assertEqual(overview["missed_missions"], 1)
        self.assertEqual(overview["lifetime_xp_earned"], 25)
        self.assertEqual(overview["lifetime_xp_reversed"], 25)
        self.assertEqual(overview["lifetime_xp_net"], 0)
        self.assertEqual(overview["total_xp_balance"], 0)

    def test_future_occurrences_are_not_included_in_current_analytics(self):
        future = self.today + timedelta(days=1)
        self.make_occurrence(
            "Future mission",
            self.learning,
            future,
            status=TaskCompletion.Status.COMPLETED,
            completion_cycle=1,
        )

        daily = get_daily_analytics(future)
        overview = get_overview_analytics()

        self.assertFalse(daily["available"])
        self.assertIsNone(daily["completed"])
        self.assertEqual(overview["scheduled_missions"], 0)
        self.assertEqual(overview["completed_missions"], 0)

    def test_comparison_is_unavailable_without_previous_period_records(self):
        self.make_occurrence(
            "Current week mission",
            self.learning,
            self.today,
        )

        comparison = get_period_comparison("week")

        self.assertFalse(comparison["available"])
        self.assertFalse(comparison["previous_period_available"])
        self.assertIsNone(comparison["changes"]["completed_missions"])
        self.assertIsNone(comparison["changes"]["completion_rate_points"])

    def test_comparison_calculates_change_only_from_matching_recorded_periods(self):
        previous_day = self.today - timedelta(days=7)
        self.make_occurrence(
            "Previous completed mission",
            self.learning,
            previous_day,
            status=TaskCompletion.Status.COMPLETED,
            completion_cycle=1,
        )
        self.make_occurrence(
            "Current completed mission",
            self.learning,
            self.today,
            status=TaskCompletion.Status.COMPLETED,
            completion_cycle=1,
        )
        self.make_occurrence(
            "Current pending mission",
            self.health,
            self.today,
        )

        comparison = get_period_comparison("week")

        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["current"]["completion_rate"], 50)
        self.assertEqual(comparison["previous"]["completion_rate"], 100)
        self.assertEqual(comparison["changes"]["completion_rate_points"], -50)
        self.assertEqual(comparison["changes"]["completed_missions"], 0)

    def test_periods_and_empty_trends_have_honest_shapes(self):
        self.make_occurrence(
            "Monthly mission",
            self.learning,
            self.today,
        )

        weekly = get_weekly_analytics()
        monthly = get_monthly_analytics()
        trends = get_performance_trends("30d")

        self.assertEqual(len(weekly["days"]), 7)
        self.assertEqual(monthly["scheduled_missions"], 1)
        self.assertTrue(monthly["weeks"])
        self.assertEqual(len(trends["points"]), 30)
        self.assertTrue(trends["data_available"])


class AnalyticsViewTests(TestCase):
    def test_analytics_page_renders_shared_shell_and_active_navigation(self):
        response = self.client.get(reverse("analytics:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_section"], "analytics")
        self.assertContains(response, "LIFE ANALYTICS")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "analytics.js")
        self.assertContains(response, "/analytics/api/dashboard/")

    def test_dashboard_api_returns_empty_state_without_fake_metrics(self):
        response = self.client.get(reverse("analytics:dashboard_api"))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["overview"]["data_available"])
        self.assertEqual(payload["overview"]["scheduled_missions"], 0)
        self.assertIsNone(payload["overview"]["completion_rate"])
        self.assertEqual(payload["trends"]["points"], [])
        self.assertEqual(payload["insights"][0]["type"], "INSUFFICIENT_DATA")

    def test_date_endpoints_validate_inputs_and_treat_future_dates_as_unavailable(self):
        daily_url = reverse("analytics:daily_api")
        invalid = self.client.get(daily_url, {"date": "not-a-date"})
        future = self.client.get(
            daily_url,
            {"date": (timezone.localdate() + timedelta(days=1)).isoformat()},
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("YYYY-MM-DD", invalid.json()["error"])
        self.assertEqual(future.status_code, 200)
        self.assertFalse(future.json()["available"])
        self.assertIsNone(future.json()["scheduled_missions"])

    def test_read_only_date_endpoint_does_not_generate_recurrence_occurrences(self):
        category = TaskCategory.objects.create(name="Learning")
        Task.objects.create(
            title="Daily study",
            category=category,
            recurrence_type=Task.RecurrenceType.DAILY,
            start_date=timezone.localdate() - timedelta(days=2),
        )

        response = self.client.get(reverse("analytics:daily_api"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scheduled_missions"], 0)
        self.assertEqual(TaskCompletion.objects.count(), 0)

    def test_analytics_endpoints_return_database_backed_json_shapes(self):
        endpoints = (
            ("analytics:overview_api", {}),
            ("analytics:weekly_api", {}),
            ("analytics:monthly_api", {}),
            ("analytics:categories_api", {}),
            ("analytics:difficulty_api", {}),
            ("analytics:trends_api", {"range": "7d"}),
            ("analytics:comparison_api", {"period": "month"}),
            ("analytics:insights_api", {}),
        )
        for route_name, query in endpoints:
            with self.subTest(endpoint=route_name):
                response = self.client.get(reverse(route_name), query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/json")
                self.assertIsInstance(response.json(), dict)

        invalid_range = self.client.get(
            reverse("analytics:trends_api"),
            {"range": "forever"},
        )
        invalid_period = self.client.get(
            reverse("analytics:comparison_api"),
            {"period": "year"},
        )
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(invalid_period.status_code, 400)

    def test_api_rejects_non_get_methods_with_json_error(self):
        response = self.client.post(reverse("analytics:overview_api"))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET")
        self.assertIn("error", response.json())
