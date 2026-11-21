from django.db import migrations


ACHIEVEMENTS = [
    {
        "code": "FIRST_MISSION",
        "name": "First Mission",
        "description": "Complete your first eligible mission.",
        "icon": "spark",
        "category": "MISSIONS",
        "condition_type": "TASK_COUNT",
        "condition_value": 1,
    },
    {
        "code": "TASK_MASTER",
        "name": "Task Master",
        "description": "Complete 50 eligible missions.",
        "icon": "check-list",
        "category": "MISSIONS",
        "condition_type": "TASK_COUNT",
        "condition_value": 50,
    },
    {
        "code": "CONSISTENCY_7",
        "name": "Consistency 7",
        "description": "Build a seven-day consecutive mission streak.",
        "icon": "calendar",
        "category": "CONSISTENCY",
        "condition_type": "STREAK",
        "condition_value": 7,
    },
    {
        "code": "CONSISTENCY_30",
        "name": "Consistency 30",
        "description": "Build a thirty-day consecutive mission streak.",
        "icon": "calendar-star",
        "category": "CONSISTENCY",
        "condition_type": "STREAK",
        "condition_value": 30,
    },
    {
        "code": "LEARNING_STARTER",
        "name": "Learning Starter",
        "description": "Complete five missions in the Learning category.",
        "icon": "book",
        "category": "LEARNING",
        "condition_type": "LEARNING_COUNT",
        "condition_value": 5,
    },
    {
        "code": "HARD_WORKER",
        "name": "Hard Worker",
        "description": "Complete ten Hard or Extreme missions.",
        "icon": "flame",
        "category": "MISSIONS",
        "condition_type": "HARD_TASK_COUNT",
        "condition_value": 10,
    },
    {
        "code": "XP_COLLECTOR",
        "name": "XP Collector",
        "description": "Earn 1,000 lifetime XP.",
        "icon": "trophy",
        "category": "PROGRESSION",
        "condition_type": "LIFETIME_XP",
        "condition_value": 1000,
    },
]


def seed_achievements(apps, schema_editor):
    Achievement = apps.get_model("gamification", "Achievement")
    for values in ACHIEVEMENTS:
        Achievement.objects.get_or_create(code=values["code"], defaults=values)


class Migration(migrations.Migration):

    dependencies = [
        ("gamification", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_achievements, migrations.RunPython.noop),
    ]
