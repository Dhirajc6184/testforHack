from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="VideoComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("output_filename", models.CharField(db_index=True, max_length=255)),
                ("author_username", models.CharField(max_length=150)),
                ("author_role", models.CharField(default="viewer", max_length=10)),
                ("timestamp_sec", models.FloatField(help_text="Video time in seconds where the pin sits")),
                ("text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["timestamp_sec", "created_at"]},
        ),
    ]
