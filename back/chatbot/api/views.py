# Image upload support added
import ipaddress
import json
import logging
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action, api_view
from rest_framework.views import APIView
from django.db.models import Count
from urllib.parse import quote

from django.conf import settings
from django.core.files import File
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET
from .models import Chat, Message
from .serializers import ChatSerializer, MessageSerializer

# Import hints tree
from .hints_tree import HINTS_TREE, get_state, get_next_state, get_parent_state

# Import email service
from .email_service import EmailValidator, EmailSender, extract_contact_info

logger = logging.getLogger(__name__)


def _mutable_request_post_data(request) -> dict:
    """
    Плоская копия POST-полей без deepcopy.
    request.data.copy() падает на multipart с файлами (BufferedRandom).
    """
    raw = request.data
    if hasattr(raw, "dict") and callable(raw.dict):
        data = raw.dict()
    else:
        data = dict(raw)
    for key in request.FILES:
        data.pop(key, None)
    return data


@require_GET
def equipment_media(request, relpath):
    """
    Отдаёт файлы из `back/templates/static/` (например картинки слайдера `equipment/...`).
    Нужен для Daphne/продакшена: встроенный `/static/` из STATICFILES_DIRS там часто не подключён.
    """
    rel = (relpath or "").strip().replace("\\", "/")
    if not rel:
        raise Http404
    for part in Path(rel).parts:
        if part in ("..", "") or part.startswith("."):
            raise Http404
    root = (Path(settings.BASE_DIR).parent / "templates" / "static").resolve()
    try:
        full = (root / rel).resolve()
        full.relative_to(root)
    except ValueError:
        raise Http404
    except OSError:
        raise Http404
    if not full.is_file():
        raise Http404
    content_type, _ = mimetypes.guess_type(str(full))
    return FileResponse(full.open("rb"), content_type=content_type or "application/octet-stream")


def _attachment_download_response(file_path: Path, download_name: str):
    if not file_path.is_file():
        raise Http404
    content_type, _ = mimetypes.guess_type(download_name or str(file_path))
    response = FileResponse(
        file_path.open("rb"),
        content_type=content_type or "application/octet-stream",
    )
    safe_name = (download_name or file_path.name or "attachment").replace('"', "")
    ascii_name = safe_name.encode("ascii", "ignore").decode("ascii") or "attachment.pdf"
    response["Content-Disposition"] = (
        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(safe_name)}'
    )
    return response


@require_GET
def message_attachment_download(request, message_id):
    """Скачивание вложения сообщения через API (работает за /podbor-api/)."""
    from .attachment_storage import resolve_message_attachment

    try:
        msg = Message.objects.get(pk=message_id)
    except Message.DoesNotExist:
        raise Http404
    file_path, download_name = resolve_message_attachment(msg)
    return _attachment_download_response(file_path, download_name)


@api_view(['GET'])
def service_centers_catalog(request):
    """Каталог сервисных центров (промышленная группа / Гранд) для виджета чата."""
    from .service_center_catalog import get_service_center_catalog

    return Response(get_service_center_catalog())


@require_GET
def faq_repair_memo_download(request):
    """Статическая памятка по ремонту (fallback, если media-файл недоступен)."""
    from .attachment_storage import REPAIR_MEMO_DOWNLOAD_NAME, static_faq_repair_memo_path

    return _attachment_download_response(static_faq_repair_memo_path(), REPAIR_MEMO_DOWNLOAD_NAME)


@require_GET
def knowledge_doc_download(request):
    """Скачивание PDF/документа базы знаний RAG по knowledge_doc_key."""
    from .knowledge_doc_storage import resolve_knowledge_document_path

    key = (request.GET.get("key") or "").strip()
    if not key:
        raise Http404
    file_path = resolve_knowledge_document_path(key)
    if not file_path:
        raise Http404
    return _attachment_download_response(file_path, file_path.name)


@require_GET
def chat_attachment_download(request, relpath):
    """Legacy/fallback: скачивание по пути в MEDIA_ROOT/chat_attachments/."""
    from .attachment_storage import (
        REPAIR_MEMO_DOWNLOAD_NAME,
        static_faq_repair_memo_path,
        _looks_like_repair_memo,
    )
    rel = (relpath or "").strip().replace("\\", "/")
    if not rel:
        raise Http404
    for part in Path(rel).parts:
        if part in ("..", "") or part.startswith("."):
            raise Http404
    root = Path(settings.MEDIA_ROOT).resolve() / "chat_attachments"
    try:
        full = (root / rel).resolve()
        full.relative_to(root)
    except ValueError:
        raise Http404
    except OSError:
        raise Http404
    download_name = Path(rel).name
    try:
        return _attachment_download_response(full, download_name)
    except Http404:
        if _looks_like_repair_memo(download_name):
            return _attachment_download_response(
                static_faq_repair_memo_path(),
                REPAIR_MEMO_DOWNLOAD_NAME,
            )
        raise


from .message_parsers import (
    LIQUID_TZ_MAX_BYTES,
    ORDER_SPECS_ATTACHMENT_EXTENSIONS,
    ORDER_SPECS_ATTACHMENT_MIME_TYPES,
    _handle_order_specs_text_message,
    _is_liquid_tz_upload,
    _is_order_specs_attachment_upload,
    _is_pdf_upload,
    _normalize_household_selected_items,
    _parse_equipment_for_price,
    _parse_gas_spu,
    _parse_gas_spu_application_lead,
    _parse_household_gas_lead,
    _parse_liquid_installation_lead,
    _parse_order_specs_edit_field,
    _parse_order_specs_for_price,
    _safe_print_order_specs_final,
    _transition_to_order_specs_confirm,
)

def get_order_specs_llm():
    """Deprecated: используйте order_specs_service.llm"""
    from .services.order_specs_service import order_specs_service

    return order_specs_service.llm


def reload_chatbot():
    """Перезагружает чатбот с новой конфигурацией"""
    from .services.rag_service import rag_service

    return rag_service.reload()


def generate_chat_title(messages):
    """Генерирует заголовок чата через LLM"""
    if not messages:
        return "Пустой чат"
    
    try:
        from .services.rag_service import rag_service

        bot = rag_service.get_bot()
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
        data = _mutable_request_post_data(request)
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
        data = _mutable_request_post_data(request)
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
        state_data = get_state(current_state)
        is_start_like = current_state == 'start' or state_data.get('is_final', False)

        from .services.message_flow_context import MessageFlowContext
        from .services.flow_router import MessageFlowRouter

        ctx = MessageFlowContext(
            chat_id=chat_id,
            request_data=data,
            question=question,
            current_state=current_state,
            is_hint_selection=is_hint_selection,
            hint_locked=hint_locked,
            state_data=state_data,
            is_start_like=is_start_like,
            image_file=image_file,
            attachment_file=attachment_file,
            user_message=user_message,
            http_request=request,
            order_specs_edit_field=_parse_order_specs_edit_field(data),
            next_state=current_state,
        )
        MessageFlowRouter.route(ctx)

        bot_response = ctx.bot_response
        next_state = ctx.next_state
        hint_locked = ctx.hint_locked
        order_specs_json = ctx.order_specs_json
        order_specs_preview = ctx.order_specs_preview
        order_specs_clarify_preview = ctx.order_specs_clarify_preview
        order_specs_llm_response = ctx.order_specs_llm_response
        order_specs_ocr_text = ctx.order_specs_ocr_text
        order_specs_pipeline_timing = ctx.order_specs_pipeline_timing
        rag_llm_ms = ctx.rag_llm_ms
        allow_empty_bot = ctx.allow_empty_bot
        suppress_chat_email = ctx.suppress_chat_email
        verification_passed = ctx.verification_passed
        verified_contact = ctx.verified_contact
        liquid_installation_lead = ctx.liquid_installation_lead
        submit_verification_liquid_result = ctx.submit_verification_liquid_result
        gas_spu_application_lead = ctx.gas_spu_application_lead
        submit_spu_application_result = ctx.submit_spu_application_result
        household_gas_lead = ctx.household_gas_lead
        submit_household_gas_result = ctx.submit_household_gas_result
        gas_spu_selection = ctx.gas_spu_selection
        gas_spu_card = ctx.gas_spu_card
        gas_spu_preview = ctx.gas_spu_preview
        faq_card = ctx.faq_card
        competitor_mask_card = ctx.competitor_mask_card
        competitor_comparison_card = ctx.competitor_comparison_card
        competitor_analog_specs = ctx.competitor_analog_specs
        competitor_analog_intro = ctx.competitor_analog_intro
        rag_sources = ctx.rag_sources
        _gas_hints = ctx.gas_hints
        _gas_expects = ctx.gas_expects

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
        bot_save_kw = {}
        bot_attachment_path = getattr(ctx, "bot_attachment_path", None)
        if bot_attachment_path:
            try:
                attachment_name = getattr(ctx, "bot_attachment_name", "") or Path(bot_attachment_path).name
                with open(bot_attachment_path, "rb") as fh:
                    bot_save_kw["attachment"] = File(fh, name=attachment_name)
                    bot_message = bot_serializer.save(**bot_save_kw)
            except OSError as e:
                print(f"[ERROR] Failed to attach bot file: {e}")
                bot_message = bot_serializer.save()
        else:
            bot_message = bot_serializer.save()

        # Получаем данные следующего состояния для фронтенда
        next_state_data = dict(get_state(next_state))
        if _gas_hints is not None:
            next_state_data['hints'] = _gas_hints
        if _gas_expects is not None:
            next_state_data['expects_input'] = _gas_expects

        # Письма менеджеру («обращение в чат») отключены. Письмо оператору — только
        # при завершении сценария техподдержки + учёт в аналитике.
        email_sent = False
        email_error = ""
        if (
            next_state == "tech_support_final"
            and next_state_data.get("is_final", False)
            and hint_locked
            and not suppress_chat_email
        ):
            try:
                chat = Chat.objects.get(pk=chat_id)
                chat_messages = chat.messages.all().order_by("created_at")
                all_messages = [
                    {
                        "content": msg.content,
                        "is_user": msg.is_user,
                        "created_at": msg.created_at,
                    }
                    for msg in chat_messages
                ]
                client_email, client_phone = extract_contact_info(question)
                email_sent, email_error = EmailSender.send_tech_support_notification(
                    messages=all_messages,
                    client_email=client_email,
                    client_phone=client_phone,
                    ip_address=chat.ip_address,
                    request_time=datetime.now(),
                    chat_id=chat_id,
                )
            except Exception as e:
                print(f"[ERROR] Failed to send tech support notification: {e}")
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

        safe_competitor_analog_specs = None
        if competitor_analog_specs is not None:
            try:
                from .order_specs_helpers import specs_for_api_response

                safe_competitor_analog_specs = specs_for_api_response(competitor_analog_specs)
            except Exception as e:
                print(f"[ERROR] competitor_analog_specs sanitize for response: {e}")
                safe_competitor_analog_specs = None

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
            'gas_spu_application_lead': gas_spu_application_lead,
            'submit_spu_application': submit_spu_application_result,
            'household_gas_lead': household_gas_lead,
            'submit_household_gas': submit_household_gas_result,
            'gas_spu_selection': gas_spu_selection,
            'gas_spu_card': gas_spu_card,
            'gas_spu_preview': gas_spu_preview,
            'faq_card': faq_card,
            'competitor_mask_card': competitor_mask_card,
            'competitor_comparison_card': competitor_comparison_card,
            'competitor_analog_specs': safe_competitor_analog_specs,
            'competitor_analog_intro': competitor_analog_intro,
            'order_specs_preview': order_specs_preview,
            'order_specs_clarify_preview': order_specs_clarify_preview,
            'order_specs_pipeline_timing': order_specs_pipeline_timing,
            'rag_llm_ms': rag_llm_ms if rag_llm_ms else None,
            'rag_sources': rag_sources if rag_sources else None,
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
        from .order_specs_navigation import FLOWMETER_HINT_STATES, resolve_flowmeter_back

        current_state = request.data.get('current_state', 'start')
        action = request.data.get('action', '')  # 'select_hint', 'back', 'free_input'
        hint_text = request.data.get('hint_text', '')
        bot_override = None
        back_extras: dict = {}

        if action == 'back':
            chat = None
            chat_id = request.data.get('chat_id')
            if chat_id:
                try:
                    chat = Chat.objects.filter(pk=int(chat_id)).first()
                except (TypeError, ValueError):
                    chat = None

            specs_snapshot = request.data.get("order_specs_snapshot")
            if isinstance(specs_snapshot, str):
                try:
                    import json as _json

                    specs_snapshot = _json.loads(specs_snapshot)
                except (TypeError, ValueError):
                    specs_snapshot = None
            if not isinstance(specs_snapshot, dict):
                specs_snapshot = None

            if current_state in FLOWMETER_HINT_STATES:
                next_state, bot_override, back_extras = resolve_flowmeter_back(
                    current_state, chat, specs_snapshot=specs_snapshot
                )
            else:
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
        bot_message = bot_override or next_state_data.get('bot_message') or ''

        payload = {
            'current_state': next_state,
            'bot_message': bot_message,
            'hints': next_state_data.get('hints', []),
            'show_back': next_state_data.get('show_back', False),
            'is_final': next_state_data.get('is_final', False),
            'expects_input': next_state_data.get('expects_input', False),
            'hints_only': next_state_data.get('hints_only', False),
        }
        if action == 'back':
            if back_extras.get('order_specs_json') is not None:
                payload['order_specs_json'] = back_extras['order_specs_json']
            if back_extras.get('order_specs_preview') is not None:
                payload['order_specs_preview'] = back_extras['order_specs_preview']
        return Response(payload)


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
