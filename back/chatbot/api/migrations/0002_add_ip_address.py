# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='ip_address',
            field=models.GenericIPAddressField(default='0.0.0.0'),
        ),
    ]