from .services import get_player_progress


def player_progress(request):
    match = request.resolver_match
    if match is None or match.app_name not in {"dashboard", "tasks", "learning", "analytics"}:
        return {}
    return {"player_progress": get_player_progress()}
