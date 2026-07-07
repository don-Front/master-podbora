"""Обработка сценария «Получить цену» (equipment_price_*)."""

from __future__ import annotations

import logging

from django.conf import settings

from ..email_service import EmailValidator
from ..hints_tree import get_state
from ..message_parsers import _parse_equipment_for_price, _parse_order_specs_for_price
from ..models import Chat
from ..verification_client import send_verification_code, verify_code as verify_email_code
from .message_flow_context import MessageFlowContext

logger = logging.getLogger(__name__)

_PRICE_STATES = frozenset(
    {
        'equipment_price_phone',
        'equipment_price_email',
        'equipment_price_verify_code',
    }
)


class PriceFlowHandler:
    @staticmethod
    def handles(state: str) -> bool:
        return state in _PRICE_STATES

    @staticmethod
    def can_start_from_slider(ctx: MessageFlowContext) -> bool:
        """
        Запрос цены со слайдера аналогов конкурента: hint_state ещё start,
        но фронт передаёт equipment_for_price + order_specs_for_price.
        """
        if ctx.current_state != "start":
            return False
        eq_obj = _parse_equipment_for_price(ctx.request_data)
        if not eq_obj:
            return False
        label = (eq_obj.get("model") or eq_obj.get("name") or "").strip()
        if not label:
            return False
        specs = _parse_order_specs_for_price(ctx.request_data)
        return bool(specs)

    @staticmethod
    def handle_price_hint(ctx: MessageFlowContext) -> None:
        data = ctx.request_data
        eq_obj = _parse_equipment_for_price(data)
        label = ''
        if eq_obj:
            label = (eq_obj.get('model') or eq_obj.get('name') or '').strip()
        if not eq_obj or not label:
            ctx.next_state = ctx.current_state
            ctx.bot_response = (
                'Не удалось определить прибор на слайдере. Пролистайте карточку и нажмите '
                '«Получить цену» ещё раз.'
            )
            ctx.hint_locked = True
        else:
            try:
                ch = Chat.objects.get(pk=ctx.chat_id)
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
                ctx.next_state = 'equipment_price_phone'
                ctx.bot_response = get_state(ctx.next_state).get('bot_message') or ''
                ctx.suppress_chat_email = True
                ctx.hint_locked = True
            except Chat.DoesNotExist:
                ctx.bot_response = 'Сессия чата устарела. Начните диалог заново.'
                ctx.next_state = 'start'
                ctx.hint_locked = False

    @staticmethod
    def handle(ctx: MessageFlowContext) -> None:
        state = ctx.current_state
        data = ctx.request_data
        question = ctx.question
        chat_id = ctx.chat_id

        if state == 'equipment_price_phone':
            text = (question or '').strip()
            phone_st = get_state('equipment_price_phone')
            ask_phone = phone_st.get('bot_message') or ''
            chat = Chat.objects.filter(pk=chat_id).first()
            _debug_skip_price = data.get('debug_skip_equipment_price_verify')
            if isinstance(_debug_skip_price, str):
                _debug_skip_price = _debug_skip_price.lower() in ('1', 'true', 'yes', 'on')
            if _debug_skip_price is True and settings.DEBUG:
                if not chat or not chat.price_quote_draft:
                    ctx.bot_response = (
                        'Сессия запроса цены устарела. Выберите прибор на слайдере и снова нажмите '
                        '«Получить цену».'
                    )
                    ctx.next_state = 'order_final'
                    ctx.hint_locked = True
                else:
                    draft = dict(chat.price_quote_draft)
                    draft['phone'] = '+7 (928) 777-77-77'
                    draft['email'] = 'tfdjccyi@trashlify.com'
                    chat.price_quote_draft = None
                    chat.save(update_fields=['price_quote_draft'])
                    eq = draft.get('equipment') or {}
                    label = (eq.get('model') or eq.get('name') or '').strip() or 'прибор'
                    em_disp = draft.get('email') or ''
                    ph_disp = draft.get('phone') or ''
                    ctx.bot_response = (
                        f'Спасибо! Почта подтверждена. Запрос цены на «{label}» передан менеджеру; '
                        f'ожидайте связи по телефону {ph_disp} или на {em_disp}.'
                    )
                    ctx.next_state = 'order_final'
                    ctx.suppress_chat_email = True
                    ctx.verification_passed = True
                    ctx.verified_contact = {
                        'phone': ph_disp,
                        'email': em_disp,
                    }
                    ctx.hint_locked = True
                    logger.warning(
                        '[DEBUG] Пропуск верификации запроса цены (equipment_price_phone), chat_id=%s',
                        chat_id,
                    )
            elif not chat or not chat.price_quote_draft:
                ctx.bot_response = (
                    'Сессия запроса цены устарела. Выберите прибор на слайдере и снова нажмите «Получить цену».'
                )
                ctx.next_state = 'order_final'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_phone
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                ok, err, pretty = EmailValidator.validate_phone_ru(text)
                if not ok:
                    ctx.bot_response = f'{err}\n\n{ask_phone}'
                    ctx.next_state = state
                    ctx.hint_locked = True
                else:
                    draft = dict(chat.price_quote_draft)
                    draft['phone'] = pretty
                    chat.price_quote_draft = draft
                    chat.save(update_fields=['price_quote_draft'])
                    ctx.next_state = 'equipment_price_email'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'equipment_price_email':
            text = (question or '').strip()
            email_st = get_state('equipment_price_email')
            ask_email = email_st.get('bot_message') or ''
            chat = Chat.objects.filter(pk=chat_id).first()
            if not chat or not chat.price_quote_draft:
                ctx.bot_response = (
                    'Сессия запроса цены устарела. Начните с кнопки «Получить цену» у слайдера приборов.'
                )
                ctx.next_state = 'order_final'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_email
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                ok, err = EmailValidator.validate_email(text)
                if not ok:
                    ctx.bot_response = f'{err}\n\n{ask_email}'
                    ctx.next_state = state
                    ctx.hint_locked = True
                else:
                    draft = dict(chat.price_quote_draft)
                    em = text.strip().lower()
                    draft['email'] = em
                    sent_ok, sent_err = send_verification_code(em)
                    if not sent_ok:
                        ctx.bot_response = (
                            f'Не удалось отправить код на почту: {sent_err}\n\n{ask_email}'
                        )
                        ctx.next_state = state
                        ctx.hint_locked = True
                        chat.price_quote_draft = draft
                        chat.save(update_fields=['price_quote_draft'])
                    else:
                        chat.price_quote_draft = draft
                        chat.save(update_fields=['price_quote_draft'])
                        ctx.next_state = 'equipment_price_verify_code'
                        next_state_data = get_state(ctx.next_state)
                        ctx.bot_response = next_state_data.get('bot_message') or ''
                        ctx.hint_locked = True

        elif state == 'equipment_price_verify_code':
            text = (question or '').strip()
            verify_st = get_state('equipment_price_verify_code')
            ask_code = verify_st.get('bot_message') or ''
            chat = Chat.objects.filter(pk=chat_id).first()
            if not chat or not chat.price_quote_draft:
                ctx.bot_response = (
                    'Сессия запроса цены устарела. Начните с кнопки «Получить цену» у слайдера приборов.'
                )
                ctx.next_state = 'order_final'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_code
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                em = (chat.price_quote_draft.get('email') or '').strip().lower()
                if not em:
                    ctx.bot_response = (
                        'Не удалось восстановить адрес почты. Укажите email ещё раз.'
                    )
                    ctx.next_state = 'equipment_price_email'
                    ctx.hint_locked = True
                elif len(text) != 6 or not text.isdigit():
                    ctx.bot_response = (
                        f'Код должен состоять из 6 цифр. Повторите ввод.\n\n{ask_code}'
                    )
                    ctx.next_state = state
                    ctx.hint_locked = True
                else:
                    vok, verr = verify_email_code(em, text)
                    if not vok:
                        ctx.bot_response = f'{verr}\n\n{ask_code}'
                        ctx.next_state = state
                        ctx.hint_locked = True
                    else:
                        draft = dict(chat.price_quote_draft)
                        chat.price_quote_draft = None
                        chat.save(update_fields=['price_quote_draft'])
                        eq = draft.get('equipment') or {}
                        label = (eq.get('model') or eq.get('name') or '').strip() or 'прибор'
                        em_disp = draft.get('email') or em
                        ctx.bot_response = (
                            f'Спасибо! Почта подтверждена. Запрос цены на «{label}» передан менеджеру; '
                            f'ожидайте связи по телефону {draft.get("phone", "")} или на {em_disp}.'
                        )
                        ctx.next_state = 'order_final'
                        ctx.suppress_chat_email = True
                        ctx.verification_passed = True
                        ctx.verified_contact = {
                            'phone': draft.get('phone') or '',
                            'email': em_disp,
                        }
                        ctx.hint_locked = True
