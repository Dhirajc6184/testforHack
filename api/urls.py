from django.urls import path
from django.http import JsonResponse
from . import views

from django.http import HttpResponse

def root_view(request):
    html = """
    <html>
    <head><title>FFmpeg Studio API</title></head>
    <body style="font-family:sans-serif; padding:40px; background:#111; color:#fff;">
        <h1>🎬 FFmpeg Studio API</h1>
        <p>Status: <span style="color:lime">● Running</span></p>
        <h3>Endpoints</h3>
        <ul>
            <li>POST /auth/register</li>
            <li>POST /auth/login</li>
            <li>POST /upload</li>
            <li>POST /process</li>
            <li>GET  /health</li>
        </ul>
    </body>
    </html>
    """
    return HttpResponse(html)

urlpatterns = [
    path('', root_view),  # ← add this

    # Auth
    path("auth/register", views.register),
    path("auth/login",    views.login),
    path("auth/me",       views.me),
    # Video
    path("upload",        views.upload_video),
    path("process",       views.process_video),
    # Health
    path("health",        views.health),
    # Comments
    path("comments/<str:output_filename>/",                  views.comments),
    path("comments/<str:output_filename>/<int:comment_id>/", views.comment_detail),
    # Scene Extract
    path("scene-extract/",              views.scene_extract),
    path("scene-extract/<str:job_id>/", views.scene_extract_status),
    # Captions
    path("captions/generate/",         views.generate_captions),
    path("captions/<str:job_id>/",     views.caption_status),
]