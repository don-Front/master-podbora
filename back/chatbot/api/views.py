import os
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action, api_view
from rest_framework.views import APIView
from django.db.models import Count
from .models import Chat, Message
from .serializers import ChatSerializer, MessageSerializer

# Import advanced chatbot
from .chatbot_core import AdvancedChatbot

# Import hints tree
from .hints_tree import HINTS_TREE, get_state, get_next_state, get_parent_state

# Import email service
from .email_service import EmailValidator, EmailSender, extract_contact_info

# Global chatbot instance
_chatbot_instance = None

def get_chatbot():
    """Lazy initialization of chatbot - recreates on module reload"""
    global _chatbot_instance
    if _chatbot_instance is None:
        config_path = r'C:\temp\chatbot\config.yaml'
        print(f"[INFO] Initializing chatbot with config: {config_path}")
        _chatbot_instance = AdvancedChatbot(config_path)
    return _chatbot_instance


def generate_chat_title(messages):
    """Генерирует заголовок чата через LLM"""
    if not messages:
        return "Пустой чат"
    
    try:
        bot = get_chatbot()
        if bot.config is None:
            return "Новый чат"
        
        # Собираем диалог для анализа
        conversation = []
        for msg in messages[:10]:  # Берем первые 10 сообщений
            role = "Клиент" if msg.is_user else "Бот"
            conversation.append(f"{role}: {msg.content[:200]}")
        
        dialog_text = "\n".join(conversation)
        
        # Запрос к LLM для генерации заголовка
        prompt = f"""Проанализируй диалог и придумай короткий заголовок (2-4 слова), отражающий тему разговора.
Заголовок должен быть на русском языке.
Примеры хороших заголовков: "Характеристики Turbo-Flow", "Выбор расходомера", "Монтаж счётчика".

Диалог:
{dialog_text}

Ответь ТОЛЬКО заголовком, без пояснений:"""

        response = bot.llm._call_llm(prompt)
        
        # Очищаем ответ
        title = response.strip().strip('"').strip("'")
        # Ограничиваем длину
        if len(title) > 50:
            title = title[:47] + "..."
        
        return title if title else "Консультация"
        
    except Exception as e:
        print(f"[ERROR] Error generating title: {e}")
        return "Консультация"


class ChatViewSet(viewsets.ModelViewSet):
    queryset = Chat.objects.all()
    serializer_class = ChatSerializer

    def get_queryset(self):
        queryset = Chat.objects.prefetch_related('messages').annotate(
            _message_count=Count('messages')
        )
        
        # Фильтр по архиву
        is_archived = self.request.query_params.get('archived', None)
        if is_archived is not None:
            queryset = queryset.filter(is_archived=is_archived.lower() == 'true')
        
        # Исключаем пустые чаты из списка (опционально)
        exclude_empty = self.request.query_params.get('exclude_empty', 'false')
        if exclude_empty.lower() == 'true':
            queryset = queryset.filter(_message_count__gt=0)
        
        return queryset.order_by('-created_at')

    def create(self, request):
        ip_address = self.get_client_ip(request)
        data = request.data.copy()
        data['ip_address'] = ip_address
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        chat = serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @action(detail=True, methods=['post'])
    def generate_title(self, request, pk=None):
        """Генерирует заголовок чата через LLM"""
        chat = self.get_object()
        messages = chat.messages.all().order_by('created_at')
        
        if not messages.exists():
            # Удаляем пустой чат
            chat.delete()
            return Response({'deleted': True, 'reason': 'empty_chat'})
        
        # Генерируем заголовок
        title = generate_chat_title(messages)
        chat.title = title
        chat.save()
        
        return Response({
            'id': chat.id,
            'title': title,
            'message_count': messages.count()
        })
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Архивирует чат"""
        chat = self.get_object()
        chat.is_archived = True
        chat.save()
        return Response({'id': chat.id, 'is_archived': True})
    
    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        """Извлекает чат из архива"""
        chat = self.get_object()
        chat.is_archived = False
        chat.save()
        return Response({'id': chat.id, 'is_archived': False})
    
    @action(detail=False, methods=['post'])
    def archive_old(self, request):
        """Архивирует все чаты старше 10 дней"""
        count = Chat.archive_old_chats()
        return Response({'archived_count': count})
    
    @action(detail=False, methods=['post'])
    def cleanup_empty(self, request):
        """Удаляет все пустые чаты"""
        count = Chat.delete_empty_chats()
        return Response({'deleted_count': count})
    
    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        """Завершает чат: генерирует заголовок или удаляет если пустой"""
        chat = self.get_object()
        messages = chat.messages.all().order_by('created_at')
        
        if not messages.exists():
            # Удаляем пустой чат
            chat_id = chat.id
            chat.delete()
            return Response({
                'action': 'deleted',
                'id': chat_id,
                'reason': 'empty_chat'
            })
        
        # Генерируем заголовок
        title = generate_chat_title(messages)
        chat.title = title
        chat.save()
        
        # Архивируем если старый
        if chat.should_be_archived:
            chat.is_archived = True
            chat.save()
        
        return Response({
            'action': 'finalized',
            'id': chat.id,
            'title': title,
            'is_archived': chat.is_archived,
            'message_count': messages.count()
        })


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer

    def get_queryset(self):
        chat_id = self.kwargs['chat_id']
        return Message.objects.filter(chat_id=chat_id)

    def list(self, request, chat_id=None):
        queryset = self.get_queryset()
        messages = list(queryset)
        serializer = self.get_serializer(messages, many=True)
        return Response(serializer.data)

    def create(self, request, chat_id=None):
        # Save user message
        data = request.data.copy()
        data['chat'] = chat_id
        data['is_user'] = True
        
        # Получаем текущее состояние и режим
        current_state = data.get('hint_state', 'start')
        is_hint_selection = data.get('is_hint_selection', False)
        hint_locked = data.get('hint_locked', False)  # Заблокирован ли режим подсказок
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        user_message = serializer.save()

        # Определяем ответ бота
        question = data['content']
        bot_response = ""
        next_state = current_state
        
        state_data = get_state(current_state)
        
        # Проверяем, является ли текущее состояние "начальным" (start или финальное)
        is_start_like = current_state == 'start' or state_data.get('is_final', False)
        
        if is_hint_selection:
            # Пользователь выбрал подсказку - переходим в новое состояние
            next_state = get_next_state(current_state, question)
            next_state_data = get_state(next_state)
            bot_response = next_state_data.get('bot_message', '')
            hint_locked = True  # Блокируем режим подсказок после первого выбора
            
        elif is_start_like:
            # На начальном этапе или финальном (новый цикл) - ВСЕГДА доступен AI-бот
            bot = get_chatbot()
            bot_response = bot.generate_response(question)
            # Подсказки остаются, блокировка сбрасывается
            hint_locked = False
            
        elif hint_locked:
            # Режим заблокирован - обрабатываем только ожидаемый ввод
            if state_data.get('expects_input', False):
                # Состояние ожидает ввод - переходим дальше
                next_state = state_data.get('next_state', current_state)
                next_state_data = get_state(next_state)
                bot_response = next_state_data.get('bot_message', '')
            else:
                # Свободный ввод не разрешён - просим выбрать подсказку
                bot_response = "Пожалуйста, выберите один из предложенных вариантов или нажмите 'Вернуться'."
                next_state = current_state
        else:
            # Режим не заблокирован - используем AI, но оставляем подсказки
            bot = get_chatbot()
            bot_response = bot.generate_response(question)
            # Подсказки остаются на месте

        # Save bot message
        bot_data = {
            'chat': chat_id,
            'content': bot_response,
            'is_user': False
        }
        bot_serializer = self.get_serializer(data=bot_data)
        bot_serializer.is_valid(raise_exception=True)
        bot_message = bot_serializer.save()

        # Получаем данные следующего состояния для фронтенда
        next_state_data = get_state(next_state)
        
        # Если перешли в финальное состояние - отправляем email уведомление
        email_sent = False
        email_error = ""
        if next_state_data.get('is_final', False) and hint_locked:
            try:
                chat = Chat.objects.get(pk=chat_id)
                all_messages = list(chat.messages.all().order_by('created_at').values(
                    'content', 'is_user', 'created_at'
                ))
                
                # Определяем категорию по состоянию
                category_map = {
                    'sales_final': 'Продажа оборудования',
                    'verification_final': 'Поверка',
                    'commissioning_final': 'Пуско-наладочные работы',
                    'tech_support_final': 'Техническая поддержка',
                    'claims_final': 'Претензии',
                    'vacancy_final': 'Отклик на вакансию',
                    'other_final': 'Другое',
                }
                category = category_map.get(next_state, 'Обращение')
                
                # Извлекаем контактную информацию из последнего сообщения пользователя
                client_email, client_phone = extract_contact_info(question)
                
                # Отправляем email
                email_sent, email_error = EmailSender.send_chat_notification(
                    category=category,
                    messages=all_messages,
                    client_email=client_email,
                    client_phone=client_phone,
                    ip_address=chat.ip_address,
                    chat_date=chat.created_at
                )
                
            except Exception as e:
                print(f"[ERROR] Failed to send email notification: {e}")
                email_error = str(e)

        # Return both messages + hint state info
        messages = [user_message, bot_message]
        response_serializer = self.get_serializer(messages, many=True)
        
        return Response({
            'messages': response_serializer.data,
            'hint_state': {
                'current_state': next_state,
                'hints': next_state_data.get('hints', []),
                'show_back': next_state_data.get('show_back', False),
                'is_final': next_state_data.get('is_final', False),
                'expects_input': next_state_data.get('expects_input', False),
                'hint_locked': hint_locked,  # Передаём состояние блокировки
            },
            'email_sent': email_sent,
        }, status=status.HTTP_201_CREATED)


class HintsView(APIView):
    """API для работы с системой подсказок"""
    
    def get(self, request):
        """Получить состояние подсказок"""
        state_id = request.query_params.get('state', 'start')
        state_data = get_state(state_id)
        
        return Response({
            'current_state': state_id,
            'bot_message': state_data.get('bot_message', ''),
            'hints': state_data.get('hints', []),
            'show_back': state_data.get('show_back', False),
            'is_final': state_data.get('is_final', False),
            'expects_input': state_data.get('expects_input', False),
        })
    
    def post(self, request):
        """Обработать переход состояния"""
        current_state = request.data.get('current_state', 'start')
        action = request.data.get('action', '')  # 'select_hint', 'back', 'free_input'
        hint_text = request.data.get('hint_text', '')
        
        if action == 'back':
            # Возврат к предыдущему состоянию
            next_state = get_parent_state(current_state)
        elif action == 'select_hint':
            # Выбор подсказки
            next_state = get_next_state(current_state, hint_text)
        elif action == 'free_input':
            # Свободный ввод
            state_data = get_state(current_state)
            if state_data.get('expects_input', False):
                next_state = state_data.get('next_state', current_state)
            else:
                next_state = 'free_chat'
        else:
            next_state = current_state
        
        next_state_data = get_state(next_state)
        
        return Response({
            'current_state': next_state,
            'bot_message': next_state_data.get('bot_message', ''),
            'hints': next_state_data.get('hints', []),
            'show_back': next_state_data.get('show_back', False),
            'is_final': next_state_data.get('is_final', False),
            'expects_input': next_state_data.get('expects_input', False),
        })


class EmailValidationView(APIView):
    """API для валидации email адресов"""
    
    def post(self, request):
        """Проверить валидность email адреса"""
        email = request.data.get('email', '').strip()
        
        if not email:
            return Response({
                'valid': False,
                'error': 'Email не указан'
            })
        
        is_valid, error = EmailValidator.validate_email(email)
        
        return Response({
            'valid': is_valid,
            'error': error if not is_valid else '',
            'email': email.lower() if is_valid else email
        })


class TestEmailView(APIView):
    """Тестовый endpoint для проверки отправки email"""
    
    def post(self, request):
        """Отправить тестовое email"""
        try:
            success, error = EmailSender.send_chat_notification(
                category="Тестовое сообщение",
                messages=[
                    {"content": "Привет!", "is_user": True, "created_at": None},
                    {"content": "Здравствуйте! Чем могу помочь?", "is_user": False, "created_at": None},
                    {"content": "Это тестовое сообщение для проверки SMTP", "is_user": True, "created_at": None},
                ],
                client_email="test@example.com",
                client_phone="+7 (999) 123-45-67",
                ip_address="127.0.0.1",
            )
            
            if success:
                return Response({
                    'success': True,
                    'message': 'Тестовое письмо отправлено!'
                })
            else:
                return Response({
                    'success': False,
                    'error': error
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
