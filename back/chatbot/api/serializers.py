from rest_framework import serializers
from .models import Chat, Message


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = '__all__'


class ChatSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)
    message_count = serializers.SerializerMethodField()
    should_be_archived = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = ['id', 'title', 'ip_address', 'created_at', 'is_archived', 
                  'messages', 'message_count', 'should_be_archived']
    
    def get_message_count(self, obj):
        # Используем аннотированное значение если есть, иначе вычисляем
        if hasattr(obj, '_message_count'):
            return obj._message_count
        return obj.messages.count()
    
    def get_should_be_archived(self, obj):
        return obj.should_be_archived
