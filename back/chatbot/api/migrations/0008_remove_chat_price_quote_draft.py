from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0007_chat_price_quote_draft'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='chat',
            name='price_quote_draft',
        ),
    ]
