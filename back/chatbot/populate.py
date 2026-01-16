import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chatbot.settings')
django.setup()

from api.models import Chat, Message

# Create some chats
chat1 = Chat.objects.create(title='Первый чат')
chat2 = Chat.objects.create(title='Второй чат')
chat3 = Chat.objects.create(title='Третий чат')

# Add messages to chat1
Message.objects.create(chat=chat1, content='Привет, как дела?', is_user=True)
Message.objects.create(chat=chat1, content='Привет! Всё хорошо, спасибо.', is_user=False)
Message.objects.create(chat=chat1, content='Что нового?', is_user=True)
Message.objects.create(chat=chat1, content='Работаю над проектом.', is_user=False)

# Add messages to chat2
Message.objects.create(chat=chat2, content='Помоги с задачей', is_user=True)
Message.objects.create(chat=chat2, content='Конечно, что нужно?', is_user=False)
Message.objects.create(chat=chat2, content='Объясни алгоритм', is_user=True)

# Add messages to chat3
Message.objects.create(chat=chat3, content='Тестовое сообщение', is_user=True)
Message.objects.create(chat=chat3, content='Ответ на тест', is_user=False)

print('Данные добавлены!')