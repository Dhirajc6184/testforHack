import os
import uuid
import subprocess
import shutil
import json
from pathlib import Path
import threading
import numpy as np
import cv2
import tempfile

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .authentication import (
    create_token, get_user, load_users, save_users, JWTAuthentication
)

ph = PasswordHasher()

# ── Helpers ────────────────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    try:
        ph.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False


# ── FFmpeg builder ─────────────────────────────────────────────────────────────

def build_ffmpeg_command(input_path: str, output_path: str, operations: list):
    cmd = ["ffmpeg", "-y"]

    for op in operations:
        if op["id"] == "trim":
            if op["vals"].get("start"):
                cmd += ["-ss", op["vals"]["start"]]
            if op["vals"].get("end"):
                cmd += ["-to", op["vals"]["end"]]

    cmd += ["-i", input_path]

    vfilters, afilters, extra = [], [], []
    has_audio = True

    for op in operations:
        op_id = op["id"]
        vals = op.get("vals", {})

        if op_id == "resize":
            vfilters.append(f"scale={vals.get('width', 1280)}:{vals.get('height', -1)}")
        elif op_id == "crop":
            vfilters.append(f"crop={vals.get('w', 720)}:{vals.get('h', 1280)}:{vals.get('x', 0)}:{vals.get('y', 0)}")
        elif op_id == "text":
            text = str(vals.get("text", "Hello")).replace("'", "\\'")
            enable_start = vals.get("_enableStart")
            enable_end   = vals.get("_enableEnd")
            enable_clause = ""
            if enable_start is not None and enable_end is not None:
                enable_clause = f":enable='between(t,{enable_start},{enable_end})'"
            vfilters.append(
                f"drawtext=text='{text}':x={vals.get('x', 50)}:y={vals.get('y', 50)}"
                f":fontsize={vals.get('size', 40)}:fontcolor={vals.get('color', 'white')}"
                f":box=1:boxcolor=black@0.4:boxborderw=5{enable_clause}"
            )
        elif op_id == "speed":
            f = float(vals.get("factor", 2.0))
            vfilters.append(f"setpts={round(1.0 / f, 4)}*PTS")
            if f != 1.0:
                afilters.append(f"atempo={min(max(f, 0.5), 2.0)}")
        elif op_id == "grayscale":
            vfilters.append("hue=s=0")
        elif op_id == "blur":
            vfilters.append(f"boxblur={vals.get('amount', 10)}")
        elif op_id == "brightness":
            vfilters.append(
                f"eq=brightness={vals.get('brightness', 0.1)}:contrast={vals.get('contrast', 1.0)}"
            )
        elif op_id == "rotate":
            m = {"90": "1", "180": "2,transpose=2", "270": "2"}
            vfilters.append(f"transpose={m.get(str(vals.get('degrees', '90')), '1')}")
        elif op_id == "audio":
            has_audio = False
        elif op_id == "volume":
            afilters.append(f"volume={vals.get('level', 2.0)}")
        elif op_id == "compress":
            extra += ["-vcodec", "libx264", "-crf", str(vals.get("crf", 28)), "-preset", "fast"]

    if vfilters:
        cmd += ["-vf", ",".join(vfilters)]
    if afilters and has_audio:
        cmd += ["-af", ",".join(afilters)]
    if not has_audio:
        cmd += ["-an"]
    cmd += extra
    cmd.append(output_path)
    return cmd


# ── Auth views ─────────────────────────────────────────────────────────────────

@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get("username", "").strip()
    password = request.data.get("password", "")
    role     = request.data.get("role", "viewer")
    if role not in ("editor", "viewer"):
        role = "viewer"

    if len(username) < 3:
        return Response(
            {"detail": "Username must be at least 3 characters"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(password) < 6:
        return Response(
            {"detail": "Password must be at least 6 characters"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    users = load_users()
    if username in users:
        return Response(
            {"detail": "Username already taken"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    users[username] = {
        "username": username,
        "hashed_password": ph.hash(password),
        "role": role,
    }
    save_users(users)
    return Response({"message": "Account created successfully"})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    # Support both form-encoded (OAuth2 style) and JSON
    if request.content_type and "application/x-www-form-urlencoded" in request.content_type:
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
    else:
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

    user = get_user(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return Response(
            {"detail": "Incorrect username or password"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_token(username)
    return Response({"access_token": token, "token_type": "bearer"})


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def me(request):
    user_data = get_user(request.user.username) or {}
    return Response({
        "username": request.user.username,
        "role": getattr(request.user, "role", user_data.get("role", "viewer")),
    })


# ── Video views ────────────────────────────────────────────────────────────────

@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_video(request):
    file = request.FILES.get("file")
    if not file:
        return Response({"detail": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

    ext = Path(file.name).suffix.lower()
    if ext not in [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"]:
        return Response({"detail": "Unsupported file type"}, status=status.HTTP_400_BAD_REQUEST)

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / safe_name

    with open(dest, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

    # Probe video metadata
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(dest)],
        capture_output=True, text=True,
    )
    duration = width = height = None
    size_mb = round(dest.stat().st_size / (1024 * 1024), 2)

    if probe.returncode == 0:
        info = json.loads(probe.stdout)
        duration = round(float(info.get("format", {}).get("duration", 0)), 2)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                width, height = s.get("width"), s.get("height")
                break

    return Response({
        "filename": safe_name,
        "original_name": file.name,
        "duration": duration,
        "width": width,
        "height": height,
        "size_mb": size_mb,
    })


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def process_video(request):
    input_filename = request.data.get("input_filename")
    output_filename = request.data.get("output_filename")
    operations = request.data.get("operations", [])

    if not input_filename:
        return Response({"detail": "input_filename is required"}, status=status.HTTP_400_BAD_REQUEST)

    input_path = settings.UPLOAD_DIR / input_filename
    if not input_path.exists():
        return Response({"detail": "Input file not found"}, status=status.HTTP_404_NOT_FOUND)

    out_name = output_filename or f"output_{uuid.uuid4().hex[:8]}.mp4"
    if not out_name.endswith(".mp4"):
        out_name += ".mp4"
    output_path = settings.OUTPUT_DIR / out_name

    cmd = build_ffmpeg_command(str(input_path), str(output_path), operations)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return Response(
            {"detail": f"FFmpeg error: {result.stderr[-800:]}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({
        "output_filename": out_name,
        "output_url": f"/outputs/{out_name}",
        "command": " ".join(cmd),
        "size_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
    })


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def serve_upload(request, filename):
    """Serve uploaded/output files with CORS headers so canvas thumbnail capture works."""
    from django.http import FileResponse, Http404
    # Try uploads dir first, then outputs dir
    for base_dir in [settings.UPLOAD_DIR, settings.OUTPUT_DIR]:
        path = base_dir / filename
        if path.exists():
            response = FileResponse(open(path, "rb"))
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            return response
    raise Http404


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    return Response({
        "status": "ok",
        "ffmpeg": shutil.which("ffmpeg") is not None,
    })


# ── /comments ──────────────────────────────────────────────────────────────────

from rest_framework import serializers as drf_serializers
from .models import VideoComment


class _CommentInSerializer(drf_serializers.Serializer):
    timestamp_sec = drf_serializers.FloatField(min_value=0)
    text          = drf_serializers.CharField(min_length=1, max_length=2000)


def _comment_to_dict(c):
    return {
        "id":              c.id,
        "output_filename": c.output_filename,
        "author":          c.author_username,
        "author_role":     c.author_role,
        "timestamp_sec":   c.timestamp_sec,
        "text":            c.text,
        "created_at":      c.created_at.isoformat(),
    }


@api_view(["GET", "POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def comments(request, output_filename):
    """
    GET  /comments/<output_filename>/  → list all comments for a video
    POST /comments/<output_filename>/  → add a comment
    """
    if request.method == "GET":
        qs = VideoComment.objects.filter(output_filename=output_filename)
        return Response([_comment_to_dict(c) for c in qs])

    # POST
    _user_data = get_user(request.user.username) or {}
    role = getattr(request.user, "role", _user_data.get("role", "viewer"))
    if role != "viewer":
        return Response({"detail": "Only viewers can post comments."}, status=status.HTTP_403_FORBIDDEN)

    serializer = _CommentInSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    _user_data = get_user(user.username) or {}
    role = getattr(user, "role", _user_data.get("role", "viewer"))

    comment = VideoComment.objects.create(
        output_filename=output_filename,
        author_username=user.username,
        author_role=role,
        timestamp_sec=serializer.validated_data["timestamp_sec"],
        text=serializer.validated_data["text"],
    )
    return Response(_comment_to_dict(comment), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def comment_detail(request, output_filename, comment_id):
    """
    DELETE /comments/<output_filename>/<comment_id>/
    - Editors can delete any comment.
    - Viewers can only delete their own.
    """
    try:
        comment = VideoComment.objects.get(id=comment_id, output_filename=output_filename)
    except VideoComment.DoesNotExist:
        return Response({"detail": "Comment not found"}, status=status.HTTP_404_NOT_FOUND)

    user = request.user
    _user_data = get_user(user.username) or {}
    role = getattr(user, "role", _user_data.get("role", "viewer"))

    if role == "editor" or comment.author_username == user.username:
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    return Response(
        {"detail": "Viewers can only delete their own comments"},
        status=status.HTTP_403_FORBIDDEN,
    )
# ── Scene Extraction ──────────────────────────────────────────────────────────

SCENE_JOBS = {}
NUM_SCENES = 3
MAX_PCT    = 50

def _fmt_time(seconds):
    seconds = int(round(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def _analyse_video(job_id, filepath):
    try:
        SCENE_JOBS[job_id]["status"] = "opening"
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            SCENE_JOBS[job_id] = {"status": "error", "message": "Could not open video."}
            return

        fps          = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration     = total_frames / fps
        max_secs     = duration * MAX_PCT / 100

        SCENE_JOBS[job_id].update({"status": "scanning", "duration": round(duration, 2)})

        step      = max(1, int(fps * 0.5), total_frames // 800)
        prev_gray = None
        raw_scores = []

        for fi in range(0, total_frames, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (160, 90))
            if prev_gray is not None:
                motion   = float(np.mean(cv2.absdiff(gray, prev_gray)))
                edges    = cv2.Canny(gray, 50, 150)
                edge_den = float(np.mean(edges)) / 255.0 * 30
                bvar     = float(np.std(gray)) / 128.0 * 20
                raw_scores.append((fi, motion * 0.5 + edge_den + bvar))
            prev_gray = gray

        cap.release()

        if not raw_scores:
            SCENE_JOBS[job_id] = {"status": "error", "message": "No frames analysed."}
            return

        SCENE_JOBS[job_id]["status"] = "selecting"

        win      = max(1, len(raw_scores) // 30)
        smoothed = []
        for i, (fi, sc) in enumerate(raw_scores):
            lo = max(0, i - win)
            hi = min(len(raw_scores), i + win + 1)
            smoothed.append((fi, float(np.mean([s[1] for s in raw_scores[lo:hi]]))))

        vals = [s[1] for s in smoothed]
        mn, mx = min(vals), max(vals)
        if mx == mn: mx = mn + 1
        normed = [(fi, (sc - mn) / (mx - mn)) for fi, sc in smoothed]

        min_gap     = max(3, int(fps * max(4, duration / (NUM_SCENES * 2))))
        gap_samples = max(1, min_gap // step)

        all_peaks = []
        for i, (fi, sc) in enumerate(normed):
            lo   = max(0, i - gap_samples)
            hi   = min(len(normed), i + gap_samples + 1)
            best = max(normed[lo:hi], key=lambda x: x[1])
            if best[0] == fi and sc > 0.1:
                all_peaks.append((fi, sc))

        all_peaks.sort(key=lambda x: -x[1])
        top_peaks = all_peaks[:NUM_SCENES]

        while len(top_peaks) < NUM_SCENES:
            existing = [p[0] for p in top_peaks]
            for i in range(NUM_SCENES):
                candidate = int((i + 0.5) / NUM_SCENES * total_frames)
                if not any(abs(candidate - e) < min_gap for e in existing):
                    top_peaks.append((candidate, 0.5))
                    existing.append(candidate)
                    break

        top_peaks.sort(key=lambda x: x[0])

        per_budget = max_secs / NUM_SCENES
        scenes     = []
        for fi, sc in top_peaks:
            ts    = fi / fps
            ideal = max(4.0, min(per_budget * 1.3, 45.0))
            start = round(max(0.0,      ts - ideal / 2), 2)
            end   = round(min(duration, ts + ideal / 2), 2)
            scenes.append({
                "start":     start,
                "end":       end,
                "duration":  round(end - start, 2),
                "peak_time": round(ts, 2),
                "score":     round(sc * 10, 1),
            })

        for i in range(1, len(scenes)):
            if scenes[i]["start"] < scenes[i-1]["end"] + 0.5:
                scenes[i]["start"] = round(scenes[i-1]["end"] + 0.5, 2)
                scenes[i]["end"]   = round(scenes[i]["start"] + scenes[i]["duration"], 2)

        total = sum(s["duration"] for s in scenes)
        if total > max_secs:
            ratio = max_secs / total
            for s in scenes:
                s["duration"] = round(s["duration"] * ratio, 2)
                s["end"]      = round(s["start"] + s["duration"], 2)

        total_extracted = round(sum(s["duration"] for s in scenes), 2)
        pct_used        = round(total_extracted / duration * 100, 1)

        score_order = sorted(range(NUM_SCENES), key=lambda i: -scenes[i]["score"])
        ranks = ["🥇 Best Scene", "🥈 2nd Best", "🥉 3rd Best"]
        for rank_pos, scene_idx in enumerate(score_order):
            scenes[scene_idx]["rank"] = ranks[rank_pos]

        SCENE_JOBS[job_id] = {
            "status":              "done",
            "duration":            round(duration, 2),
            "duration_fmt":        _fmt_time(duration),
            "fps":                 round(fps, 1),
            "scenes":              scenes,
            "total_extracted":     total_extracted,
            "total_extracted_fmt": _fmt_time(total_extracted),
            "pct_used":            pct_used,
        }

    except Exception as e:
        SCENE_JOBS[job_id] = {"status": "error", "message": str(e)}


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def scene_extract(request):
    filename = request.data.get("filename")
    if not filename:
        return Response({"detail": "filename is required"}, status=status.HTTP_400_BAD_REQUEST)
    filepath = settings.UPLOAD_DIR / filename
    if not filepath.exists():
        return Response({"detail": "File not found. Upload the video first."}, status=status.HTTP_404_NOT_FOUND)
    job_id = str(uuid.uuid4())
    SCENE_JOBS[job_id] = {"status": "queued"}
    threading.Thread(target=_analyse_video, args=(job_id, str(filepath)), daemon=True).start()
    return Response({"job_id": job_id}, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def scene_extract_status(request, job_id):
    job = SCENE_JOBS.get(job_id)
    if job is None:
        return Response({"detail": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(job)

# ── Caption Generation ─────────────────────────────────────────────────────────

CAPTION_JOBS = {}


def _generate_captions(job_id, filepath):
    """Run whisper transcription in a background thread."""
    try:
        import whisper

        CAPTION_JOBS[job_id]["status"] = "extracting_audio"

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.wav")

            # Extract audio
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", filepath, "-vn", "-ac", "1", "-ar", "16000", audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            if not os.path.exists(audio_path):
                CAPTION_JOBS[job_id] = {"status": "error", "message": "No audio track found in video."}
                return

            CAPTION_JOBS[job_id]["status"] = "transcribing"

            model = whisper.load_model("base")
            transcription = model.transcribe(audio_path)

        segments = [
            {
                "start": round(seg["start"], 2),
                "end":   round(seg["end"], 2),
                "text":  seg["text"].strip(),
            }
            for seg in transcription["segments"]
            if seg["text"].strip()
        ]

        CAPTION_JOBS[job_id] = {
            "status":   "done",
            "segments": segments,
            "language": transcription.get("language", "unknown"),
        }

    except ImportError:
        CAPTION_JOBS[job_id] = {
            "status":  "error",
            "message": "openai-whisper is not installed. Run: pip install openai-whisper",
        }
    except Exception as exc:
        CAPTION_JOBS[job_id] = {"status": "error", "message": str(exc)}


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_captions(request):
    """
    POST /captions/generate/
    Body: { "filename": "<uploaded filename>" }
    Returns: { "job_id": "..." }
    """
    filename = request.data.get("filename")
    if not filename:
        return Response({"detail": "filename is required"}, status=status.HTTP_400_BAD_REQUEST)

    filepath = settings.UPLOAD_DIR / filename
    if not filepath.exists():
        return Response({"detail": "File not found. Upload the video first."}, status=status.HTTP_404_NOT_FOUND)

    job_id = str(uuid.uuid4())
    CAPTION_JOBS[job_id] = {"status": "queued"}
    threading.Thread(target=_generate_captions, args=(job_id, str(filepath)), daemon=True).start()
    return Response({"job_id": job_id}, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def caption_status(request, job_id):
    """GET /captions/<job_id>/"""
    job = CAPTION_JOBS.get(job_id)
    if job is None:
        return Response({"detail": "Job not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(job)
