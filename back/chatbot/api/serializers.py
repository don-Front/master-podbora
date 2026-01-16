from rest_framework import serializers
from .models import Chat, Message


class MessageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = ['id', 'chat', 'content', 'image', 'image_url', 'is_user', 'created_at']
        extra_kwargs = {
            'image': {'write_only': True, 'required': False},
            'content': {'required': False},
        }
    
    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


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
