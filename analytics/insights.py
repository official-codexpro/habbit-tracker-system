def _insight(
    insight_type,
    title,
    description,
    priority,
    metric,
    period,
):
    return {
        "type": insight_type,
        "title": title,
        "description": description,
        "priority": priority,
        "metric": metric,
        "period": period,
    }


def generate_insights(dashboard):
    overview = dashboard["overview"]
    weekly = dashboard["comparisons"]["week"]
    categories = dashboard["categories"]
    insights = []

    if not overview["data_available"]:
        return [
            _insight(
                "INSUFFICIENT_DATA",
                "Your analytics journey starts here",
                "No mission occurrences or XP ledger activity are recorded yet, so trends are not available.",
                "LOW",
                {"name": "recorded_missions", "value": 0, "unit": "missions"},
                "all_time",
            )
        ]

    if weekly["available"]:
        completion_change = weekly["changes"]["completion_rate_points"]
        if completion_change is not None and completion_change > 0:
            insights.append(
                _insight(
                    "PRODUCTIVITY",
                    "Mission completion rate improved",
                    f"Your completion rate is up {completion_change:g} percentage points compared with the previous matching week-to-date period.",
                    "MEDIUM",
                    {
                        "name": "completion_rate",
                        "value": weekly["current"]["completion_rate"],
                        "unit": "percent",
                        "change": completion_change,
                        "change_unit": "percentage_points",
                    },
                    "week_to_date",
                )
            )
        elif completion_change is not None and completion_change < 0:
            insights.append(
                _insight(
                    "WARNING",
                    "Mission completion rate dipped",
                    f"Your completion rate is down {abs(completion_change):g} percentage points compared with the previous matching week-to-date period.",
                    "MEDIUM",
                    {
                        "name": "completion_rate",
                        "value": weekly["current"]["completion_rate"],
                        "unit": "percent",
                        "change": completion_change,
                        "change_unit": "percentage_points",
                    },
                    "week_to_date",
                )
            )

        consistency_change = weekly["changes"]["consistency_points"]
        if consistency_change is not None and consistency_change > 0:
            insights.append(
                _insight(
                    "CONSISTENCY",
                    "More active days were recorded",
                    f"Your active-day rate is up {consistency_change:g} percentage points compared with the previous matching week-to-date period.",
                    "LOW",
                    {
                        "name": "consistency_rate",
                        "value": weekly["current"]["consistency_rate"],
                        "unit": "percent",
                        "change": consistency_change,
                        "change_unit": "percentage_points",
                    },
                    "week_to_date",
                )
            )
        elif consistency_change is not None and consistency_change < 0:
            insights.append(
                _insight(
                    "CONSISTENCY",
                    "Fewer active days were recorded",
                    f"Your active-day rate is down {abs(consistency_change):g} percentage points compared with the previous matching week-to-date period.",
                    "LOW",
                    {
                        "name": "consistency_rate",
                        "value": weekly["current"]["consistency_rate"],
                        "unit": "percent",
                        "change": consistency_change,
                        "change_unit": "percentage_points",
                    },
                    "week_to_date",
                )
            )

        xp_change = weekly["changes"]["xp_net"]
        if xp_change is not None and xp_change > 0:
            insights.append(
                _insight(
                    "XP",
                    "Your XP balance gained ground",
                    f"The XP ledger recorded a net gain of {xp_change} XP compared with the previous matching week-to-date period.",
                    "LOW",
                    {"name": "net_xp", "value": xp_change, "unit": "XP"},
                    "week_to_date",
                )
            )

    active_categories = [
        item
        for item in categories["categories"]
        if item["scheduled_missions"] > 0
    ]
    if len(active_categories) > 1:
        strongest = categories["strongest_category"]
        if strongest is not None and strongest["completion_rate"] is not None:
            insights.append(
                _insight(
                    "CATEGORY",
                    f"{strongest['category']} is your strongest questline",
                    f"This category has your highest recorded mission completion rate at {strongest['completion_rate']:g}%.",
                    "LOW",
                    {
                        "name": "category_completion_rate",
                        "value": strongest["completion_rate"],
                        "unit": "percent",
                        "category": strongest["category"],
                    },
                    "all_time",
                )
            )

    if overview["pending_missions"] > 0:
        insights.append(
            _insight(
                "RECOMMENDATION",
                "Pending missions are on your board",
                f"There are {overview['pending_missions']} recorded pending missions. Choose one to move your journey forward.",
                "LOW",
                {
                    "name": "pending_missions",
                    "value": overview["pending_missions"],
                    "unit": "missions",
                },
                "all_time",
            )
        )

    if not weekly["previous_period_available"]:
        insights.append(
            _insight(
                "INSUFFICIENT_DATA",
                "More history unlocks comparisons",
                "The previous matching week has no recorded mission or XP activity, so week-over-week change is unavailable.",
                "LOW",
                {"name": "previous_period", "value": None, "unit": "unavailable"},
                "week_to_date",
            )
        )

    return insights
