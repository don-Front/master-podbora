from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ChatViewSet,
    MessageViewSet,
    HintsView,
    EmailValidationView,
    TestEmailView,
    download_purs_questionnaire,
    faq_repair_memo_download,
    knowledge_doc_download,
    service_centers_catalog,
    equipment_media,
    message_attachment_download,
    chat_attachment_download,
)

router = DefaultRouter()
router.register(r'chats', ChatViewSet)

# For messages, we need a custom URL
urlpatterns = [
    path('equipment-media/<path:relpath>', equipment_media, name='equipment-media'),
    path('service-centers/', service_centers_catalog, name='service-centers'),
    path('faq-attachments/repair-memo/', faq_repair_memo_download, name='faq-repair-memo'),
    path('knowledge-doc/download/', knowledge_doc_download, name='knowledge-doc-download'),
    path('message-attachments/<int:message_id>/', message_attachment_download, name='message-attachment'),
    path('chat-attachments/<path:relpath>', chat_attachment_download, name='chat-attachment'),
    path('', include(router.urls)),
    path('chats/<int:chat_id>/messages/', MessageViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='chat-messages'),
    path('hints/', HintsView.as_view(), name='hints'),
    path('validate-email/', EmailValidationView.as_view(), name='validate-email'),
    path('test-email/', TestEmailView.as_view(), name='test-email'),
    path('templates/purs-questionnaire/', download_purs_questionnaire, name='purs-questionnaire'),
]