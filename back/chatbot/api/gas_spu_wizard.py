# -*- coding: utf-8 -*-
"""
Пошаговый подбор СПУ (газ): та же логика ветвления, что модалка на сайте.
Кнопки = текст подсказки; состояние — dict gas_spu_selection (поле step + параметры).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GAS_STATE = 'verification_installations_gas'

# Текст подсказки и кнопки на карточке — должен совпадать с проверкой во views.MessageViewSet
GAS_SPU_LEAVE_REQUEST = 'Оставить заявку →'


def _hint(text: str) -> Dict[str, str]:
    return {'text': text, 'next_state': GAS_STATE}


@dataclass
class GasSpuStepResult:
    ctx: Dict[str, Any]
    message: str
    hints: List[Dict[str, str]]
    expects_input: bool = False
    card: Optional[Dict[str, Any]] = None
    preview: Optional[Dict[str, Any]] = None  # {method, url, body, review_title?, review_rows?} на шаге review


def normalize_ctx(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c: Dict[str, Any] = dict(raw or {})
    if not c.get('step'):
        c['step'] = 'meter_type'
    ex = c.get('extras')
    if not isinstance(ex, dict):
        ex = {}
    c['extras'] = {
        'ps': bool(ex.get('ps')),
        'setter': ex.get('setter'),  # None | "v1" | "v2" | "v3"
    }
    return c


def spu_card_url() -> str:
    u = (getattr(settings, 'SPU_CARD_API_URL', None) or '').strip().rstrip('/')
    if u:
        return u
    origin = getattr(settings, 'VERIFICATION_SERVICE_ORIGIN', 'http://master-turbo-podbor.ru')
    return f"{str(origin).rstrip('/')}/api/spu/card"


def _spu_card_payload_is_success(body: Dict[str, Any]) -> bool:
    """Сервис карточки иногда отдаёт HTTP 200 и поля карточки без status=success."""
    if not isinstance(body, dict):
        return False
    st = body.get('status')
    if st in ('error', 'failed'):
        return False
    if st in ('success', 'ok'):
        return True
    if body.get('equipment_key'):
        return True
    titleish = (body.get('name') or body.get('title') or '').strip()
    if titleish and (
        body.get('image_url')
        or body.get('image_path')
        or body.get('type')
        or body.get('flow_range')
        or body.get('counters')
    ):
        return True
    return False


def post_spu_card(payload: Dict[str, Any], timeout: int = 45) -> Dict[str, Any]:
    url = spu_card_url()
    try:
        logger.info('post_spu_card: POST %s', url)
        r = requests.post(url, json=payload, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {'status': 'error', 'message': (r.text or '')[:800]}
        if not isinstance(body, dict):
            body = {'status': 'error', 'message': str(body)}
        body.setdefault('http_status', r.status_code)
        if 200 <= r.status_code < 300 and _spu_card_payload_is_success(body):
            body['status'] = 'success'
            # не тащим в ответ клиенту служебный текст «без поля message»
            if body.get('message', '').startswith('ответ сервиса карточки без поля'):
                body.pop('message', None)
        elif body.get('status') != 'success' and not (body.get('message') or body.get('error')):
            body['message'] = f'ответ сервиса карточки без поля message (HTTP {r.status_code})'
        logger.info(
            'post_spu_card: ответ HTTP %s status=%r',
            r.status_code,
            body.get('status'),
        )
        return body
    except Exception as e:
        logger.warning('post_spu_card failed: %s', e)
        return {'status': 'error', 'message': str(e)}


def _fmt_card_reply(api: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    if _spu_card_payload_is_success(api):
        parts = [
            (api.get('message') or '').strip(),
            (api.get('title') or api.get('name') or '').strip(),
            (api.get('summary') or api.get('description') or '').strip(),
        ]
        lines = [p for p in parts if p]
        if not lines:
            lines = ['Карточка подбора получена.']
        return '\n\n'.join(lines)
    err = api.get('message') or api.get('error')
    if not err:
        hs = api.get('http_status')
        err = (
            f'ответ без описания ошибки (HTTP {hs})'
            if hs is not None
            else 'Сервис карточки недоступен'
        )
    return f'Не удалось получить карточку: {err}'


def _build_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
    mt = ctx.get('meter_type')
    it = ctx.get('installation_type')
    if mt == 'domestic' and it == 'portable':
        body: Dict[str, Any] = {
            'meter_type': 'domestic',
            'installation_type': 'portable',
            'flow_range': ctx['flow_range'],
            'pressure_limit': str(ctx['pressure_limit']),
            'accuracy': str(ctx['accuracy']),
        }
        ex = ctx.get('extras') or {}
        if ex.get('ps'):
            body['optional_ps_sensor'] = True
        if ex.get('setter'):
            body['optional_setter'] = ex['setter']
        return body
    if mt == 'domestic' and it == 'stationary':
        return {
            'meter_type': 'domestic',
            'installation_type': 'stationary',
            'flow_range': ctx['flow_range'],
            'posts': str(int(ctx['posts'])),
            'lines': str(int(ctx['lines'])),
            'accuracy': '0.3',
        }
    if mt == 'industrial' and it == 'stationary':
        mod = ctx['modification']
        body = {
            'meter_type': 'industrial',
            'installation_type': 'stationary',
            'modification': mod,
            'diameter': int(ctx['diameter']),
        }
        if mod == 'nozzles':
            body['accuracy'] = str(ctx['accuracy'])
        return body
    raise ValueError('unsupported branch')


REVIEW_CONFIRM = 'Подобрать оборудование'
REVIEW_RESTART = 'Выбрать параметры заново'


REVIEW_UI_TITLE = 'Проверьте выбранные параметры'


def _make_preview(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'method': 'POST',
        'url': spu_card_url(),
        'body': dict(payload),
        'review_title': REVIEW_UI_TITLE,
        'review_rows': _review_checklist_rows(ctx),
    }


def _label_meter(mt: str) -> str:
    return {'domestic': 'Бытовые счётчики', 'industrial': 'Бытовые и промышленные счётчики'}.get(mt or '', mt)


def _label_install(it: str) -> str:
    return {'stationary': 'Стационарная', 'portable': 'Переносная'}.get(it or '', it)


def _label_flow_spu3(val: str) -> str:
    m = {
        '0.016-16': 'от 0,016 до 16 м³/ч',
        '0.25-25': 'от 0,25 до 25 м³/ч',
        '0.04-40': 'от 0,04 до 40 м³/ч',
        '0.1-100': 'от 0,1 до 100 м³/ч',
    }
    return m.get(val, val)


def _label_pressure(val: str) -> str:
    m = {
        '1.6': '1,6 кПа (спецзаказ)',
        '2.5': '2,5 кПа',
        '4': '4 кПа',
        '10': '10 кПа (спецзаказ)',
        '16': '16 кПа',
        '25': '25 кПа',
        '40': '40 кПа',
        '60': '60 кПа (спецзаказ)',
        '100': '100 кПа (спецзаказ)',
    }
    return m.get(str(val), str(val))


def _label_accuracy_spu3(val: str) -> str:
    return {'0.3': '±0,3%', '0.45': '±0,45% (спецзаказ)'}.get(str(val), str(val))


def _label_flow_spu5(val: str) -> str:
    return {'0.03-25': 'от 0,03 до 25 м³/ч', '0.03-70': 'от 0,03 до 70 м³/ч'}.get(val, val)


def _label_setter(st: Optional[str]) -> str:
    if not st:
        return 'не выбран'
    return {'v1': 'вариант 1', 'v2': 'вариант 2', 'v3': 'вариант 3'}.get(st, st)


def _review_checklist_rows(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """Пары label/value для UI проверки параметров (шаг review)."""
    mt, it = ctx.get('meter_type'), ctx.get('installation_type')
    rows: List[Dict[str, str]] = []
    if mt == 'domestic' and it == 'portable':
        rows.append({'key': 'line', 'label': 'Линейка', 'value': 'СПУ-3 (переносная, бытовые)'})
    elif mt == 'domestic' and it == 'stationary':
        rows.append({'key': 'line', 'label': 'Линейка', 'value': 'СПУ-5 (стационарная, бытовые)'})
    elif mt == 'industrial' and it == 'stationary':
        rows.append({'key': 'line', 'label': 'Линейка', 'value': 'СПУ-7 (стационарная, промышленные)'})

    rows.append({'key': 'meters', 'label': 'Тип счётчиков', 'value': _label_meter(mt)})
    rows.append({'key': 'install', 'label': 'Тип установки', 'value': _label_install(it)})

    if mt == 'domestic' and it == 'portable':
        rows.append(
            {'key': 'flow', 'label': 'Диапазон расхода', 'value': _label_flow_spu3(ctx.get('flow_range', ''))}
        )
        rows.append(
            {
                'key': 'pressure',
                'label': 'Предельное давление',
                'value': _label_pressure(ctx.get('pressure_limit', '')),
            }
        )
        rows.append(
            {
                'key': 'accuracy',
                'label': 'Погрешность',
                'value': _label_accuracy_spu3(str(ctx.get('accuracy', ''))),
            }
        )
        ex = ctx.get('extras') or {}
        rows.append({'key': 'ps', 'label': 'Датчик PS', 'value': 'да' if ex.get('ps') else 'нет'})
        rows.append({'key': 'setter', 'label': 'Задатчик расхода', 'value': _label_setter(ex.get('setter'))})
    elif mt == 'domestic' and it == 'stationary':
        rows.append(
            {'key': 'flow', 'label': 'Диапазон расхода', 'value': _label_flow_spu5(ctx.get('flow_range', ''))}
        )
        rows.append({'key': 'posts', 'label': 'Число постов', 'value': str(ctx.get('posts', ''))})
        rows.append({'key': 'lines', 'label': 'Число линий', 'value': str(ctx.get('lines', ''))})
        rows.append({'key': 'accuracy', 'label': 'Погрешность', 'value': '±0,3% (фиксирована для конфигурации)'})
    elif mt == 'industrial' and it == 'stationary':
        mod = ctx.get('modification')
        rows.append(
            {
                'key': 'mod',
                'label': 'Модификация',
                'value': 'сопла' if mod == 'nozzles' else 'мастер-счётчики' if mod == 'masters' else str(mod),
            }
        )
        if mod == 'nozzles':
            rows.append({'key': 'flow_card', 'label': 'Диапазон расхода (на карточке)', 'value': '0,016–1600 м³/ч'})
            rows.append(
                {
                    'key': 'accuracy',
                    'label': 'Погрешность',
                    'value': f'{ctx.get("accuracy")}% (±0,2 / 0,25 / 0,3)',
                }
            )
            rows.append({'key': 'si', 'label': 'Поверяемых СИ на линии', 'value': '1'})
        else:
            rows.append({'key': 'flow_card', 'label': 'Диапазон расхода (на карточке)', 'value': '0,016–5000 м³/ч'})
            rows.append({'key': 'accuracy_card', 'label': 'Погрешность (на карточке)', 'value': '±0,33%'})
            rows.append({'key': 'si', 'label': 'Поверяемых СИ', 'value': 'до 2'})
        rows.append({'key': 'diameter', 'label': 'Диаметр линии', 'value': f'DN {ctx.get("diameter")} мм'})
    return rows


def _review_intro_text() -> str:
    return (
        'Все параметры выбраны.\n\n'
        f'Если всё верно — нажмите «{REVIEW_CONFIRM}». '
        f'Чтобы пройти выбор заново — «{REVIEW_RESTART}».'
    )


def _enter_review(c: Dict[str, Any]) -> GasSpuStepResult:
    c = normalize_ctx(c)
    try:
        payload = _build_payload(c)
    except Exception as e:
        return GasSpuStepResult(
            ctx=c,
            message=f'Не удалось сформировать сводку параметров: {e}',
            hints=[_hint(REVIEW_RESTART)],
            preview=None,
        )
    c2 = dict(c)
    c2['step'] = 'review'
    c2['_pending_payload'] = payload
    return GasSpuStepResult(
        ctx=c2,
        message=_review_intro_text(),
        hints=[_hint(REVIEW_CONFIRM), _hint(REVIEW_RESTART)],
        preview=_make_preview(payload, c2),
    )


def _review_screen(c: Dict[str, Any]) -> GasSpuStepResult:
    c = normalize_ctx(c)
    try:
        payload = c.get('_pending_payload') or _build_payload(c)
    except Exception as e:
        return GasSpuStepResult(
            ctx=c,
            message=f'Не удалось восстановить параметры: {e}',
            hints=[_hint(REVIEW_RESTART)],
            preview=None,
        )
    c2 = dict(c)
    c2['step'] = 'review'
    c2['_pending_payload'] = payload
    return GasSpuStepResult(
        ctx=c2,
        message=_review_intro_text(),
        hints=[_hint(REVIEW_CONFIRM), _hint(REVIEW_RESTART)],
        preview=_make_preview(payload, c2),
    )


def _commit_card(c: Dict[str, Any]) -> GasSpuStepResult:
    c = normalize_ctx(c)
    payload = c.get('_pending_payload')
    if not payload:
        try:
            payload = _build_payload(c)
        except Exception as e:
            return GasSpuStepResult(
                ctx=c,
                message=f'Не удалось собрать запрос: {e}',
                hints=[_hint(REVIEW_CONFIRM), _hint(REVIEW_RESTART)],
                preview=None,
            )
    card = post_spu_card(payload)
    c2 = dict(c)
    c2['step'] = 'gas_done'
    c2['_last_payload'] = payload
    c2.pop('_pending_payload', None)
    snap: Dict[str, Any] = {}
    if isinstance(card, dict):
        for k in (
            'name',
            'title',
            'equipment_key',
            'equipment_id',
            'model',
            'type',
            'flow_range',
            'accuracy',
            'image_url',
            'image_path',
        ):
            if card.get(k) is not None and str(card.get(k)).strip() != '':
                snap[k] = card[k]
    if snap:
        c2['card_snapshot'] = snap
    return GasSpuStepResult(
        ctx=c2,
        message=_fmt_card_reply(card, c2),
        hints=[_hint(GAS_SPU_LEAVE_REQUEST), _hint('Новый подбор СПУ')],
        card=card,
        preview=None,
    )


def entry_after_menu() -> GasSpuStepResult:
    ctx: Dict[str, Any] = {'step': 'meter_type', 'extras': {'ps': False, 'setter': None}}
    return GasSpuStepResult(
        ctx=ctx,
        message=(
            'Подберём поверочную установку для газа по вашим условиям — как в калькуляторе на сайте.\n\n'
            'Уточните, пожалуйста, какие счётчики вы планируете поверять?'
        ),
        hints=[
            _hint('Бытовые счётчики'),
            _hint('Бытовые и промышленные счётчики'),
        ],
    )


def rerender(ctx: Dict[str, Any]) -> GasSpuStepResult:
    c = normalize_ctx(ctx)
    return apply_hint(c, None)


def apply_hint(ctx: Dict[str, Any], hint: Optional[str]) -> GasSpuStepResult:
    c = normalize_ctx(ctx)
    h = (hint or '').strip()
    if not h:
        return _rerender_current(c)

    if c.get('step') == 'gas_done':
        if h == 'Новый подбор СПУ':
            return entry_after_menu()
        return GasSpuStepResult(
            ctx=c,
            message=(
                f'Чтобы оформить заявку — нажмите «{GAS_SPU_LEAVE_REQUEST}». '
                'Для нового расчёта — «Новый подбор СПУ».'
            ),
            hints=[_hint(GAS_SPU_LEAVE_REQUEST), _hint('Новый подбор СПУ')],
        )

    if c.get('step') == 'review':
        if h == REVIEW_CONFIRM:
            return _commit_card(c)
        if h == REVIEW_RESTART:
            return entry_after_menu()
        return _review_screen(c)

    if c.get('step') == 'meter_type':
        if h == 'Бытовые счётчики':
            c['meter_type'] = 'domestic'
            c['step'] = 'installation_type'
            return _ask_installation(c)
        if h == 'Бытовые и промышленные счётчики':
            c['meter_type'] = 'industrial'
            c['step'] = 'installation_type'
            return _ask_installation(c)
        return entry_after_menu()

    if c.get('step') == 'installation_type':
        mt = c.get('meter_type')
        if h == 'Стационарная':
            c['installation_type'] = 'stationary'
            return _after_installation(c)
        if h == 'Переносная':
            if mt == 'industrial':
                return GasSpuStepResult(
                    ctx=c,
                    message=(
                        'Для промышленных счётчиков доступна только стационарная установка. '
                        'Выберите, пожалуйста, вариант ниже.'
                    ),
                    hints=[_hint('Стационарная')],
                )
            if mt == 'domestic':
                c['installation_type'] = 'portable'
                return _after_installation(c)
        return _ask_installation(c)

    if c.get('step') == 'spu3_flow':
        mapping = {
            'От 0,016 до 16 м³/ч': '0.016-16',
            'От 0,25 до 25 м³/ч': '0.25-25',
            'От 0,04 до 40 м³/ч': '0.04-40',
            'От 0,1 до 100 м³/ч': '0.1-100',
        }
        if h in mapping:
            c['flow_range'] = mapping[h]
            c['step'] = 'spu3_pressure'
            return _ask_spu3_pressure(c)
        return _ask_spu3_flow(c)

    if c.get('step') == 'spu3_pressure':
        pressures = {
            '1,6 кПа (спецзаказ)': '1.6',
            '2,5 кПа': '2.5',
            '4 кПа': '4',
            '10 кПа (спецзаказ)': '10',
            '16 кПа': '16',
            '25 кПа': '25',
            '40 кПа': '40',
            '60 кПа (спецзаказ)': '60',
            '100 кПа (спецзаказ)': '100',
        }
        if h in pressures:
            c['pressure_limit'] = pressures[h]
            c['step'] = 'spu3_accuracy'
            return _ask_spu3_accuracy(c)
        return _ask_spu3_pressure(c)

    if c.get('step') == 'spu3_accuracy':
        if h == '±0,3%':
            c['accuracy'] = '0.3'
            c['step'] = 'spu3_extras'
            return _ask_spu3_extras(c)
        if h == '±0,45% (спецзаказ)':
            c['accuracy'] = '0.45'
            c['step'] = 'spu3_extras'
            return _ask_spu3_extras(c)
        return _ask_spu3_accuracy(c)

    if c.get('step') == 'spu3_extras':
        if h == 'Подключить датчик PS':
            c['extras']['ps'] = True
            return _ask_spu3_extras(c)
        if h == 'Убрать датчик PS':
            c['extras']['ps'] = False
            return _ask_spu3_extras(c)
        if h == 'Без задатчиков расхода':
            c['extras']['setter'] = None
            return _ask_spu3_extras(c)
        if h == 'Задатчик расхода: вариант 1':
            c['extras']['setter'] = 'v1'
            return _ask_spu3_extras(c)
        if h == 'Задатчик расхода: вариант 2':
            c['extras']['setter'] = 'v2'
            return _ask_spu3_extras(c)
        if h == 'Задатчик расхода: вариант 3':
            c['extras']['setter'] = 'v3'
            return _ask_spu3_extras(c)
        if h == 'Перейти к проверке параметров':
            return _enter_review(c)
        return _ask_spu3_extras(c)

    if c.get('step') == 'spu5_flow':
        if h == 'От 0,03 до 25 м³/ч':
            c['flow_range'] = '0.03-25'
            c['step'] = 'spu5_posts'
            return _ask_spu5_posts(c)
        if h == 'От 0,03 до 70 м³/ч':
            c['flow_range'] = '0.03-70'
            c['step'] = 'spu5_posts'
            return _ask_spu5_posts(c)
        return _ask_spu5_flow(c)

    if c.get('step') == 'spu5_posts':
        pmap = {'6 постов': 6, '10 постов': 10, '15 постов': 15, '23 поста': 23}
        if h in pmap:
            c['posts'] = pmap[h]
            c['step'] = 'spu5_lines'
            return _ask_spu5_lines(c)
        return _ask_spu5_posts(c)

    if c.get('step') == 'spu5_lines':
        if h == '1 линия':
            c['lines'] = 1
            return _enter_review(c)
        if h == '2 линии':
            c['lines'] = 2
            return _enter_review(c)
        return _ask_spu5_lines(c)

    if c.get('step') == 'spu7_modification':
        if h == 'Сопла':
            c['modification'] = 'nozzles'
            c['step'] = 'spu7_noz_accuracy'
            return _ask_spu7_noz_accuracy(c)
        if h == 'Мастер-счётчики':
            c['modification'] = 'masters'
            c['step'] = 'spu7_mast_diam'
            return _ask_spu7_mast_diameter(c)
        return _ask_spu7_modification(c)

    if c.get('step') == 'spu7_noz_accuracy':
        amap = {'±0,2%': '0.2', '±0,25%': '0.25', '±0,3%': '0.3'}
        if h in amap:
            c['accuracy'] = amap[h]
            c['step'] = 'spu7_noz_diam'
            return _ask_spu7_noz_diameter(c)
        return _ask_spu7_noz_accuracy(c)

    if c.get('step') == 'spu7_noz_diam':
        dmap = _diameter_hints_nozzles()
        if h in dmap:
            c['diameter'] = dmap[h]
            return _enter_review(c)
        return _ask_spu7_noz_diameter(c)

    if c.get('step') == 'spu7_mast_diam':
        dmap = _diameter_hints_masters()
        if h in dmap:
            c['diameter'] = dmap[h]
            return _enter_review(c)
        return _ask_spu7_mast_diameter(c)

    return _rerender_current(c)


def _ask_installation(c: Dict[str, Any]) -> GasSpuStepResult:
    hints = [_hint('Стационарная')]
    if c.get('meter_type') == 'domestic':
        hints.append(_hint('Переносная'))
    return GasSpuStepResult(
        ctx=c,
        message=(
            'Спасибо. Какой тип установки вам подходит?\n\n'
            'Если вы поверяете только бытовые счётчики, можно выбрать переносную или стационарную конфигурацию. '
            'Для промышленных линейок доступна только стационарная установка.'
        ),
        hints=hints,
    )


def _after_installation(c: Dict[str, Any]) -> GasSpuStepResult:
    mt, it = c.get('meter_type'), c.get('installation_type')
    if mt == 'domestic' and it == 'portable':
        c['step'] = 'spu3_flow'
        return _ask_spu3_flow(c)
    if mt == 'domestic' and it == 'stationary':
        c['step'] = 'spu5_flow'
        msg = (
            'Для стационарной линейки СПУ-5 диапазон расходов и число постов задаются отдельно. '
            'Для выбранной конфигурации погрешность на карточке фиксирована: **±0,3%**.\n\n'
            'Уточните, пожалуйста, требуемый диапазон расходов.'
        )
        return _ask_spu5_flow_raw(c, msg)
    if mt == 'industrial' and it == 'stationary':
        c['step'] = 'spu7_modification'
        return _ask_spu7_modification(c)
    return _ask_installation(c)


def _ask_spu3_flow(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message=(
            'Отлично, это конфигурация уровня СПУ-3 (переносная для бытовых счётчиков).\n\n'
            'Уточните, пожалуйста, нужный диапазон расходов воздуха (как на сайте):'
        ),
        hints=[
            _hint('От 0,016 до 16 м³/ч'),
            _hint('От 0,25 до 25 м³/ч'),
            _hint('От 0,04 до 40 м³/ч'),
            _hint('От 0,1 до 100 м³/ч'),
        ],
    )


def _ask_spu3_pressure(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message='Выберите, пожалуйста, предельное давление (кПа). Пометка «спецзаказ» — как на сайте, уточняется при оформлении.',
        hints=[
            _hint('1,6 кПа (спецзаказ)'),
            _hint('2,5 кПа'),
            _hint('4 кПа'),
            _hint('10 кПа (спецзаказ)'),
            _hint('16 кПа'),
            _hint('25 кПа'),
            _hint('40 кПа'),
            _hint('60 кПа (спецзаказ)'),
            _hint('100 кПа (спецзаказ)'),
        ],
    )


def _ask_spu3_accuracy(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message='Укажите, пожалуйста, требуемую относительную погрешность:',
        hints=[_hint('±0,3%'), _hint('±0,45% (спецзаказ)')],
    )


def _ask_spu3_extras(c: Dict[str, Any]) -> GasSpuStepResult:
    ex = c.get('extras') or {}
    ps_on = ex.get('ps')
    st = ex.get('setter')
    summary = []
    if ps_on:
        summary.append('датчик PS — да')
    else:
        summary.append('датчик PS — нет')
    if st:
        summary.append(f'задатчик расхода — {_label_setter(st)}')
    else:
        summary.append('задатчики расхода — не выбраны')
    msg = (
        'По желанию можно уточнить дополнительную комплектацию (как на сайте). '
        'Этот шаг не обязателен — затем можно перейти к проверке параметров перед запросом карточки.\n\n'
        f'Сейчас: {", ".join(summary)}.\n\n'
        'Выберите опции кнопками (типы задатчиков взаимоисключающие):'
    )
    hints: List[Dict[str, str]] = []
    hints.append(_hint('Подключить датчик PS') if not ps_on else _hint('Убрать датчик PS'))
    hints.extend(
        [
            _hint('Без задатчиков расхода'),
            _hint('Задатчик расхода: вариант 1'),
            _hint('Задатчик расхода: вариант 2'),
            _hint('Задатчик расхода: вариант 3'),
            _hint('Перейти к проверке параметров'),
        ]
    )
    return GasSpuStepResult(ctx=c, message=msg, hints=hints)


def _ask_spu5_flow_raw(c: Dict[str, Any], message: str) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message=message,
        hints=[_hint('От 0,03 до 25 м³/ч'), _hint('От 0,03 до 70 м³/ч')],
    )


def _ask_spu5_flow(c: Dict[str, Any]) -> GasSpuStepResult:
    msg = (
        'Для стационарной линейки СПУ-5 погрешность для этой конфигурации фиксирована: ±0,3% '
        '(отдельно спрашивать не нужно).\n\n'
        'Уточните, пожалуйста, требуемый диапазон расходов.'
    )
    return _ask_spu5_flow_raw(c, msg)


def _ask_spu5_posts(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message='Укажите, пожалуйста, число постов на установке:',
        hints=[
            _hint('6 постов'),
            _hint('10 постов'),
            _hint('15 постов'),
            _hint('23 поста'),
        ],
    )


def _ask_spu5_lines(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message='Сколько измерительных линий должно быть предусмотрено?',
        hints=[_hint('1 линия'), _hint('2 линии')],
    )


def _ask_spu7_modification(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message=(
            'Для промышленной стационарной линейки (СПУ-7) уточните, пожалуйста, модификацию установки — '
            'сопла или мастер-счётчики.'
        ),
        hints=[_hint('Сопла'), _hint('Мастер-счётчики')],
    )


def _ask_spu7_noz_accuracy(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message=(
            'Для варианта «Сопла» диапазон расходов на карточке фиксирован: **0,016–1600 м³/ч** (дополнительно не спрашиваем). '
            'Поверяемых СИ на линии: **1**.\n\n'
            'Выберите, пожалуйста, требуемую погрешность:'
        ),
        hints=[_hint('±0,2%'), _hint('±0,25%'), _hint('±0,3%')],
    )


def _diameter_hints_nozzles() -> Dict[str, int]:
    labels = [15, 20, 25, 32, 40, 50, 80, 100, 150, 200]
    return {f'DN {d} мм': d for d in labels}


def _ask_spu7_noz_diameter(c: Dict[str, Any]) -> GasSpuStepResult:
    hints = [_hint(k) for k in _diameter_hints_nozzles().keys()]
    return GasSpuStepResult(
        ctx=c,
        message='Укажите, пожалуйста, условный диаметр линии (мм):',
        hints=hints,
    )


def _diameter_hints_masters() -> Dict[str, int]:
    labels = [15, 20, 25, 32, 40, 50, 80, 100, 150, 200, 250]
    return {f'DN {d} мм': d for d in labels}


def _ask_spu7_mast_diameter(c: Dict[str, Any]) -> GasSpuStepResult:
    return GasSpuStepResult(
        ctx=c,
        message=(
            'Для варианта «Мастер-счётчики» диапазон расходов фиксирован: **0,016–5000 м³/ч**, '
            'погрешность **±0,33%**; до **2** поверяемых СИ.\n\n'
            'Уточните, пожалуйста, диаметр линии:'
        ),
        hints=[_hint(k) for k in _diameter_hints_masters().keys()],
    )


def _rerender_current(c: Dict[str, Any]) -> GasSpuStepResult:
    c = normalize_ctx(c)
    s = c.get('step', 'meter_type')
    if s == 'meter_type':
        return entry_after_menu()
    if s == 'installation_type':
        return _ask_installation(c)
    if s == 'spu3_flow':
        return _ask_spu3_flow(c)
    if s == 'spu3_pressure':
        return _ask_spu3_pressure(c)
    if s == 'spu3_accuracy':
        return _ask_spu3_accuracy(c)
    if s == 'spu3_extras':
        return _ask_spu3_extras(c)
    if s == 'spu5_flow':
        return _ask_spu5_flow(c)
    if s == 'spu5_posts':
        return _ask_spu5_posts(c)
    if s == 'spu5_lines':
        return _ask_spu5_lines(c)
    if s == 'spu7_modification':
        return _ask_spu7_modification(c)
    if s == 'spu7_noz_accuracy':
        return _ask_spu7_noz_accuracy(c)
    if s == 'spu7_noz_diam':
        return _ask_spu7_noz_diameter(c)
    if s == 'spu7_mast_diam':
        return _ask_spu7_mast_diameter(c)
    if s == 'review':
        return _review_screen(c)
    if s == 'gas_done':
        return GasSpuStepResult(
            ctx=c,
            message='Подбор завершён. Можно начать сначала кнопкой ниже.',
            hints=[_hint('Новый подбор СПУ')],
        )
    return entry_after_menu()
