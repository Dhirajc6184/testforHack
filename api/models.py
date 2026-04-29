from django.db import models


class VideoComment(models.Model):
    """
    A comment pinned to a specific timestamp on a processed video.

    - Any authenticated user can POST a comment.
    - author_username stores the username string (no DB FK since users live in users.json).
    - author_role stores 'editor' or 'viewer' at post time.
    - GET is open to anyone with the output_filename.
    - Editors can DELETE any comment; viewers can only delete their own.
    """
    output_filename = models.CharField(max_length=255, db_index=True)
    author_username = models.CharField(max_length=150)
    author_role     = models.CharField(max_length=10, default="viewer")
    timestamp_sec   = models.FloatField(help_text="Video time in seconds where the pin sits")
    text            = models.TextField()
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp_sec", "created_at"]

    def __str__(self):
        return f"[{self.output_filename}@{self.timestamp_sec}s] {self.author_username}: {self.text[:40]}"
