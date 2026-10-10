"""
URL configuration for flamia project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse
from django.urls import include, path


def service_worker(request):
    response = FileResponse(
        open(settings.BASE_DIR / "static" / "service-worker.js", "rb"),
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache"
    return response


def manifest(request):
    response = FileResponse(
        open(settings.BASE_DIR / "static" / "manifest.json", "rb"),
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "no-cache"
    return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("manifest.json", manifest, name="manifest"),
    path("service-worker.js", service_worker, name="service-worker"),
    path("", include("logistics.urls")),
]

if settings.STATICFILES_DIRS:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
