from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChatViewSet, MessageViewSet, HintsView, EmailValidationView, TestEmailView

router = DefaultRouter()
router.register(r'chats', ChatViewSet)

# For messages, we need a custom URL
urlpatterns = [
    path('', include(router.urls)),
    path('chats/<int:chat_id>/messages/', MessageViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='chat-messages'),
    path('hints/', HintsView.as_view(), name='hints'),
    path('validate-email/', EmailValidationView.as_view(), name='validate-email'),
    path('test-email/', TestEmailView.as_view(), name='test-email'),
]