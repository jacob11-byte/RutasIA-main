"""Deployment checks required by the final project's risk analysis."""
import os

from django.conf import settings
from django.core.checks import Error, register


@register(deploy=True)
def production_configuration(app_configs, **kwargs):
    errors = []
    required = ("SECRET_KEY", "DATABASE_URL", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS")
    if settings.DEBUG:
        errors.append(Error("DEBUG debe ser False en produccion.", id="logistics.E001"))
    for key in required:
        if not os.getenv(key):
            errors.append(Error(f"Configura {key} explicitamente antes de desplegar.", id="logistics.E002"))
    if settings.SECRET_KEY.startswith("django-insecure-") or len(settings.SECRET_KEY) < 50:
        errors.append(Error("La SECRET_KEY de desarrollo no es valida para produccion.", id="logistics.E003"))
    if any(host == "*" or host.startswith(".") for host in settings.ALLOWED_HOSTS):
        errors.append(Error("Utiliza hosts de produccion explicitos, sin comodines.", id="logistics.E004"))
    return errors
