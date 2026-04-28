# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_chat_order_specs_draft'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='price_quote_draft',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
