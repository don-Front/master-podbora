# Generated migration for adding is_archived field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_add_ip_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
    ]

