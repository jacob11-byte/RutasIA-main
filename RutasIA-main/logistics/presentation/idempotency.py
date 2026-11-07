"""Persist mutation results so a lost HTTP response can be safely retried."""
import hashlib
import uuid
from functools import wraps

from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse

from logistics.models import MutationReceipt


def idempotent(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key")
        if request.method != "POST":
            return view(request, *args, **kwargs)
        if not key:
            with transaction.atomic():
                response = view(request, *args, **kwargs)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
                return response
        try:
            key = uuid.UUID(key)
        except (ValueError, TypeError):
            return JsonResponse({"ok": False, "error": "Identificador de operacion invalido."}, status=400)
        fingerprint = hashlib.sha256(request.path.encode() + b"\0" + request.body).hexdigest()
        with transaction.atomic():
            # Serializes simultaneous replays even before the first receipt exists.
            User.objects.select_for_update().get(pk=request.user.pk)
            receipt = MutationReceipt.objects.filter(user=request.user, key=key).first()
            if receipt:
                if receipt.fingerprint != fingerprint:
                    return JsonResponse({"ok": False, "error": "El identificador pertenece a otra operacion."}, status=409)
                return JsonResponse(receipt.response, status=receipt.status_code)
            # Roll back partial creates when a view catches a validation exception.
            with transaction.atomic():
                response = view(request, *args, **kwargs)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
            if 200 <= response.status_code < 300:
                import json
                MutationReceipt.objects.create(
                    user=request.user, key=key, fingerprint=fingerprint,
                    response=json.loads(response.content), status_code=response.status_code,
                )
            return response
    return wrapped
