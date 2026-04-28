# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_message_attachment'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='order_specs_draft',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='chat',
            name='order_specs_pending_field',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
