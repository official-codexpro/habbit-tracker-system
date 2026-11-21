from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tasks.models import Task, TaskCategory, TaskCompletion
from tasks.services import complete_task_occurrence, generate_task_occurrences, undo_task_completion

from .models import Achievement, DailyStreak, PlayerAchievement, PlayerProfile, XPTransaction
from .services import (
    InsufficientXP,
    award_bonus_xp,
    award_task_xp,
    calculate_current_streak,
    calculate_level,
    calculate_level_progress,
    calculate_longest_streak,
    calculate_rank,
    calculate_xp_to_next_level,
    check_achievements,
    get_locked_achievements,
    get_player_profile,
    get_player_progress,
    get_unlocked_achievements,
    get_xp_history,
    get_xp_remaining,
    record_daily_activity,
    reverse_task_xp,
)


class LevelAndRankTests(SimpleTestCase):
    def test_level_boundaries_and_progress(self):
        boundaries = {
            0: 1,
            99: 1,
            100: 2,
            299: 2,
            300: 3,
            599: 3,
            600: 4,
            1000: 5,
        }
        for xp, expected_level in boundaries.items():
            with self.subTest(xp=xp):
                self.assertEqual(calculate_level(xp), expected_level)

        self.assertEqual(calculate_level_progress(99), 99)
        self.assertEqual(calculate_level_progress(100), 0)
        self.assertEqual(get_xp_remaining(99), 1)
        self.assertEqual(get_xp_remaining(299), 1)
        self.assertEqual(get_xp_remaining(300), 300)
        self.assertEqual(calculate_xp_to_next_level(3), 300)

    def test_rank_boundaries(self):
        boundaries = {
            1: PlayerProfile.Rank.BEGINNER,
            4: PlayerProfile.Rank.BEGINNER,
            5: PlayerProfile.Rank.APPRENTICE,
            9: PlayerProfile.Rank.APPRENTICE,
            10: PlayerProfile.Rank.WARRIOR,
            19: PlayerProfile.Rank.WARRIOR,
            20: PlayerProfile.Rank.ELITE,
            29: PlayerProfile.Rank.ELITE,
            30: PlayerProfile.Rank.MASTER,
            49: PlayerProfile.Rank.MASTER,
            50: PlayerProfile.Rank.LEGEND,
            74: PlayerProfile.Rank.LEGEND,
            75: PlayerProfile.Rank.MYTHIC,
        }
        for level, expected_rank in boundaries.items():
            with self.subTest(level=level):
                self.assertEqual(calculate_rank(level), expected_rank)

    def test_progression_functions_reject_invalid_values(self):
        for invalid_xp in (-1, 1.5, True):
            with self.subTest(xp=invalid_xp), self.assertRaises(ValueError):
                calculate_level(invalid_xp)
        with self.assertRaises(ValueError):
            calculate_xp_to_next_level(0)
        with self.assertRaises(ValueError):
            calculate_rank(0)


class GamificationServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.learning = TaskCategory.objects.create(name="Learning")
        self.personal = TaskCategory.objects.create(name="Personal")
        self.player = get_player_profile()
        self.task_number = 0

    def make_task(
        self,
        *,
        activity_date=None,
        category=None,
        difficulty=Task.Difficulty.NORMAL,
        xp_reward=25,
    ):
        self.task_number += 1
        activity_date = activity_date or self.today
        task = Task.objects.create(
            title=f"Mission {self.task_number}",
            category=category or self.personal,
            difficulty=difficulty,
            xp_reward=xp_reward,
            recurrence_type=Task.RecurrenceType.ONCE,
            start_date=activity_date,
        )
        generate_task_occurrences(activity_date)
        return task, TaskCompletion.objects.get(
            task=task,
            scheduled_date=activity_date,
        )

    def complete_on(self, activity_date, **task_options):
        task, occurrence = self.make_task(
            activity_date=activity_date,
            **task_options,
        )
        return task, complete_task_occurrence(occurrence.pk)

    def test_profile_is_a_single_default_player(self):
        second_lookup = get_player_profile()

        self.assertEqual(self.player.pk, second_lookup.pk)
        self.assertEqual(self.player.display_name, "Player One")
        self.assertEqual(self.player.total_xp, 0)
        self.assertEqual(self.player.current_level, 1)
        self.assertEqual(self.player.current_rank, PlayerProfile.Rank.BEGINNER)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlayerProfile.objects.create(display_name="Duplicate")

    def test_task_xp_is_awarded_once_reversed_once_and_can_be_earned_again(self):
        task, occurrence = self.make_task(xp_reward=10)

        first_completion = complete_task_occurrence(occurrence.pk)
        earned = XPTransaction.objects.get(
            task_completion=occurrence,
            completion_cycle=1,
            transaction_type=XPTransaction.Type.EARNED,
        )
        repeated_award = award_task_xp(occurrence.pk)
        repeated_completion = complete_task_occurrence(occurrence.pk)

        self.player.refresh_from_db()
        self.assertEqual(first_completion.xp_awarded, 10)
        self.assertEqual(repeated_award.pk, earned.pk)
        self.assertEqual(repeated_completion.completed_at, first_completion.completed_at)
        self.assertEqual(self.player.total_xp, 10)
        self.assertEqual(
            XPTransaction.objects.filter(
                task_completion=occurrence,
                transaction_type=XPTransaction.Type.EARNED,
            ).count(),
            1,
        )

        undone = undo_task_completion(occurrence.pk)
        self.player.refresh_from_db()
        reversal = XPTransaction.objects.get(
            task_completion=occurrence,
            completion_cycle=1,
            transaction_type=XPTransaction.Type.REVERSED,
        )
        self.assertEqual(reversal.amount, -10)
        self.assertEqual(undone.xp_awarded, 0)
        self.assertEqual(self.player.total_xp, 0)
        self.assertEqual(reverse_task_xp(occurrence.pk).pk, reversal.pk)
        undo_task_completion(occurrence.pk)
        self.assertEqual(
            XPTransaction.objects.filter(
                task_completion=occurrence,
                transaction_type=XPTransaction.Type.REVERSED,
            ).count(),
            1,
        )

        re_completed = complete_task_occurrence(occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(re_completed.completion_cycle, 2)
        self.assertEqual(re_completed.xp_awarded, 10)
        self.assertEqual(self.player.total_xp, 10)
        self.assertEqual(
            XPTransaction.objects.filter(
                task_completion=occurrence,
                transaction_type=XPTransaction.Type.EARNED,
            ).count(),
            2,
        )
        self.assertEqual(task.xp_reward, 10)

    def test_zero_xp_completion_and_reversal_are_audited(self):
        _, occurrence = self.make_task(xp_reward=0)

        complete_task_occurrence(occurrence.pk)
        undo_task_completion(occurrence.pk)

        self.player.refresh_from_db()
        self.assertEqual(self.player.total_xp, 0)
        self.assertEqual(
            list(
                XPTransaction.objects.filter(task_completion=occurrence)
                .order_by("transaction_type")
                .values_list("transaction_type", "amount")
            ),
            [("EARNED", 0), ("REVERSED", 0)],
        )

    def test_level_and_rank_recalculate_after_earning_and_reversal(self):
        _, occurrence = self.make_task(xp_reward=1000)

        complete_task_occurrence(occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.current_level, 5)
        self.assertEqual(self.player.current_rank, PlayerProfile.Rank.APPRENTICE)

        undo_task_completion(occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.total_xp, 0)
        self.assertEqual(self.player.current_level, 1)
        self.assertEqual(self.player.current_rank, PlayerProfile.Rank.BEGINNER)

    def test_bonus_xp_and_immutable_audit_history(self):
        bonus = award_bonus_xp(self.player, 40, "Manual milestone")
        self.player.refresh_from_db()

        self.assertEqual((bonus.amount, bonus.balance_after), (40, 40))
        self.assertEqual(self.player.current_level, 1)
        self.assertEqual(
            list(get_xp_history(self.player).values_list("pk", flat=True)),
            [bonus.pk],
        )
        with self.assertRaises(ValueError):
            award_bonus_xp(self.player, -1, "Invalid bonus")
        with self.assertRaises(ValidationError):
            bonus.save()
        with self.assertRaises(ValidationError):
            bonus.delete()

    def test_failed_xp_reversal_rolls_back_the_task_undo(self):
        _, occurrence = self.make_task(xp_reward=100)
        complete_task_occurrence(occurrence.pk)
        PlayerProfile.objects.filter(pk=self.player.pk).update(total_xp=0)

        with self.assertRaises(InsufficientXP):
            undo_task_completion(occurrence.pk)

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, TaskCompletion.Status.COMPLETED)
        self.assertFalse(
            XPTransaction.objects.filter(
                task_completion=occurrence,
                transaction_type=XPTransaction.Type.REVERSED,
            ).exists()
        )

    def test_first_mission_bonus_is_applied_once_and_achievement_survives_reversal(self):
        first_mission = Achievement.objects.get(code="FIRST_MISSION")
        first_mission.xp_reward = 30
        first_mission.save(update_fields=["xp_reward"])
        _, occurrence = self.make_task(xp_reward=10)

        complete_task_occurrence(occurrence.pk)
        check_achievements(self.player)
        self.player.refresh_from_db()
        unlocked = PlayerAchievement.objects.get(
            player=self.player,
            achievement=first_mission,
        )
        self.assertEqual((self.player.total_xp, unlocked.xp_awarded), (40, 30))
        self.assertEqual(
            XPTransaction.objects.filter(
                transaction_type=XPTransaction.Type.BONUS,
                description="Achievement unlocked: First Mission",
            ).count(),
            1,
        )

        undo_task_completion(occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.total_xp, 30)
        self.assertTrue(
            PlayerAchievement.objects.filter(
                player=self.player,
                achievement=first_mission,
            ).exists()
        )
        self.assertEqual(
            get_unlocked_achievements(self.player).filter(pk=first_mission.pk).count(),
            1,
        )
        self.assertFalse(
            get_locked_achievements(self.player).filter(pk=first_mission.pk).exists()
        )

    def test_xp_collector_uses_lifetime_earned_xp_and_is_not_removed_on_undo(self):
        collector = Achievement.objects.get(code="XP_COLLECTOR")
        collector.xp_reward = 40
        collector.save(update_fields=["xp_reward"])
        _, occurrence = self.make_task(xp_reward=1000)

        complete_task_occurrence(occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.total_xp, 1040)
        self.assertTrue(
            PlayerAchievement.objects.filter(
                player=self.player,
                achievement=collector,
                xp_awarded=40,
            ).exists()
        )
        undo_task_completion(occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.total_xp, 40)
        self.assertTrue(
            PlayerAchievement.objects.filter(
                player=self.player,
                achievement=collector,
            ).exists()
        )

    def test_bonus_xp_evaluates_achievements_without_reward_recursion(self):
        collector = Achievement.objects.get(code="XP_COLLECTOR")

        award_bonus_xp(self.player, 1000, "Milestone bonus")
        check_achievements(self.player)

        self.assertEqual(
            PlayerAchievement.objects.filter(
                player=self.player,
                achievement=collector,
            ).count(),
            1,
        )
        self.assertEqual(
            XPTransaction.objects.filter(
                transaction_type=XPTransaction.Type.BONUS,
                description="Achievement unlocked: XP Collector",
            ).count(),
            1,
        )
        self.player.refresh_from_db()
        self.assertEqual(self.player.total_xp, 1000)

    def test_mission_count_learning_and_difficulty_achievements(self):
        for index in range(50):
            if index < 10:
                options = {"difficulty": Task.Difficulty.HARD}
            elif index < 15:
                options = {"category": self.learning}
            else:
                options = {"category": self.personal}
            _, occurrence = self.make_task(xp_reward=0, **options)
            complete_task_occurrence(occurrence.pk)

        codes = set(
            get_unlocked_achievements(self.player).values_list("code", flat=True)
        )
        self.assertTrue(
            {
                "FIRST_MISSION",
                "TASK_MASTER",
                "LEARNING_STARTER",
                "HARD_WORKER",
            }.issubset(codes)
        )
        self.assertEqual(
            PlayerAchievement.objects.filter(
                player=self.player,
                achievement__code="TASK_MASTER",
            ).count(),
            1,
        )

    def test_streak_service_handles_consecutive_and_missed_days(self):
        self.complete_on(self.today - timedelta(days=2), xp_reward=0)
        self.complete_on(self.today - timedelta(days=1), xp_reward=0)
        self.complete_on(self.today, xp_reward=0)
        self.assertEqual(calculate_current_streak(self.player), 3)
        self.assertEqual(calculate_longest_streak(self.player), 3)

    def test_missed_calendar_day_breaks_the_current_streak(self):
        self.complete_on(
            self.today - timedelta(days=3),
            xp_reward=0,
        )
        self.complete_on(
            self.today - timedelta(days=1),
            xp_reward=0,
        )
        self.assertEqual(calculate_current_streak(self.player), 1)
        self.assertEqual(calculate_longest_streak(self.player), 1)

    def test_multiple_missions_and_undo_recalculate_a_day_without_losing_history(self):
        _, first = self.make_task(xp_reward=0)
        _, second = self.make_task(xp_reward=0)
        complete_task_occurrence(first.pk)
        complete_task_occurrence(second.pk)
        day = DailyStreak.objects.get(player=self.player, activity_date=self.today)
        self.assertEqual((day.qualifying_activity_count, day.is_active_day), (2, True))

        undo_task_completion(first.pk)
        day.refresh_from_db()
        self.assertEqual((day.qualifying_activity_count, day.is_active_day), (1, True))
        self.assertEqual(calculate_current_streak(self.player), 1)

        undo_task_completion(second.pk)
        day.refresh_from_db()
        self.assertEqual((day.qualifying_activity_count, day.is_active_day), (0, False))
        self.assertEqual(calculate_current_streak(self.player), 0)
        self.assertEqual(DailyStreak.objects.filter(pk=day.pk).count(), 1)

    def test_future_activity_is_never_recorded_as_a_streak_day(self):
        future = self.today + timedelta(days=1)
        _, occurrence = self.make_task(activity_date=future, xp_reward=0)

        complete_task_occurrence(occurrence.pk)

        self.assertFalse(
            DailyStreak.objects.filter(player=self.player, activity_date=future).exists()
        )
        self.assertEqual(calculate_current_streak(self.player), 0)
        self.assertIsNone(record_daily_activity(self.player, future))

    def test_longest_streak_is_preserved_and_consistency_achievements_unlock(self):
        completed_occurrence = None
        for offset in range(29, -1, -1):
            _, completed_occurrence = self.complete_on(
                self.today - timedelta(days=offset),
                xp_reward=0,
            )

        self.player.refresh_from_db()
        codes = set(
            get_unlocked_achievements(self.player).values_list("code", flat=True)
        )
        self.assertEqual(self.player.longest_streak, 30)
        self.assertTrue({"CONSISTENCY_7", "CONSISTENCY_30"}.issubset(codes))

        undo_task_completion(completed_occurrence.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.longest_streak, 30)
        self.assertEqual(calculate_current_streak(self.player), 29)
        self.assertTrue(
            get_unlocked_achievements(self.player)
            .filter(code="CONSISTENCY_30")
            .exists()
        )

    def test_player_progress_uses_database_values(self):
        self.player.display_name = "Ranger"
        self.player.save(update_fields=["display_name", "updated_at"])
        award_bonus_xp(self.player, 99, "Test progress")
        _, _ = self.complete_on(self.today, xp_reward=0)

        progress = get_player_progress()

        self.assertEqual(progress["display_name"], "Ranger")
        self.assertEqual(progress["total_xp"], 99)
        self.assertEqual(progress["current_level"], 1)
        self.assertEqual(progress["xp_remaining"], 1)
        self.assertEqual(progress["total_completed_missions"], 1)
        self.assertEqual(progress["current_streak"], 1)
        self.assertEqual(progress["unlocked_achievement_count"], 1)
        self.assertEqual(progress["learning_completed_missions"], 0)
