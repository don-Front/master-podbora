# Image upload support added
import ipaddress
import json
import logging
import os
import sys
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action, api_view
from rest_framework.views import APIView
from django.db.models import Count
from django.conf import settings
from .models import Chat, Message
from .serializers import ChatSerializer, MessageSerializer

# Import hints tree
from .hints_tree import HINTS_TREE, get_state, get_next_state, get_parent_state

# Import email service
from .email_service import EmailValidator, EmailSender, extract_contact_info

logger = logging.getLogger(__name__)


def _parse_equipment_for_price(data):
    """Достаёт объект прибора из JSON-тела или FormData (поле equipment_for_price)."""
    eq_raw = data.get('equipment_for_price')
    if eq_raw is None:
        return None
    if isinstance(eq_raw, dict):
        return eq_raw
    if isinstance(eq_raw, str):
        s = eq_raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _parse_order_specs_for_price(data):
    """Снимок спецификации из PDF (для расчёта цены), из JSON или FormData."""
    raw = data.get('order_specs_for_price')
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


# Global chatbot instance
_chatbot_instance = None

def get_chatbot():
    """Lazy initialization of chatbot - recreates on module reload"""
    global _chatbot_instance
    if _chatbot_instance is None:
        # Импорт тяжёлых зависимостей (torch, FAISS, эмбеддинги) только при первом вызове LLM/RAG,
        # иначе даже GET /hints/ блокируется на минуты и может упасть с 500.
        from .chatbot_core import AdvancedChatbot

        # Пытаемся найти config.yaml в проекте
        current_file = os.path.abspath(__file__)
        # Путь: back/chatbot/api/views.py -> back/project/config.yaml
        # api -> chatbot -> back -> project
        project_root = os.path.normpath(os.path.join(os.path.dirname(current_file), '..', '..', 'project'))
        config_path = os.path.normpath(os.path.join(project_root, 'config.yaml'))
        
        if not os.path.exists(config_path):
            # Fallback на старый путь
            config_path = r'C:\temp\chatbot\config.yaml'
            print(f"[WARNING] Project config not found at {os.path.normpath(os.path.join(project_root, 'config.yaml'))}, using: {config_path}")
        else:
            print(f"[INFO] Using config from project: {config_path}")
        
        print(f"[INFO] Initializing chatbot with config: {config_path}")
        _chatbot_instance = AdvancedChatbot(config_path)
    return _chatbot_instance

def _safe_print_order_specs_final(draft) -> None:
    """Вывод итогового JSON в консоль; не должен ронять запрос при нестандартных типах."""
    try:
        from .order_specs_helpers import specs_for_api_response

        safe = specs_for_api_response(draft)
        line = json.dumps(safe, ensure_ascii=False)
        msg = f"[ORDER_SPECS_FINAL] {line}"
        # Daphne/Windows часто буферизуют stdout — дублируем в stderr и лог
        print(msg, flush=True)
        print(msg, file=sys.stderr, flush=True)
        logger.warning(msg)
    except Exception as e:
        err = f"[ERROR] ORDER_SPECS_FINAL (print): {e}"
        print(err, flush=True)
        print(err, file=sys.stderr, flush=True)
        logger.exception("ORDER_SPECS_FINAL failed")


def _is_pdf_upload(file_obj):
    if not file_obj:
        return False
    name = (getattr(file_obj, 'name', '') or '').lower()
    ctype = (getattr(file_obj, 'content_type', '') or '').lower()
    return name.endswith('.pdf') or ctype in ('application/pdf', 'application/x-pdf')


def reload_chatbot():
    """Перезагружает чатбот с новой конфигурацией"""
    global _chatbot_instance
    _chatbot_instance = None
    return get_chatbot()


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
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = (request.META.get('REMOTE_ADDR') or '').strip()
        if not ip or ip.lower() in ('unknown', 'null', '-'):
            return '0.0.0.0'
        try:
            ipaddress.ip_address(ip)
            return ip
        except ValueError:
            return '0.0.0.0'
    
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
    
    def get_serializer_context(self):
        """Добавляем request в контекст для построения URL изображений"""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

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
        
        # Вложения: изображение (общий сценарий) и PDF (оформление заказа)
        image_file = request.FILES.get('image')
        attachment_file = request.FILES.get('attachment')
        
        # Получаем текущее состояние и режим
        current_state = data.get('hint_state', 'start')
        is_hint_selection = str(data.get('is_hint_selection', 'false')).lower() == 'true'
        hint_locked = str(data.get('hint_locked', 'false')).lower() == 'true'
        
        # Создаём данные для сериализатора
        message_data = {
            'chat': chat_id,
            'content': data.get('content', ''),
            'is_user': True,
        }
        
        serializer = self.get_serializer(data=message_data)
        serializer.is_valid(raise_exception=True)
        save_kw = {}
        if image_file:
            save_kw['image'] = image_file
        if attachment_file:
            save_kw['attachment'] = attachment_file
        user_message = serializer.save(**save_kw) if save_kw else serializer.save()

        # Определяем ответ бота
        question = message_data.get('content', '')
        bot_response = ""
        next_state = current_state
        order_specs_json = None
        allow_empty_bot = False  # True: финал заказа, текст отдаёт фронт по ответу /api/1c/data
        suppress_chat_email = False  # не дублировать письмо при завершении сценария «цена со слайдера»

        state_data = get_state(current_state)
        
        # Проверяем, является ли текущее состояние "начальным" (start или финальное)
        is_start_like = current_state == 'start' or state_data.get('is_final', False)
        
        if is_hint_selection:
            q_sel = (question or '').strip()
            if q_sel == 'Получить цену' and current_state == 'order_final':
                eq_obj = _parse_equipment_for_price(data)
                label = ''
                if eq_obj:
                    label = (eq_obj.get('model') or eq_obj.get('name') or '').strip()
                if not eq_obj or not label:
                    next_state = current_state
                    bot_response = (
                        'Не удалось определить прибор на слайдере. Пролистайте карточку и нажмите '
                        '«Получить цену» ещё раз.'
                    )
                    hint_locked = True
                else:
                    try:
                        Chat.objects.get(pk=chat_id)
                        bot_response = ""
                        allow_empty_bot = True
                        next_state = 'order_final'
                        suppress_chat_email = True
                        hint_locked = True
                    except Chat.DoesNotExist:
                        bot_response = 'Сессия чата устарела. Начните диалог заново.'
                        next_state = 'start'
                        hint_locked = False
            else:
                # Пользователь выбрал подсказку - переходим в новое состояние
                next_state = get_next_state(current_state, question)
                next_state_data = get_state(next_state)
                bot_response = next_state_data.get('bot_message') or ''
                hint_locked = True  # Блокируем режим подсказок после первого выбора
                if next_state == "order_pdf_request":
                    try:
                        ch = Chat.objects.get(pk=chat_id)
                        ch.order_specs_draft = None
                        ch.order_specs_pending_field = None
                        ch.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
                    except Chat.DoesNotExist:
                        pass
            
        elif is_start_like:
            # На начальном этапе или финальном (новый цикл) - ВСЕГДА доступен AI-бот
            bot = get_chatbot()
            bot_response = bot.generate_response(question)
            # Подсказки остаются, блокировка сбрасывается
            hint_locked = False
            
        elif hint_locked:
            # Режим заблокирован - обрабатываем только ожидаемый ввод
            if current_state == 'order_pdf_request':
                has_pdf = _is_pdf_upload(attachment_file)
                has_image = bool(image_file)
                text = (question or '').strip()
                if has_pdf:
                    abs_pdf = os.path.join(settings.MEDIA_ROOT, str(user_message.attachment))
                    thanks_template = get_state("order_final").get("bot_message") or ""
                    try:
                        from .pdf_order_analysis import run_pdf_order_pipeline
                        from .order_specs_helpers import (
                            format_prompt_for_field,
                            list_missing_fields,
                            merge_draft,
                        )

                        bot_ai = get_chatbot()
                        if getattr(bot_ai, "llm", None) is None:
                            raise RuntimeError("LLM не инициализирован (проверьте config.yaml и LM Studio).")
                        specs, _ocr_text, pipeline_err = run_pdf_order_pipeline(abs_pdf, bot_ai.llm)
                        draft = merge_draft(specs)
                        order_specs_json = draft

                        chat = Chat.objects.get(pk=chat_id)
                        chat.order_specs_draft = draft
                        missing = list_missing_fields(draft)

                        if missing:
                            chat.order_specs_pending_field = missing[0]
                            chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
                            next_state = "order_specs_clarify"
                            intro = ""
                            if pipeline_err:
                                intro = (
                                    f"Часть данных из PDF распознана не полностью ({pipeline_err}).\n\n"
                                )
                            bot_response = intro + format_prompt_for_field(missing[0])
                            hint_locked = True
                        else:
                            chat.order_specs_draft = None
                            chat.order_specs_pending_field = None
                            chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
                            _safe_print_order_specs_final(draft)
                            next_state = "order_final"
                            bot_response = ""
                            allow_empty_bot = True
                            hint_locked = True
                    except Exception as e:
                        print(f"[ERROR] pdf_order_pipeline: {e}")
                        order_specs_json = None
                        next_state = state_data.get("next_state", "order_final")
                        bot_response = (
                            f"Не удалось обработать PDF автоматически: {e}\n\n{thanks_template}"
                        )
                        hint_locked = True
                elif has_image:
                    bot_response = (
                        "Нужен документ в формате PDF с характеристиками оборудования. "
                        "Пожалуйста, прикрепите PDF-файл, а не изображение."
                    )
                    next_state = current_state
                elif text:
                    bot_response = (
                        "Для оформления заказа пришлите, пожалуйста, файл PDF с описанием характеристик "
                        "оборудования (кнопка скрепки 📎)."
                    )
                    next_state = current_state
                else:
                    bot_response = (
                        "Пожалуйста, прикрепите и отправьте файл в формате PDF с описанием характеристик оборудования."
                    )
                    next_state = current_state
            elif current_state == 'order_specs_clarify':
                from .order_specs_helpers import (
                    format_prompt_for_field,
                    list_missing_fields,
                    merge_draft,
                    parse_field_value,
                )

                text = (question or "").strip()
                chat = Chat.objects.filter(pk=chat_id).first()
                if not chat:
                    bot_response = "Сессия чата устарела. Начните диалог заново."
                    next_state = "start"
                    hint_locked = False
                else:
                    draft = merge_draft(chat.order_specs_draft or {})
                    pending = chat.order_specs_pending_field
                    missing_pre = list_missing_fields(draft)
                    if not pending and missing_pre:
                        pending = missing_pre[0]
                        chat.order_specs_pending_field = pending
                        chat.save(update_fields=["order_specs_pending_field"])

                    if not text:
                        if pending or missing_pre:
                            key = pending or (missing_pre[0] if missing_pre else None)
                            if key:
                                bot_response = format_prompt_for_field(key)
                            else:
                                bot_response = "Введите значение в поле ниже и отправьте."
                        else:
                            bot_response = "Введите значение текстом."
                        next_state = "order_specs_clarify"
                        order_specs_json = draft
                        hint_locked = True
                    else:
                        key = pending or (missing_pre[0] if missing_pre else None)
                        if not key:
                            _safe_print_order_specs_final(draft)
                            chat.order_specs_draft = None
                            chat.order_specs_pending_field = None
                            chat.save(
                                update_fields=["order_specs_draft", "order_specs_pending_field"]
                            )
                            bot_response = ""
                            allow_empty_bot = True
                            next_state = "order_final"
                            order_specs_json = draft
                            hint_locked = True
                        else:
                            try:
                                draft[key] = parse_field_value(key, text)
                            except ValueError as ve:
                                bot_response = (
                                    f"Не удалось разобрать ответ ({ve}). "
                                    f"Повторите ввод.\n\n{format_prompt_for_field(key)}"
                                )
                                next_state = "order_specs_clarify"
                                order_specs_json = draft
                                hint_locked = True
                            else:
                                chat.order_specs_draft = draft
                                missing = list_missing_fields(draft)
                                if missing:
                                    chat.order_specs_pending_field = missing[0]
                                    chat.save(
                                        update_fields=[
                                            "order_specs_draft",
                                            "order_specs_pending_field",
                                        ]
                                    )
                                    bot_response = format_prompt_for_field(missing[0])
                                    next_state = "order_specs_clarify"
                                    order_specs_json = draft
                                    hint_locked = True
                                else:
                                    chat.order_specs_draft = None
                                    chat.order_specs_pending_field = None
                                    chat.save(
                                        update_fields=[
                                            "order_specs_draft",
                                            "order_specs_pending_field",
                                        ]
                                    )
                                    _safe_print_order_specs_final(draft)
                                    bot_response = ""
                                    allow_empty_bot = True
                                    next_state = "order_final"
                                    order_specs_json = draft
                                    hint_locked = True
            elif state_data.get('expects_input', False):
                # Состояние ожидает ввод - переходим дальше
                next_state = state_data.get('next_state', current_state)
                next_state_data = get_state(next_state)
                bot_response = next_state_data.get('bot_message') or ''
            else:
                # Свободный ввод не разрешён - просим выбрать подсказку
                bot_response = "Пожалуйста, выберите один из предложенных вариантов или нажмите 'Вернуться'."
                next_state = current_state
        else:
            # Режим не заблокирован - используем AI, но оставляем подсказки
            bot = get_chatbot()
            bot_response = bot.generate_response(question)
            # Подсказки остаются на месте

        if not allow_empty_bot and (bot_response is None or not str(bot_response).strip()):
            bot_response = (
                "Не удалось получить текст ответа. Попробуйте повторить запрос или обратитесь в поддержку."
            )

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
        if next_state_data.get('is_final', False) and hint_locked and not suppress_chat_email:
            try:
                chat = Chat.objects.get(pk=chat_id)
                chat_messages = chat.messages.all().order_by('created_at')
                
                # Собираем сообщения с путями к изображениям
                all_messages = []
                for msg in chat_messages:
                    msg_data = {
                        'content': msg.content,
                        'is_user': msg.is_user,
                        'created_at': msg.created_at,
                    }
                    # Добавляем путь к изображению и вложению (PDF) если есть
                    if msg.image:
                        msg_data['image'] = os.path.join(settings.MEDIA_ROOT, str(msg.image))
                    if msg.attachment:
                        msg_data['attachment'] = os.path.join(settings.MEDIA_ROOT, str(msg.attachment))
                    all_messages.append(msg_data)
                
                # Определяем категорию по состоянию
                category_map = {
                    'sales_final': 'Продажа оборудования',
                    'verification_final': 'Поверка',
                    'commissioning_final': 'Пуско-наладочные работы',
                    'tech_support_final': 'Техническая поддержка',
                    'claims_final': 'Претензии',
                    'vacancy_final': 'Отклик на вакансию',
                    'other_final': 'Другое',
                    'order_final': 'Оформление заказа',
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

        safe_order_specs = None
        if order_specs_json is not None:
            try:
                from .order_specs_helpers import specs_for_api_response

                safe_order_specs = specs_for_api_response(order_specs_json)
            except Exception as e:
                print(f"[ERROR] order_specs_json sanitize for response: {e}")
                safe_order_specs = None

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
            'order_specs_json': safe_order_specs,
        }, status=status.HTTP_201_CREATED)


class HintsView(APIView):
    """API для работы с системой подсказок"""
    
    def get(self, request):
        """Получить состояние подсказок"""
        state_id = request.query_params.get('state', 'start')
        state_data = get_state(state_id)
        
        return Response({
            'current_state': state_id,
            'bot_message': state_data.get('bot_message') or '',
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
            'bot_message': next_state_data.get('bot_message') or '',
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
