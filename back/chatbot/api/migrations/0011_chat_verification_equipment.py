from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0010_knowledgedocument"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="verification_equipment",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
