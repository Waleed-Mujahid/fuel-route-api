from django.http import JsonResponse


def healthz(request):
    """Liveness probe used by Docker/CI; touches no database or network."""
    return JsonResponse({'status': 'ok'})
