from django.http import JsonResponse


class ApiSessionMiddleware:
    """Do not serve another account's API to an already-open offline workspace."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "error": "Tu sesion vencio. Inicia sesion para sincronizar."}, status=401)
        expected = request.headers.get("X-Flamia-User-ID")
        if expected and expected != str(request.user.pk):
            return JsonResponse({"ok": False, "error": "La sesion cambio de cuenta. Recarga la pagina antes de continuar."}, status=409)
        response = self.get_response(request)
        response["X-Flamia-User-ID"] = str(request.user.pk)
        response["Cache-Control"] = "no-store, private"
        return response
