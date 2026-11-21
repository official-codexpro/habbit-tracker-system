from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gamification.services import get_player_profile
from tasks.models import Task, TaskCategory, TaskCompletion
from tasks.services import complete_task_occurrence, generate_task_occurrences


class DashboardViewTests(TestCase):
    def test_home_displays_dynamic_date_and_initial_gaming_dashboard(self):
        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_date"], timezone.localdate())
        self.assertContains(response, "PLAYER ONE")
        self.assertContains(response, "LEVEL UP")
        self.assertContains(response, "MY LIFE JOURNEY")
        self.assertContains(response, "RECENT ACTIVITIES")
        self.assertContains(response, "LEARNING STARTER")
        self.assertContains(response, "Locked achievement: First Mission")
        self.assertContains(response, "0 / 100 XP")

    def test_dashboard_exposes_current_player_progression(self):
        profile = get_player_profile()
        profile.display_name = "Ranger"
        profile.save(update_fields=["display_name", "updated_at"])
        category = TaskCategory.objects.create(name="Learning")
        task = Task.objects.create(
            title="Study Django",
            category=category,
            xp_reward=15,
            start_date=timezone.localdate(),
        )
        generate_task_occurrences(timezone.localdate())
        occurrence = TaskCompletion.objects.get(
            task=task,
            scheduled_date=timezone.localdate(),
        )
        complete_task_occurrence(occurrence.pk)

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RANGER")
        self.assertContains(response, "15 / 100 XP")
        self.assertContains(response, "15 XP")
        self.assertEqual(response.context["player_progress"]["total_xp"], 15)
        self.assertEqual(response.context["player_progress"]["current_streak"], 1)
        self.assertEqual(response.context["player_progress"]["longest_streak"], 1)
        self.assertEqual(response.context["player_progress"]["total_completed_missions"], 1)
        self.assertEqual(response.context["player_progress"]["unlocked_achievement_count"], 1)

    def test_reserved_section_has_a_clear_coming_soon_state(self):
        response = self.client.get(
            reverse("dashboard:coming_soon", kwargs={"section": "daily-tasks"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Daily Tasks")
        self.assertContains(response, "Coming soon")

    def test_rewards_section_has_a_clear_coming_soon_state(self):
        response = self.client.get(
            reverse("dashboard:coming_soon", kwargs={"section": "rewards"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rewards")
        self.assertContains(response, "Coming soon")

    def test_unknown_section_returns_not_found(self):
        response = self.client.get(
            reverse("dashboard:coming_soon", kwargs={"section": "unknown"})
        )

        self.assertEqual(response.status_code, 404)
