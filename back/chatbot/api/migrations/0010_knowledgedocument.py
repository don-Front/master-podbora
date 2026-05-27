from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0009_restore_chat_price_quote_draft"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgeDocument",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("document_key", models.CharField(db_index=True, max_length=255, unique=True)),
                ("display_name", models.CharField(max_length=512)),
                (
                    "doc_type",
                    models.CharField(
                        choices=[
                            ("gost", "ГОСТ / норматив"),
                            ("passport", "Паспорт / ТУ"),
                            ("catalog", "Каталог"),
                        ],
                        default="catalog",
                        max_length=32,
                    ),
                ),
                ("file_hash", models.CharField(blank=True, default="", max_length=64)),
                ("version", models.PositiveIntegerField(default=1)),
                ("source_path", models.CharField(blank=True, default="", max_length=1024)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at", "document_key"],
            },
        ),
    ]
