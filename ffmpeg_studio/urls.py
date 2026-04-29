from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls), 
    path("", include("api.urls")),
] + static("uploads", document_root=settings.UPLOAD_DIR) \
  + static("outputs", document_root=settings.OUTPUT_DIR)