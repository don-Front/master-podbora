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
from django.http import FileResponse, Http404
from .models import Chat, Message
from .serializers import ChatSerializer, MessageSerializer

# Import hints tree
from .hints_tree import HINTS_TREE, get_state, get_next_state, get_parent_state

# Import email service
from .email_service import EmailValidator, EmailSender, extract_contact_info
from .verification_client import send_verification_code, verify_code as verify_email_code

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


def _parse_liquid_installation_lead(data):
    """ФИО и контакт из сценария «поверочные установки — жидкость» (JSON в теле или FormData)."""
    raw = data.get('liquid_installation_lead')
    if raw is None:
        return {}
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    if not isinstance(d, dict):
        return {}
    return {
        'full_name': (d.get('full_name') or '').strip(),
        'email': (d.get('email') or '').strip().lower(),
        'phone': (d.get('phone') or '').strip(),
        'tz_attachment_url': (d.get('tz_attachment_url') or '').strip(),
        'tz_file_name': (d.get('tz_file_name') or '').strip(),
        'tz_comments': (d.get('tz_comments') or '').strip(),
    }


# Global chatbot instance
_chatbot_instance = None
_order_specs_llm = None

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


def get_order_specs_llm():
    """Лёгкий LLM-клиент для разбора PDF без загрузки RAG/эмбеддингов."""
    global _order_specs_llm
    if _order_specs_llm is None:
        import yaml
        from .chatbot_core.llm_client import LLMClient

        current_file = os.path.abspath(__file__)
        project_root = os.path.normpath(os.path.join(os.path.dirname(current_file), '..', '..', 'project'))
        config_path = os.path.normpath(os.path.join(project_root, 'config.yaml'))
        if not os.path.exists(config_path):
            config_path = r'C:\temp\chatbot\config.yaml'

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        llm_config = config.get('llm') or {}
        required = ['base_url', 'model', 'temperature', 'max_tokens']
        missing = [key for key in required if not llm_config.get(key)]
        if missing:
            raise ValueError(f"В config.yaml не заполнены параметры llm: {', '.join(missing)}")

        _order_specs_llm = LLMClient(**llm_config)
    return _order_specs_llm

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


# ТЗ в сценарии «поверочные установки — жидкость»
LIQUID_TZ_MAX_BYTES = 10 * 1024 * 1024
LIQUID_TZ_EXTENSIONS = ('.pdf', '.doc', '.docx', '.txt', '.zip', '.rar')
LIQUID_TZ_MIME_TYPES = frozenset(
    {
        'application/pdf',
        'application/x-pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'application/zip',
        'application/x-zip-compressed',
        'application/x-rar-compressed',
        'application/vnd.rar',
    }
)


def _is_liquid_tz_upload(file_obj):
    """Допустимое вложение ТЗ: расширение или известный MIME (без расширения)."""
    if not file_obj:
        return False
    name = (getattr(file_obj, 'name', '') or '').lower()
    if any(name.endswith(ext) for ext in LIQUID_TZ_EXTENSIONS):
        return True
    ctype = (getattr(file_obj, 'content_type', '') or '').lower().split(';')[0].strip()
    return ctype in LIQUID_TZ_MIME_TYPES


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
        order_specs_llm_response = None
        order_specs_ocr_text = None
        allow_empty_bot = False  # True: финал заказа, текст отдаёт фронт по ответу /api/1c/data
        suppress_chat_email = False  # не дублировать письмо при завершении сценария «цена со слайдера»
        verification_passed = False  # фронт выводит в консоль при успешной проверке кода
        verified_contact = None
        liquid_installation_lead = None
        submit_verification_liquid_result = None

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
                        ch = Chat.objects.get(pk=chat_id)
                        specs_snap = _parse_order_specs_for_price(data) or {}
                        price_draft = {
                            'equipment': {
                                'id': eq_obj.get('id') or eq_obj.get('equipment_id') or '',
                                'model': eq_obj.get('model') or '',
                                'name': eq_obj.get('name') or '',
                                'image': eq_obj.get('image') or '',
                            },
                            'specs': specs_snap,
                            'phone': None,
                            'email': None,
                        }
                        ch.price_quote_draft = price_draft
                        ch.save(update_fields=['price_quote_draft'])
                        next_state = 'equipment_price_phone'
                        bot_response = get_state(next_state).get('bot_message') or ''
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
                if current_state == 'verification_installations_liquid_tz' and q_sel == 'Далее':
                    ctx = _parse_liquid_installation_lead(data)
                    liquid_installation_lead = {
                        'full_name': ctx.get('full_name') or '',
                        'email': ctx.get('email') or '',
                        'phone': ctx.get('phone') or '',
                        'tz_attachment_url': '',
                        'tz_file_name': '',
                        'tz_comments': '',
                    }
                    bot_response = (
                        'Хорошо, продолжаем без вложения технического задания.\n\n' + bot_response
                    )
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

                        llm = get_order_specs_llm()
                        specs, _ocr_text, pipeline_err, llm_raw = run_pdf_order_pipeline(abs_pdf, llm)
                        order_specs_llm_response = llm_raw
                        order_specs_ocr_text = _ocr_text
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
            elif current_state == 'equipment_price_phone':
                text = (question or '').strip()
                phone_st = get_state('equipment_price_phone')
                ask_phone = phone_st.get('bot_message') or ''
                chat = Chat.objects.filter(pk=chat_id).first()
                if not chat or not chat.price_quote_draft:
                    bot_response = (
                        'Сессия запроса цены устарела. Выберите прибор на слайдере и снова нажмите «Получить цену».'
                    )
                    next_state = 'order_final'
                    hint_locked = True
                elif not text:
                    bot_response = ask_phone
                    next_state = current_state
                    hint_locked = True
                else:
                    ok, err, pretty = EmailValidator.validate_phone_ru(text)
                    if not ok:
                        bot_response = f'{err}\n\n{ask_phone}'
                        next_state = current_state
                        hint_locked = True
                    else:
                        draft = dict(chat.price_quote_draft)
                        draft['phone'] = pretty
                        chat.price_quote_draft = draft
                        chat.save(update_fields=['price_quote_draft'])
                        next_state = 'equipment_price_email'
                        next_state_data = get_state(next_state)
                        bot_response = next_state_data.get('bot_message') or ''
                        hint_locked = True
            elif current_state == 'equipment_price_email':
                text = (question or '').strip()
                email_st = get_state('equipment_price_email')
                ask_email = email_st.get('bot_message') or ''
                chat = Chat.objects.filter(pk=chat_id).first()
                if not chat or not chat.price_quote_draft:
                    bot_response = (
                        'Сессия запроса цены устарела. Начните с кнопки «Получить цену» у слайдера приборов.'
                    )
                    next_state = 'order_final'
                    hint_locked = True
                elif not text:
                    bot_response = ask_email
                    next_state = current_state
                    hint_locked = True
                else:
                    ok, err = EmailValidator.validate_email(text)
                    if not ok:
                        bot_response = f'{err}\n\n{ask_email}'
                        next_state = current_state
                        hint_locked = True
                    else:
                        draft = dict(chat.price_quote_draft)
                        em = text.strip().lower()
                        draft['email'] = em
                        sent_ok, sent_err = send_verification_code(em)
                        if not sent_ok:
                            bot_response = (
                                f'Не удалось отправить код на почту: {sent_err}\n\n{ask_email}'
                            )
                            next_state = current_state
                            hint_locked = True
                            chat.price_quote_draft = draft
                            chat.save(update_fields=['price_quote_draft'])
                        else:
                            chat.price_quote_draft = draft
                            chat.save(update_fields=['price_quote_draft'])
                            next_state = 'equipment_price_verify_code'
                            next_state_data = get_state(next_state)
                            bot_response = next_state_data.get('bot_message') or ''
                            hint_locked = True
            elif current_state == 'equipment_price_verify_code':
                text = (question or '').strip()
                verify_st = get_state('equipment_price_verify_code')
                ask_code = verify_st.get('bot_message') or ''
                chat = Chat.objects.filter(pk=chat_id).first()
                if not chat or not chat.price_quote_draft:
                    bot_response = (
                        'Сессия запроса цены устарела. Начните с кнопки «Получить цену» у слайдера приборов.'
                    )
                    next_state = 'order_final'
                    hint_locked = True
                elif not text:
                    bot_response = ask_code
                    next_state = current_state
                    hint_locked = True
                else:
                    em = (chat.price_quote_draft.get('email') or '').strip().lower()
                    if not em:
                        bot_response = (
                            'Не удалось восстановить адрес почты. Укажите email ещё раз.'
                        )
                        next_state = 'equipment_price_email'
                        hint_locked = True
                    elif len(text) != 6 or not text.isdigit():
                        bot_response = (
                            f'Код должен состоять из 6 цифр. Повторите ввод.\n\n{ask_code}'
                        )
                        next_state = current_state
                        hint_locked = True
                    else:
                        vok, verr = verify_email_code(em, text)
                        if not vok:
                            bot_response = f'{verr}\n\n{ask_code}'
                            next_state = current_state
                            hint_locked = True
                        else:
                            draft = dict(chat.price_quote_draft)
                            chat.price_quote_draft = None
                            chat.save(update_fields=['price_quote_draft'])
                            eq = draft.get('equipment') or {}
                            label = (eq.get('model') or eq.get('name') or '').strip() or 'прибор'
                            em_disp = draft.get('email') or em
                            bot_response = (
                                f'Спасибо! Почта подтверждена. Запрос цены на «{label}» передан менеджеру; '
                                f'ожидайте связи по телефону {draft.get("phone", "")} или на {em_disp}.'
                            )
                            next_state = 'order_final'
                            suppress_chat_email = True
                            verification_passed = True
                            verified_contact = {
                                'phone': draft.get('phone') or '',
                                'email': em_disp,
                            }
                            hint_locked = True
            elif current_state == 'verification_installations_liquid':
                text = (question or '').strip()
                ask_fio = get_state('verification_installations_liquid').get('bot_message') or ''
                if not text:
                    bot_response = ask_fio
                    next_state = current_state
                    hint_locked = True
                else:
                    normalized = ' '.join(text.split())
                    parts = [p for p in normalized.replace('-', ' ').split(' ') if p]
                    if len(parts) < 3 or len(normalized) < 10:
                        bot_response = (
                            'Пожалуйста, введите полное ФИО: фамилию, имя и отчество '
                            'тремя словами через пробел (дефис в фамилии допускается).\n\n'
                            f'{ask_fio}'
                        )
                        next_state = current_state
                        hint_locked = True
                    else:
                        liquid_installation_lead = {
                            'full_name': normalized,
                            'email': '',
                            'phone': '',
                            'tz_attachment_url': '',
                            'tz_file_name': '',
                            'tz_comments': '',
                        }
                        next_state = 'verification_installations_liquid_contact'
                        next_state_data = get_state(next_state)
                        bot_response = next_state_data.get('bot_message') or ''
                        hint_locked = True
            elif current_state == 'verification_installations_liquid_contact':
                text = (question or '').strip()
                ask_contact = (
                    get_state('verification_installations_liquid_contact').get('bot_message') or ''
                )
                ctx = _parse_liquid_installation_lead(data)
                full_name = (ctx.get('full_name') or '').strip()
                if not full_name:
                    bot_response = (
                        'Не удалось восстановить ФИО. Нажмите «Вернуться» и снова введите фамилию, имя и отчество.'
                    )
                    next_state = 'verification_installations_liquid'
                    hint_locked = True
                elif not text:
                    bot_response = ask_contact
                    next_state = current_state
                    hint_locked = True
                    liquid_installation_lead = {
                        'full_name': full_name,
                        'email': '',
                        'phone': '',
                        'tz_attachment_url': '',
                        'tz_file_name': '',
                        'tz_comments': '',
                    }
                else:
                    ok, err, kind, norm = EmailValidator.validate_email_format_or_phone_ru(text)
                    if not ok:
                        bot_response = f'{err}\n\n{ask_contact}'
                        next_state = current_state
                        hint_locked = True
                        liquid_installation_lead = {
                            'full_name': full_name,
                            'email': '',
                            'phone': '',
                            'tz_attachment_url': '',
                            'tz_file_name': '',
                            'tz_comments': '',
                        }
                    else:
                        email = norm if kind == 'email' else ''
                        phone = norm if kind == 'phone' else ''
                        liquid_installation_lead = {
                            'full_name': full_name,
                            'email': email,
                            'phone': phone,
                            'tz_attachment_url': '',
                            'tz_file_name': '',
                            'tz_comments': '',
                        }
                        next_state = 'verification_installations_liquid_tz'
                        next_state_data = get_state(next_state)
                        bot_response = next_state_data.get('bot_message') or ''
                        hint_locked = True
            elif current_state == 'verification_installations_liquid_tz':
                has_attachment = bool(attachment_file)
                has_tz_format = _is_liquid_tz_upload(attachment_file)
                tz_size = int(getattr(attachment_file, 'size', 0) or 0) if attachment_file else 0
                tz_size_ok = tz_size <= LIQUID_TZ_MAX_BYTES
                has_image = bool(image_file)
                text = (question or '').strip()
                ask_tz = get_state('verification_installations_liquid_tz').get('bot_message') or ''
                ctx = _parse_liquid_installation_lead(data)
                base_lead = {
                    'full_name': ctx.get('full_name') or '',
                    'email': ctx.get('email') or '',
                    'phone': ctx.get('phone') or '',
                    'tz_attachment_url': (ctx.get('tz_attachment_url') or '').strip(),
                    'tz_file_name': (ctx.get('tz_file_name') or '').strip(),
                    'tz_comments': (ctx.get('tz_comments') or '').strip(),
                }
                fmt_hint = 'Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR (до 10 МБ).'
                if has_attachment and has_tz_format and tz_size_ok:
                    fn = ''
                    url = ''
                    if user_message.attachment:
                        att = user_message.attachment
                        fn = os.path.basename(getattr(att, 'name', '') or str(att))
                        try:
                            url = self.request.build_absolute_uri(att.url)
                        except Exception:
                            url = att.url if getattr(att, 'url', None) else ''
                    base_lead['tz_attachment_url'] = url
                    base_lead['tz_file_name'] = fn
                    liquid_installation_lead = base_lead
                    ask_comments = (
                        get_state('verification_installations_liquid_tz_comments').get('bot_message') or ''
                    )
                    label = fn or 'файл'
                    bot_response = (
                        f'Спасибо, техническое задание получено ({label}).\n\n{ask_comments}'.strip()
                    )
                    next_state = 'verification_installations_liquid_tz_comments'
                    hint_locked = True
                elif has_attachment and has_tz_format and not tz_size_ok:
                    liquid_installation_lead = base_lead
                    bot_response = (
                        f'Размер файла не должен превышать 10 МБ. Выберите другой файл '
                        f'или нажмите «Далее», если без вложения.\n\n{ask_tz}'
                    )
                    next_state = current_state
                    hint_locked = True
                elif has_attachment and not has_tz_format:
                    liquid_installation_lead = base_lead
                    bot_response = (
                        f'Недопустимый формат файла. {fmt_hint} Прикрепите файл кнопкой «📎» '
                        f'или нажмите «Далее».\n\n{ask_tz}'
                    )
                    next_state = current_state
                    hint_locked = True
                elif has_image:
                    liquid_installation_lead = base_lead
                    bot_response = (
                        f'Для ТЗ используйте вложение «📎» ({fmt_hint}). '
                        f'Или нажмите «Далее», если без файла.\n\n{ask_tz}'
                    )
                    next_state = current_state
                    hint_locked = True
                elif text:
                    liquid_installation_lead = base_lead
                    bot_response = (
                        'Чтобы отправить ТЗ, прикрепите файл кнопкой «📎». '
                        'Если документ не нужен — нажмите подсказку «Далее».\n\n' + ask_tz
                    )
                    next_state = current_state
                    hint_locked = True
                else:
                    liquid_installation_lead = base_lead
                    bot_response = ask_tz or f'Прикрепите файл ТЗ ({fmt_hint}) или нажмите «Далее».'
                    next_state = current_state
                    hint_locked = True
            elif current_state == 'verification_installations_liquid_tz_comments':
                text = (question or '').strip()
                ask_comments = (
                    get_state('verification_installations_liquid_tz_comments').get('bot_message') or ''
                )
                ctx = _parse_liquid_installation_lead(data)
                full_name = (ctx.get('full_name') or '').strip()
                if not full_name:
                    bot_response = (
                        'Не удалось восстановить данные анкеты. Нажмите «Вернуться» и пройдите шаги заново.'
                    )
                    next_state = 'verification_installations_liquid_tz'
                    hint_locked = True
                elif not text:
                    liquid_installation_lead = {
                        'full_name': full_name,
                        'email': ctx.get('email') or '',
                        'phone': ctx.get('phone') or '',
                        'tz_attachment_url': ctx.get('tz_attachment_url') or '',
                        'tz_file_name': ctx.get('tz_file_name') or '',
                        'tz_comments': '',
                    }
                    bot_response = ask_comments
                    next_state = current_state
                    hint_locked = True
                else:
                    comments = text
                    liquid_installation_lead = {
                        'full_name': full_name,
                        'email': ctx.get('email') or '',
                        'phone': ctx.get('phone') or '',
                        'tz_attachment_url': ctx.get('tz_attachment_url') or '',
                        'tz_file_name': ctx.get('tz_file_name') or '',
                        'tz_comments': comments,
                    }
                    next_state = 'verification_installations_liquid_after_tz'
                    next_state_data = get_state(next_state)
                    try:
                        from .submit_verification_liquid import (
                            resolve_liquid_tz_file_path,
                            submit_verification_liquid_request,
                        )

                        att_url = (liquid_installation_lead.get('tz_attachment_url') or '').strip()
                        tz_path = resolve_liquid_tz_file_path(chat_id, att_url)
                        email = (liquid_installation_lead.get('email') or '').strip()
                        phone = (liquid_installation_lead.get('phone') or '').strip()
                        contact = email if email else phone
                        submit_verification_liquid_result = submit_verification_liquid_request(
                            fullname=full_name,
                            contact=contact,
                            comment=comments,
                            tz_file_path=tz_path,
                        )
                    except Exception as e:
                        logger.exception('submit_verification_liquid_request')
                        submit_verification_liquid_result = {
                            'status': 'error',
                            'message': str(e),
                            'email_sent': False,
                        }
                    if (
                        isinstance(submit_verification_liquid_result, dict)
                        and submit_verification_liquid_result.get('status') == 'success'
                    ):
                        api_msg = (submit_verification_liquid_result.get('message') or '').strip()
                        bot_response = api_msg or 'Заявка успешно принята.'
                    else:
                        bot_response = next_state_data.get('bot_message') or ''
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
                'hints_only': next_state_data.get('hints_only', False),
                'hint_locked': hint_locked,  # Передаём состояние блокировки
            },
            'email_sent': email_sent,
            'order_specs_json': safe_order_specs,
            'order_specs_llm_response': order_specs_llm_response,
            'order_specs_ocr_text': order_specs_ocr_text,
            'verification_passed': verification_passed,
            'verified_contact': verified_contact,
            'liquid_installation_lead': liquid_installation_lead,
            'submit_verification_liquid': submit_verification_liquid_result,
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
            'hints_only': state_data.get('hints_only', False),
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
            'hints_only': next_state_data.get('hints_only', False),
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


def download_purs_questionnaire(request):
    """Отдаёт шаблон опросного листа ПУРС (.doc) для скачивания из чата (шаг ТЗ «жидкость»)."""
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent.parent / 'templates' / 'Опросный_лист_PURS.doc'
    if not path.is_file():
        raise Http404('Шаблон не найден')
    return FileResponse(
        path.open('rb'),
        as_attachment=True,
        filename='Опросный_лист_PURS.doc',
        content_type='application/msword',
    )
