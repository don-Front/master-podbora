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
    # Выбранная модель/серия для цепочки вопросов о поверке (RAG)
    verification_equipment = models.CharField(max_length=255, blank=True, default="")

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


class KnowledgeDocument(models.Model):
    """Версионированный документ базы знаний RAG."""

    DOC_TYPE_GOST = "gost"
    DOC_TYPE_PASSPORT = "passport"
    DOC_TYPE_CATALOG = "catalog"
    DOC_TYPE_CHOICES = [
        (DOC_TYPE_GOST, "ГОСТ / норматив"),
        (DOC_TYPE_PASSPORT, "Паспорт / ТУ"),
        (DOC_TYPE_CATALOG, "Каталог"),
    ]

    document_key = models.CharField(max_length=255, unique=True, db_index=True)
    display_name = models.CharField(max_length=512)
    doc_type = models.CharField(max_length=32, choices=DOC_TYPE_CHOICES, default=DOC_TYPE_CATALOG)
    file_hash = models.CharField(max_length=64, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    source_path = models.CharField(max_length=1024, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "document_key"]

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"{self.document_key} v{self.version} ({status})"
