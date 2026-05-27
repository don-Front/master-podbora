"""Обработка сценариев верификации, бытового газа и заявок СПУ."""

from __future__ import annotations

import logging
import os

from ..email_service import EmailValidator
from ..hints_tree import get_state
from ..message_parsers import (
    LIQUID_TZ_MAX_BYTES,
    _is_liquid_tz_upload,
    _parse_gas_spu,
    _parse_gas_spu_application_lead,
    _parse_household_gas_lead,
    _parse_liquid_installation_lead,
)
from .message_flow_context import MessageFlowContext

logger = logging.getLogger(__name__)

_VERIFICATION_STATES = frozenset(
    {
        'verification_installations_gas',
        'household_gas_fullname',
        'household_gas_contact',
        'household_gas_organization',
        'household_gas_comment',
        'verification_installations_liquid',
        'verification_installations_liquid_contact',
        'verification_installations_liquid_tz',
        'verification_installations_liquid_tz_comments',
        'verification_installations_gas_application',
        'verification_installations_gas_application_contact',
        'verification_installations_gas_application_tz',
        'verification_installations_gas_application_tz_comments',
    }
)


class VerificationFlowHandler:
    @staticmethod
    def handles(state: str) -> bool:
        return state in _VERIFICATION_STATES

    @staticmethod
    def handle(ctx: MessageFlowContext) -> None:
        state = ctx.current_state
        data = ctx.request_data
        question = ctx.question
        chat_id = ctx.chat_id
        attachment_file = ctx.attachment_file
        image_file = ctx.image_file
        user_message = ctx.user_message
        http_request = ctx.http_request

        if state == 'verification_installations_gas':
            from ..gas_spu_wizard import rerender as gas_rerender

            ctx.next_state = 'verification_installations_gas'
            ctx.hint_locked = True
            gctx = _parse_gas_spu(data)
            gr = gas_rerender(gctx)
            ctx.gas_spu_selection = gr.ctx
            ctx.bot_response = gr.message
            ctx.gas_hints = gr.hints
            ctx.gas_expects = gr.expects_input
            ctx.gas_spu_card = gr.card
            ctx.gas_spu_preview = gr.preview

        elif state == 'household_gas_fullname':
            text = (question or '').strip()
            ask_fio = get_state('household_gas_fullname').get('bot_message') or ''
            lead_ctx = _parse_household_gas_lead(data)
            selected_items = lead_ctx.get('selected_items') or []
            if not selected_items:
                ctx.bot_response = 'Не удалось восстановить выбранные позиции. Вернитесь к прайс-листу и выберите счётчики заново.'
                ctx.next_state = 'equipment_household_gas_dev'
                ctx.hint_locked = True
                ctx.household_gas_lead = {
                    'full_name': '',
                    'email': '',
                    'phone': '',
                    'organization': '',
                    'comment': '',
                    'selected_items': [],
                }
            elif not text:
                ctx.bot_response = ask_fio
                ctx.next_state = state
                ctx.hint_locked = True
                ctx.household_gas_lead = {**lead_ctx, 'selected_items': selected_items}
            else:
                normalized = ' '.join(text.split())
                parts = [p for p in normalized.replace('-', ' ').split(' ') if p]
                if len(parts) < 3 or len(normalized) < 10:
                    ctx.bot_response = (
                        'Пожалуйста, введите полное ФИО: фамилию, имя и отчество '
                        'тремя словами через пробел (дефис в фамилии допускается).\n\n'
                        f'{ask_fio}'
                    )
                    ctx.next_state = state
                    ctx.hint_locked = True
                    ctx.household_gas_lead = {**lead_ctx, 'selected_items': selected_items}
                else:
                    ctx.household_gas_lead = {
                        'full_name': normalized,
                        'email': '',
                        'phone': '',
                        'organization': '',
                        'comment': '',
                        'selected_items': selected_items,
                    }
                    ctx.next_state = 'household_gas_contact'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'household_gas_contact':
            text = (question or '').strip()
            ask_contact = get_state('household_gas_contact').get('bot_message') or ''
            lead_ctx = _parse_household_gas_lead(data)
            full_name = (lead_ctx.get('full_name') or '').strip()
            selected_items = lead_ctx.get('selected_items') or []
            if not full_name or not selected_items:
                ctx.bot_response = 'Не удалось восстановить данные заявки. Вернитесь к прайс-листу и пройдите шаги заново.'
                ctx.next_state = 'equipment_household_gas_dev'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_contact
                ctx.next_state = state
                ctx.hint_locked = True
                ctx.household_gas_lead = {**lead_ctx, 'selected_items': selected_items}
            else:
                ok, err, kind, norm = EmailValidator.validate_email_format_or_phone_ru(text)
                if not ok:
                    ctx.bot_response = f'{err}\n\n{ask_contact}'
                    ctx.next_state = state
                    ctx.hint_locked = True
                    ctx.household_gas_lead = {**lead_ctx, 'selected_items': selected_items}
                else:
                    ctx.household_gas_lead = {
                        **lead_ctx,
                        'email': norm if kind == 'email' else '',
                        'phone': norm if kind == 'phone' else '',
                        'selected_items': selected_items,
                    }
                    ctx.next_state = 'household_gas_organization'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'household_gas_organization':
            text = (question or '').strip()
            ask_org = get_state('household_gas_organization').get('bot_message') or ''
            lead_ctx = _parse_household_gas_lead(data)
            selected_items = lead_ctx.get('selected_items') or []
            if not (lead_ctx.get('full_name') or '').strip() or not selected_items:
                ctx.bot_response = 'Не удалось восстановить данные заявки. Вернитесь к прайс-листу и пройдите шаги заново.'
                ctx.next_state = 'equipment_household_gas_dev'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_org
                ctx.next_state = state
                ctx.hint_locked = True
                ctx.household_gas_lead = {**lead_ctx, 'selected_items': selected_items}
            else:
                organization = '' if text.lower() in ('-', 'нет', 'не указана', 'без организации') else ' '.join(text.split())
                ctx.household_gas_lead = {
                    **lead_ctx,
                    'organization': organization,
                    'selected_items': selected_items,
                }
                ctx.next_state = 'household_gas_comment'
                next_state_data = get_state(ctx.next_state)
                ctx.bot_response = next_state_data.get('bot_message') or ''
                ctx.hint_locked = True

        elif state == 'household_gas_comment':
            text = (question or '').strip()
            ask_comment = get_state('household_gas_comment').get('bot_message') or ''
            lead_ctx = _parse_household_gas_lead(data)
            full_name = (lead_ctx.get('full_name') or '').strip()
            email = (lead_ctx.get('email') or '').strip()
            phone = (lead_ctx.get('phone') or '').strip()
            selected_items = lead_ctx.get('selected_items') or []
            if not full_name or not selected_items or not (email or phone):
                ctx.bot_response = 'Не удалось восстановить данные заявки. Вернитесь к прайс-листу и пройдите шаги заново.'
                ctx.next_state = 'equipment_household_gas_dev'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_comment
                ctx.next_state = state
                ctx.hint_locked = True
                ctx.household_gas_lead = {**lead_ctx, 'selected_items': selected_items}
            else:
                comment = '' if text.lower() in ('-', 'нет') else text
                ctx.household_gas_lead = {
                    **lead_ctx,
                    'comment': comment,
                    'selected_items': selected_items,
                }
                ctx.next_state = 'household_gas_after_submit'
                next_state_data = get_state(ctx.next_state)
                contact = email if email else phone
                try:
                    from ..submit_household_gas import submit_household_gas_request

                    ctx.submit_household_gas_result = submit_household_gas_request(
                        fullname=full_name,
                        contact=contact,
                        comment=comment,
                        organization=lead_ctx.get('organization') or '',
                        phone=phone,
                        email=email,
                        selected_items=selected_items,
                    )
                except Exception as e:
                    logger.exception('submit_household_gas_request')
                    ctx.submit_household_gas_result = {'status': 'error', 'message': str(e)}
                if (
                    isinstance(ctx.submit_household_gas_result, dict)
                    and ctx.submit_household_gas_result.get('status') == 'success'
                ):
                    api_msg = (ctx.submit_household_gas_result.get('message') or '').strip()
                    ctx.bot_response = api_msg or 'Заявка успешно принята.'
                else:
                    api_msg = (
                        ctx.submit_household_gas_result.get('message')
                        if isinstance(ctx.submit_household_gas_result, dict)
                        else ''
                    )
                    ctx.bot_response = api_msg or next_state_data.get('bot_message') or ''
                ctx.hint_locked = True

        elif state == 'verification_installations_liquid':
            text = (question or '').strip()
            ask_fio = get_state('verification_installations_liquid').get('bot_message') or ''
            if not text:
                ctx.bot_response = ask_fio
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                normalized = ' '.join(text.split())
                parts = [p for p in normalized.replace('-', ' ').split(' ') if p]
                if len(parts) < 3 or len(normalized) < 10:
                    ctx.bot_response = (
                        'Пожалуйста, введите полное ФИО: фамилию, имя и отчество '
                        'тремя словами через пробел (дефис в фамилии допускается).\n\n'
                        f'{ask_fio}'
                    )
                    ctx.next_state = state
                    ctx.hint_locked = True
                else:
                    ctx.liquid_installation_lead = {
                        'full_name': normalized,
                        'email': '',
                        'phone': '',
                        'tz_attachment_url': '',
                        'tz_file_name': '',
                        'tz_comments': '',
                    }
                    ctx.next_state = 'verification_installations_liquid_contact'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'verification_installations_liquid_contact':
            text = (question or '').strip()
            ask_contact = (
                get_state('verification_installations_liquid_contact').get('bot_message') or ''
            )
            lead_ctx = _parse_liquid_installation_lead(data)
            full_name = (lead_ctx.get('full_name') or '').strip()
            if not full_name:
                ctx.bot_response = (
                    'Не удалось восстановить ФИО. Нажмите «Вернуться» и снова введите фамилию, имя и отчество.'
                )
                ctx.next_state = 'verification_installations_liquid'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_contact
                ctx.next_state = state
                ctx.hint_locked = True
                ctx.liquid_installation_lead = {
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
                    ctx.bot_response = f'{err}\n\n{ask_contact}'
                    ctx.next_state = state
                    ctx.hint_locked = True
                    ctx.liquid_installation_lead = {
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
                    ctx.liquid_installation_lead = {
                        'full_name': full_name,
                        'email': email,
                        'phone': phone,
                        'tz_attachment_url': '',
                        'tz_file_name': '',
                        'tz_comments': '',
                    }
                    ctx.next_state = 'verification_installations_liquid_tz'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'verification_installations_liquid_tz':
            has_attachment = bool(attachment_file)
            has_tz_format = _is_liquid_tz_upload(attachment_file)
            tz_size = int(getattr(attachment_file, 'size', 0) or 0) if attachment_file else 0
            tz_size_ok = tz_size <= LIQUID_TZ_MAX_BYTES
            has_image = bool(image_file)
            text = (question or '').strip()
            ask_tz = get_state('verification_installations_liquid_tz').get('bot_message') or ''
            lead_ctx = _parse_liquid_installation_lead(data)
            base_lead = {
                'full_name': lead_ctx.get('full_name') or '',
                'email': lead_ctx.get('email') or '',
                'phone': lead_ctx.get('phone') or '',
                'tz_attachment_url': (lead_ctx.get('tz_attachment_url') or '').strip(),
                'tz_file_name': (lead_ctx.get('tz_file_name') or '').strip(),
                'tz_comments': (lead_ctx.get('tz_comments') or '').strip(),
            }
            fmt_hint = 'Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR (до 10 МБ).'
            if has_attachment and has_tz_format and tz_size_ok:
                fn = ''
                url = ''
                if user_message.attachment:
                    att = user_message.attachment
                    fn = os.path.basename(getattr(att, 'name', '') or str(att))
                    try:
                        url = http_request.build_absolute_uri(att.url)
                    except Exception:
                        url = att.url if getattr(att, 'url', None) else ''
                base_lead['tz_attachment_url'] = url
                base_lead['tz_file_name'] = fn
                ctx.liquid_installation_lead = base_lead
                ask_comments = (
                    get_state('verification_installations_liquid_tz_comments').get('bot_message') or ''
                )
                label = fn or 'файл'
                ctx.bot_response = (
                    f'Спасибо, техническое задание получено ({label}).\n\n{ask_comments}'.strip()
                )
                ctx.next_state = 'verification_installations_liquid_tz_comments'
                ctx.hint_locked = True
            elif has_attachment and has_tz_format and not tz_size_ok:
                ctx.liquid_installation_lead = base_lead
                ctx.bot_response = (
                    f'Размер файла не должен превышать 10 МБ. Выберите другой файл '
                    f'или нажмите «Далее», если без вложения.\n\n{ask_tz}'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif has_attachment and not has_tz_format:
                ctx.liquid_installation_lead = base_lead
                ctx.bot_response = (
                    f'Недопустимый формат файла. {fmt_hint} Прикрепите файл кнопкой «📎» '
                    f'или нажмите «Далее».\n\n{ask_tz}'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif has_image:
                ctx.liquid_installation_lead = base_lead
                ctx.bot_response = (
                    f'Для ТЗ используйте вложение «📎» ({fmt_hint}). '
                    f'Или нажмите «Далее», если без файла.\n\n{ask_tz}'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif text:
                ctx.liquid_installation_lead = base_lead
                ctx.bot_response = (
                    'Чтобы отправить ТЗ, прикрепите файл кнопкой «📎». '
                    'Если документ не нужен — нажмите подсказку «Далее».\n\n' + ask_tz
                )
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                ctx.liquid_installation_lead = base_lead
                ctx.bot_response = ask_tz or f'Прикрепите файл ТЗ ({fmt_hint}) или нажмите «Далее».'
                ctx.next_state = state
                ctx.hint_locked = True

        elif state == 'verification_installations_liquid_tz_comments':
            text = (question or '').strip()
            ask_comments = (
                get_state('verification_installations_liquid_tz_comments').get('bot_message') or ''
            )
            lead_ctx = _parse_liquid_installation_lead(data)
            full_name = (lead_ctx.get('full_name') or '').strip()
            if not full_name:
                ctx.bot_response = (
                    'Не удалось восстановить данные анкеты. Нажмите «Вернуться» и пройдите шаги заново.'
                )
                ctx.next_state = 'verification_installations_liquid_tz'
                ctx.hint_locked = True
            elif not text:
                ctx.liquid_installation_lead = {
                    'full_name': full_name,
                    'email': lead_ctx.get('email') or '',
                    'phone': lead_ctx.get('phone') or '',
                    'tz_attachment_url': lead_ctx.get('tz_attachment_url') or '',
                    'tz_file_name': lead_ctx.get('tz_file_name') or '',
                    'tz_comments': '',
                }
                ctx.bot_response = ask_comments
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                comments = text
                ctx.liquid_installation_lead = {
                    'full_name': full_name,
                    'email': lead_ctx.get('email') or '',
                    'phone': lead_ctx.get('phone') or '',
                    'tz_attachment_url': lead_ctx.get('tz_attachment_url') or '',
                    'tz_file_name': lead_ctx.get('tz_file_name') or '',
                    'tz_comments': comments,
                }
                ctx.next_state = 'verification_installations_liquid_after_tz'
                next_state_data = get_state(ctx.next_state)
                try:
                    from ..submit_verification_liquid import (
                        resolve_liquid_tz_file_path,
                        submit_verification_liquid_request,
                    )

                    att_url = (ctx.liquid_installation_lead.get('tz_attachment_url') or '').strip()
                    tz_path = resolve_liquid_tz_file_path(chat_id, att_url)
                    email = (ctx.liquid_installation_lead.get('email') or '').strip()
                    phone = (ctx.liquid_installation_lead.get('phone') or '').strip()
                    contact = email if email else phone
                    ctx.submit_verification_liquid_result = submit_verification_liquid_request(
                        fullname=full_name,
                        contact=contact,
                        comment=comments,
                        tz_file_path=tz_path,
                    )
                except Exception as e:
                    logger.exception('submit_verification_liquid_request')
                    ctx.submit_verification_liquid_result = {
                        'status': 'error',
                        'message': str(e),
                        'email_sent': False,
                    }
                if (
                    isinstance(ctx.submit_verification_liquid_result, dict)
                    and ctx.submit_verification_liquid_result.get('status') == 'success'
                ):
                    api_msg = (ctx.submit_verification_liquid_result.get('message') or '').strip()
                    ctx.bot_response = api_msg or 'Заявка успешно принята.'
                else:
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                ctx.hint_locked = True

        elif state == 'verification_installations_gas_application':
            gctx = _parse_gas_spu(data)
            ctx.gas_spu_selection = gctx
            text = (question or '').strip()
            ask_fio = get_state('verification_installations_gas_application').get('bot_message') or ''
            if not gctx or gctx.get('step') != 'gas_done':
                ctx.bot_response = (
                    'Не найдены параметры подобранной установки. Нажмите «Вернуться» и оформите заявку '
                    'ещё раз после появления карточки.'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_fio
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                normalized = ' '.join(text.split())
                parts = [p for p in normalized.replace('-', ' ').split(' ') if p]
                if len(parts) < 3 or len(normalized) < 10:
                    ctx.bot_response = (
                        'Пожалуйста, введите полное ФИО: фамилию, имя и отчество '
                        'тремя словами через пробел (дефис в фамилии допускается).\n\n'
                        f'{ask_fio}'
                    )
                    ctx.next_state = state
                    ctx.hint_locked = True
                else:
                    ctx.gas_spu_application_lead = {
                        'full_name': normalized,
                        'email': '',
                        'phone': '',
                        'tz_attachment_url': '',
                        'tz_file_name': '',
                        'tz_comments': '',
                    }
                    ctx.next_state = 'verification_installations_gas_application_contact'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'verification_installations_gas_application_contact':
            gctx = _parse_gas_spu(data)
            ctx.gas_spu_selection = gctx
            text = (question or '').strip()
            ask_contact = (
                get_state('verification_installations_gas_application_contact').get('bot_message') or ''
            )
            lead_ctx = _parse_gas_spu_application_lead(data)
            full_name = (lead_ctx.get('full_name') or '').strip()
            if not gctx or gctx.get('step') != 'gas_done':
                ctx.bot_response = (
                    'Не найдены параметры подобранной установки. Нажмите «Вернуться» и пройдите шаги заново.'
                )
                ctx.next_state = 'verification_installations_gas_application'
                ctx.hint_locked = True
            elif not full_name:
                ctx.bot_response = (
                    'Не удалось восстановить ФИО. Нажмите «Вернуться» и снова введите фамилию, имя и отчество.'
                )
                ctx.next_state = 'verification_installations_gas_application'
                ctx.hint_locked = True
            elif not text:
                ctx.bot_response = ask_contact
                ctx.next_state = state
                ctx.hint_locked = True
                ctx.gas_spu_application_lead = {
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
                    ctx.bot_response = f'{err}\n\n{ask_contact}'
                    ctx.next_state = state
                    ctx.hint_locked = True
                    ctx.gas_spu_application_lead = {
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
                    ctx.gas_spu_application_lead = {
                        'full_name': full_name,
                        'email': email,
                        'phone': phone,
                        'tz_attachment_url': '',
                        'tz_file_name': '',
                        'tz_comments': '',
                    }
                    ctx.next_state = 'verification_installations_gas_application_tz'
                    next_state_data = get_state(ctx.next_state)
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                    ctx.hint_locked = True

        elif state == 'verification_installations_gas_application_tz':
            gctx = _parse_gas_spu(data)
            ctx.gas_spu_selection = gctx
            has_attachment = bool(attachment_file)
            has_tz_format = _is_liquid_tz_upload(attachment_file)
            tz_size = int(getattr(attachment_file, 'size', 0) or 0) if attachment_file else 0
            tz_size_ok = tz_size <= LIQUID_TZ_MAX_BYTES
            has_image = bool(image_file)
            text = (question or '').strip()
            ask_tz = get_state('verification_installations_gas_application_tz').get('bot_message') or ''
            lead_ctx = _parse_gas_spu_application_lead(data)
            base_lead = {
                'full_name': lead_ctx.get('full_name') or '',
                'email': lead_ctx.get('email') or '',
                'phone': lead_ctx.get('phone') or '',
                'tz_attachment_url': (lead_ctx.get('tz_attachment_url') or '').strip(),
                'tz_file_name': (lead_ctx.get('tz_file_name') or '').strip(),
                'tz_comments': (lead_ctx.get('tz_comments') or '').strip(),
            }
            fmt_hint = 'Допустимые форматы: PDF, DOC, DOCX, TXT, ZIP, RAR (до 10 МБ).'
            if not gctx or gctx.get('step') != 'gas_done':
                ctx.bot_response = 'Сессия подбора устарела. Вернитесь и оформите заявку заново.'
                ctx.next_state = 'verification_installations_gas'
                ctx.hint_locked = True
            elif has_attachment and has_tz_format and tz_size_ok:
                fn = ''
                url = ''
                if user_message.attachment:
                    att = user_message.attachment
                    fn = os.path.basename(getattr(att, 'name', '') or str(att))
                    try:
                        url = http_request.build_absolute_uri(att.url)
                    except Exception:
                        url = att.url if getattr(att, 'url', None) else ''
                base_lead['tz_attachment_url'] = url
                base_lead['tz_file_name'] = fn
                ctx.gas_spu_application_lead = base_lead
                ask_comments = (
                    get_state('verification_installations_gas_application_tz_comments').get('bot_message')
                    or ''
                )
                label = fn or 'файл'
                ctx.bot_response = (
                    f'Спасибо, техническое задание получено ({label}).\n\n{ask_comments}'.strip()
                )
                ctx.next_state = 'verification_installations_gas_application_tz_comments'
                ctx.hint_locked = True
            elif has_attachment and has_tz_format and not tz_size_ok:
                ctx.gas_spu_application_lead = base_lead
                ctx.bot_response = (
                    f'Размер файла не должен превышать 10 МБ. Выберите другой файл '
                    f'или нажмите «Далее», если без вложения.\n\n{ask_tz}'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif has_attachment and not has_tz_format:
                ctx.gas_spu_application_lead = base_lead
                ctx.bot_response = (
                    f'Недопустимый формат файла. {fmt_hint} Прикрепите файл кнопкой «📎» '
                    f'или нажмите «Далее».\n\n{ask_tz}'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif has_image:
                ctx.gas_spu_application_lead = base_lead
                ctx.bot_response = (
                    f'Для ТЗ используйте вложение «📎» ({fmt_hint}). '
                    f'Или нажмите «Далее», если без файла.\n\n{ask_tz}'
                )
                ctx.next_state = state
                ctx.hint_locked = True
            elif text:
                ctx.gas_spu_application_lead = base_lead
                ctx.bot_response = (
                    'Чтобы отправить ТЗ, прикрепите файл кнопкой «📎». '
                    'Если документ не нужен — нажмите подсказку «Далее».\n\n' + ask_tz
                )
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                ctx.gas_spu_application_lead = base_lead
                ctx.bot_response = ask_tz or f'Прикрепите файл ТЗ ({fmt_hint}) или нажмите «Далее».'
                ctx.next_state = state
                ctx.hint_locked = True

        elif state == 'verification_installations_gas_application_tz_comments':
            gctx = _parse_gas_spu(data)
            ctx.gas_spu_selection = gctx
            text = (question or '').strip()
            ask_comments = (
                get_state('verification_installations_gas_application_tz_comments').get('bot_message')
                or ''
            )
            lead_ctx = _parse_gas_spu_application_lead(data)
            full_name = (lead_ctx.get('full_name') or '').strip()
            if not gctx or gctx.get('step') != 'gas_done':
                ctx.bot_response = 'Сессия подбора устарела. Пройдите сценарий заново.'
                ctx.next_state = 'verification_installations_gas'
                ctx.hint_locked = True
            elif not full_name:
                ctx.bot_response = (
                    'Не удалось восстановить данные анкеты. Нажмите «Вернуться» и пройдите шаги заново.'
                )
                ctx.next_state = 'verification_installations_gas_application_tz'
                ctx.hint_locked = True
            elif not text:
                ctx.gas_spu_application_lead = {
                    'full_name': full_name,
                    'email': lead_ctx.get('email') or '',
                    'phone': lead_ctx.get('phone') or '',
                    'tz_attachment_url': lead_ctx.get('tz_attachment_url') or '',
                    'tz_file_name': lead_ctx.get('tz_file_name') or '',
                    'tz_comments': '',
                }
                ctx.bot_response = ask_comments
                ctx.next_state = state
                ctx.hint_locked = True
            else:
                comments = text
                ctx.gas_spu_application_lead = {
                    'full_name': full_name,
                    'email': lead_ctx.get('email') or '',
                    'phone': lead_ctx.get('phone') or '',
                    'tz_attachment_url': lead_ctx.get('tz_attachment_url') or '',
                    'tz_file_name': lead_ctx.get('tz_file_name') or '',
                    'tz_comments': comments,
                }
                ctx.next_state = 'verification_installations_gas_application_after_tz'
                next_state_data = get_state(ctx.next_state)
                try:
                    from ..submit_spu_application import submit_spu_application_request
                    from ..submit_verification_liquid import resolve_liquid_tz_file_path

                    att_url = (ctx.gas_spu_application_lead.get('tz_attachment_url') or '').strip()
                    tz_path = resolve_liquid_tz_file_path(chat_id, att_url)
                    email = (ctx.gas_spu_application_lead.get('email') or '').strip()
                    phone = (ctx.gas_spu_application_lead.get('phone') or '').strip()
                    contact = email if email else phone
                    ctx.submit_spu_application_result = submit_spu_application_request(
                        fullname=full_name,
                        contact=contact,
                        comment=comments,
                        gas_spu_selection=gctx,
                        tz_file_path=tz_path,
                    )
                except Exception as e:
                    logger.exception('submit_spu_application_request')
                    ctx.submit_spu_application_result = {
                        'status': 'error',
                        'message': str(e),
                    }
                if (
                    isinstance(ctx.submit_spu_application_result, dict)
                    and ctx.submit_spu_application_result.get('status') == 'success'
                ):
                    api_msg = (ctx.submit_spu_application_result.get('message') or '').strip()
                    ctx.bot_response = api_msg or 'Заявка успешно принята.'
                else:
                    ctx.bot_response = next_state_data.get('bot_message') or ''
                ctx.hint_locked = True
