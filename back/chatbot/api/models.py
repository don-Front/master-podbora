from django.db import models
from django.utils import timezone
from datetime import timedelta


class Chat(models.Model):
    title = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(default='0.0.0.0')
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)
    # Черновик JSON спецификации и текущее поле при уточнении (сценарий заказа по PDF)
    order_specs_draft = models.JSONField(null=True, blank=True)
    order_specs_pending_field = models.CharField(max_length=64, blank=True, null=True)
    # Временные данные запроса цены по прибору со слайдера (оборудование, телефон, почта)
    price_quote_draft = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.title
    
    @property
    def should_be_archived(self):
        """Проверяет, должен ли чат быть в архиве (старше 10 дней)"""
        return self.created_at < timezone.now() - timedelta(days=10)
    
    @property
    def message_count(self):
        """Количество сообщений в чате"""
        return self.messages.count()
    
    @classmethod
    def archive_old_chats(cls):
        """Архивирует чаты старше 10 дней"""
        threshold = timezone.now() - timedelta(days=10)
        return cls.objects.filter(
            created_at__lt=threshold, 
            is_archived=False
        ).update(is_archived=True)
    
    @classmethod
    def delete_empty_chats(cls):
        """Удаляет чаты без сообщений"""
        empty_chats = cls.objects.annotate(
            msg_count=models.Count('messages')
        ).filter(msg_count=0)
        count = empty_chats.count()
        empty_chats.delete()
        return count


class Message(models.Model):
    chat = models.ForeignKey(Chat, related_name='messages', on_delete=models.CASCADE)
    content = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to='chat_images/', blank=True, null=True)
    attachment = models.FileField(upload_to='chat_attachments/', blank=True, null=True)
    is_user = models.BooleanField(default=True)  # True if sent by user, False if by bot
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message in {self.chat.title}: {self.content[:50]}"
    
    @property
    def has_image(self):
        return bool(self.image)

    @property
    def has_attachment(self):
        return bool(self.attachment)
