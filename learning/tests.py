from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gamification.models import XPTransaction
from tasks.models import TaskCompletion

from .models import (
    LearningCourse,
    LearningGoal,
    LearningSession,
    LearningTopic,
    Skill,
)
from .services import (
    learning_history,
    reorder_topic,
    set_course_status,
    set_goal_status,
    set_skill_proficiency,
    set_topic_status,
)


class LearningModelTests(TestCase):
    def setUp(self):
        self.goal = LearningGoal.objects.create(title="Master Django")
        self.skill = Skill.objects.create(name="Django")
        self.skill.learning_goals.set([self.goal])

    def test_goal_creation_status_priority_and_completion(self):
        goal = LearningGoal.objects.create(
            title="Learn databases",
            status=LearningGoal.Status.PAUSED,
            priority=4,
        )
        self.assertEqual(goal.status, "PAUSED")
        self.assertEqual(goal.priority, 4)
        updated = set_goal_status(goal.pk, LearningGoal.Status.COMPLETED)
        self.assertEqual(updated.status, "COMPLETED")

    def test_goal_archiving_preserves_history(self):
        LearningSession.objects.create(
            learning_goal=self.goal,
            title="Study Django",
            duration_minutes=30,
        )
        archived = set_goal_status(self.goal.pk, LearningGoal.Status.ARCHIVED)
        self.assertEqual(archived.status, "ARCHIVED")
        self.assertEqual(LearningSession.objects.filter(learning_goal=self.goal).count(), 1)

    def test_skill_creation_and_manual_proficiency_updates(self):
        skill = set_skill_proficiency(self.skill.pk, current=3, target=5)
        self.assertEqual(skill.current_proficiency, 3)
        self.assertEqual(skill.target_proficiency, 5)
        with self.assertRaises(ValueError):
            set_skill_proficiency(skill.pk, current=6)

    def test_proficiency_validation_rejects_out_of_range_values(self):
        skill = Skill(name="Python", current_proficiency=6)
        with self.assertRaises(ValidationError):
            skill.full_clean()

    def test_course_topic_creation_progress_and_completion(self):
        course = LearningCourse.objects.create(
            title="Django Fundamentals",
            skill=self.skill,
            learning_goal=self.goal,
            total_topics=3,
        )
        one = LearningTopic.objects.create(course=course, title="Models", position=1)
        LearningTopic.objects.create(course=course, title="Views", position=2)
        LearningTopic.objects.create(course=course, title="Templates", position=3)
        course.refresh_from_db()
        self.assertEqual(course.progress_percentage, 0)

        topic = set_topic_status(one.pk, LearningTopic.Status.COMPLETED)
        course.refresh_from_db()
        self.assertEqual(topic.status, "COMPLETED")
        self.assertEqual(topic.completion_date, timezone.localdate())
        self.assertEqual(course.completed_topics, 1)
        self.assertEqual(course.progress_percentage, 33.3)

    def test_topic_reopening_and_reordering_preserve_history(self):
        course = LearningCourse.objects.create(title="Python", total_topics=2)
        one = LearningTopic.objects.create(course=course, title="One", position=1)
        two = LearningTopic.objects.create(course=course, title="Two", position=2)
        set_topic_status(one.pk, LearningTopic.Status.COMPLETED)
        reopened = set_topic_status(one.pk, LearningTopic.Status.NOT_STARTED)
        course.refresh_from_db()
        self.assertIsNone(reopened.completion_date)
        self.assertEqual(course.completed_topics, 0)
        reorder_topic(two.pk, 1)
        one.refresh_from_db()
        two.refresh_from_db()
        self.assertEqual(two.position, 1)
        self.assertEqual(one.position, 2)

    def test_empty_course_progress_is_unavailable(self):
        course = LearningCourse.objects.create(title="No topics")
        self.assertFalse(course.has_topic_progress)
        self.assertIsNone(course.progress_percentage)

    def test_course_status_actions(self):
        course = LearningCourse.objects.create(title="Database Design")
        paused = set_course_status(course.pk, LearningCourse.Status.PAUSED)
        resumed = set_course_status(course.pk, LearningCourse.Status.IN_PROGRESS)
        completed = set_course_status(course.pk, LearningCourse.Status.COMPLETED)
        self.assertEqual(paused.status, "PAUSED")
        self.assertEqual(resumed.status, "IN_PROGRESS")
        self.assertEqual(completed.status, "COMPLETED")

    def test_session_creation_duration_and_future_validation(self):
        session = LearningSession.objects.create(
            skill=self.skill,
            learning_goal=self.goal,
            title="Independent practice",
            duration_minutes=45,
            session_date=timezone.localdate(),
        )
        self.assertEqual(session.duration_minutes, 45)
        invalid = LearningSession(
            title="Future study",
            duration_minutes=1,
            session_date=timezone.localdate() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()
        with self.assertRaises(ValidationError):
            LearningSession(
                title="Invalid duration",
                duration_minutes=0,
                session_date=timezone.localdate(),
            ).full_clean()

    def test_learning_session_does_not_change_tasks_or_award_xp(self):
        before_xp = XPTransaction.objects.count()
        before_occurrences = TaskCompletion.objects.count()
        LearningSession.objects.create(
            title="Read documentation",
            duration_minutes=20,
        )
        self.assertEqual(XPTransaction.objects.count(), before_xp)
        self.assertEqual(TaskCompletion.objects.count(), before_occurrences)

    def test_history_reports_actual_minutes_and_filters(self):
        today = timezone.localdate()
        course = LearningCourse.objects.create(title="Python")
        LearningSession.objects.create(
            course=course,
            skill=self.skill,
            title="Python work",
            duration_minutes=30,
            session_date=today,
        )
        LearningSession.objects.create(
            skill=self.skill,
            title="Python practice",
            duration_minutes=90,
            session_date=today - timedelta(days=2),
        )
        report = learning_history(
            today - timedelta(days=6),
            today,
            course_id=course.pk,
        )
        self.assertEqual(report["total_minutes"], 30)
        self.assertEqual(report["session_count"], 1)
        self.assertEqual(report["average_minutes"], 30)
        report = learning_history(
            today - timedelta(days=6),
            today,
            skill_id=self.skill.pk,
        )
        self.assertEqual(report["total_minutes"], 120)
        self.assertEqual(report["session_count"], 2)
        self.assertEqual(report["active_day_count"], 2)


class LearningViewTests(TestCase):
    def setUp(self):
        self.goal = LearningGoal.objects.create(title="Learn Python")
        self.skill = Skill.objects.create(name="Python")
        self.course = LearningCourse.objects.create(
            title="Python Fundamentals",
            skill=self.skill,
            learning_goal=self.goal,
            total_topics=2,
        )

    def test_learning_dashboard_and_history_pages_load(self):
        dashboard = self.client.get(reverse("learning:dashboard"))
        history = self.client.get(reverse("learning:history"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "LEARNING COMMAND")
        self.assertContains(dashboard, "Learn Python")
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, "LEARNING HISTORY")

    def test_goal_api_creation_status_and_detail_update(self):
        create = self.client.post(
            reverse("learning:goals_api"),
            data={
                "title": "Learn Django",
                "description": "Study web development",
                "priority": 3,
                "status": "ACTIVE",
                "target_date": "",
            },
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 201)
        goal_id = create.json()["goal"]["id"]
        pause = self.client.post(
            reverse("learning:goal_status_api", kwargs={"goal_id": goal_id, "action": "pause"})
        )
        self.assertEqual(pause.status_code, 200)
        self.assertEqual(pause.json()["goal"]["status"], "PAUSED")
        update = self.client.post(
            reverse("learning:goal_detail_api", kwargs={"goal_id": goal_id}),
            data={"title": "Learn Django deeply", "description": "", "priority": 4, "status": "ACTIVE", "target_date": ""},
            content_type="application/json",
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["goal"]["title"], "Learn Django deeply")

    def test_skill_api_proficiency_validation_and_update(self):
        create = self.client.post(
            reverse("learning:skills_api"),
            data={"name": "SQL", "description": "", "category": "Database", "learning_goals": [self.goal.pk], "current_proficiency": 1, "target_proficiency": 4, "status": "ACTIVE"},
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 201)
        skill_id = create.json()["skill"]["id"]
        invalid = self.client.post(
            reverse("learning:skill_proficiency_api", kwargs={"skill_id": skill_id}),
            data={"current_proficiency": 9, "target_proficiency": 5},
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)
        valid = self.client.post(
            reverse("learning:skill_proficiency_api", kwargs={"skill_id": skill_id}),
            data={"current_proficiency": 3, "target_proficiency": 5},
            content_type="application/json",
        )
        self.assertEqual(valid.status_code, 200)

    def test_course_topic_and_session_apis(self):
        course_create = self.client.post(
            reverse("learning:courses_api"),
            data={"title": "JavaScript", "description": "", "skill": self.skill.pk, "learning_goal": self.goal.pk, "provider": "", "resource_url": "", "total_topics": 2, "completed_topics": 0, "status": "NOT_STARTED", "start_date": timezone.localdate().isoformat(), "target_completion_date": ""},
            content_type="application/json",
        )
        self.assertEqual(course_create.status_code, 201)
        course_id = course_create.json()["course"]["id"]
        topic_create = self.client.post(
            reverse("learning:topics_api", kwargs={"course_id": course_id}),
            data={"title": "Variables", "description": "", "position": 1, "status": "NOT_STARTED", "completion_date": ""},
            content_type="application/json",
        )
        self.assertEqual(topic_create.status_code, 201)
        topic_id = topic_create.json()["topic"]["id"]
        completed = self.client.post(
            reverse("learning:topic_status_api", kwargs={"topic_id": topic_id, "action": "complete"})
        )
        self.assertEqual(completed.status_code, 200)
        reopened = self.client.post(
            reverse("learning:topic_status_api", kwargs={"topic_id": topic_id, "action": "reopen"})
        )
        self.assertEqual(reopened.status_code, 200)

        session_create = self.client.post(
            reverse("learning:sessions_api"),
            data={"course": course_id, "skill": self.skill.pk, "learning_goal": self.goal.pk, "title": "Practice JavaScript", "topics_covered": "Variables", "notes": "", "duration_minutes": 35, "session_date": timezone.localdate().isoformat()},
            content_type="application/json",
        )
        self.assertEqual(session_create.status_code, 201)
        session_id = session_create.json()["session"]["id"]
        edited = self.client.post(
            reverse("learning:session_detail_api", kwargs={"session_id": session_id}),
            data={"course": course_id, "skill": self.skill.pk, "learning_goal": self.goal.pk, "title": "Practice JavaScript edited", "topics_covered": "Variables", "notes": "Notes", "duration_minutes": 40, "session_date": timezone.localdate().isoformat()},
            content_type="application/json",
        )
        self.assertEqual(edited.status_code, 200)
        deleted = self.client.delete(reverse("learning:session_detail_api", kwargs={"session_id": session_id}))
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(LearningSession.objects.filter(pk=session_id).exists())

    def test_session_api_rejects_future_date_zero_duration_and_invalid_filters(self):
        future = self.client.post(
            reverse("learning:sessions_api"),
            data={"title": "Future", "duration_minutes": 10, "session_date": (timezone.localdate() + timedelta(days=1)).isoformat()},
            content_type="application/json",
        )
        zero = self.client.post(
            reverse("learning:sessions_api"),
            data={"title": "Zero", "duration_minutes": 0, "session_date": timezone.localdate().isoformat()},
            content_type="application/json",
        )
        invalid_course = self.client.get(reverse("learning:sessions_api"), {"course": "abc"})
        invalid_range = self.client.get(reverse("learning:history_api"), {"range": "forever"})
        self.assertEqual(future.status_code, 400)
        self.assertEqual(zero.status_code, 400)
        self.assertEqual(invalid_course.status_code, 400)
        self.assertEqual(invalid_range.status_code, 400)

    def test_history_api_and_analytics_integration_use_saved_sessions(self):
        LearningSession.objects.create(
            course=self.course,
            skill=self.skill,
            learning_goal=self.goal,
            title="Weekly study",
            duration_minutes=60,
            session_date=timezone.localdate(),
        )
        history = self.client.get(reverse("learning:history_api"), {"range": "7"})
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["total_minutes"], 60)
        self.assertEqual(history.json()["session_count"], 1)
        analytics = self.client.get(reverse("analytics:dashboard_api"))
        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(analytics.json()["learning"]["total_minutes"], 60)
        learning_api = self.client.get(reverse("analytics:learning_api"))
        self.assertEqual(learning_api.status_code, 200)
        self.assertEqual(learning_api.json()["session_count"], 1)
