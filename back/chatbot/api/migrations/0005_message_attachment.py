# Generated manually for Message.attachment

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_message_image_alter_message_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='chat_attachments/'),
        ),
    ]
