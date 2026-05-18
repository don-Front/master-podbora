import { resolveEquipmentImageUrl } from '../config';

const FLOW_RANGE_LABELS = {
  '0.016-16': 'от 0,016 до 16 м³/ч',
  '0.25-25': 'от 0,25 до 25 м³/ч',
  '0.04-40': 'от 0,04 до 40 м³/ч',
  '0.1-100': 'от 0,1 до 100 м³/ч',
  '0.03-25': 'от 0,03 до 25 м³/ч',
  '0.03-70': 'от 0,03 до 70 м³/ч',
};

const PRESSURE_LABELS = {
  1.6: '1,6 кПа',
  2.5: '2,5 кПа',
  4: '4 кПа',
  10: '10 кПа',
  16: '16 кПа',
  25: '25 кПа',
  40: '40 кПа',
  60: '60 кПа',
  100: '100 кПа',
};

function labelFlowRange(key) {
  if (key == null || key === '') return '';
  const k = String(key);
  return FLOW_RANGE_LABELS[k] || k;
}

function labelPressure(v) {
  if (v == null || v === '') return '';
  const n = Number(v);
  if (!Number.isNaN(n) && PRESSURE_LABELS[n] != null) return PRESSURE_LABELS[n];
  const s = String(v);
  return PRESSURE_LABELS[s] || `${s.replace('.', ',')} кПа`;
}

function labelAccuracy(a) {
  if (a == null || a === '') return '';
  const s = String(a);
  if (s === '0.3') return '±0,3%';
  if (s === '0.45') return '±0,45%';
  if (s === '0.2') return '±0,2%';
  if (s === '0.25') return '±0,25%';
  return s.includes('%') ? s : `±${s.replace('.', ',')}%`;
}

/** Карточка от сервиса без явной ошибки и с данными для показа. */
export function gasSpuCardLooksValid(card) {
  if (!card || typeof card !== 'object') return false;
  if (card.status === 'error' || card.status === 'failed') return false;
  return Boolean(
    (card.name || card.title || '').trim() || (card.equipment_key && String(card.equipment_key).trim())
  );
}

/**
 * Только параметры, которые пользователь прошёл в мастере (по полям selection).
 * Подписи диапазонов/давления — как в визарде; числовые поля из выбора пользователя.
 */
export function buildGasSpuUserSpecRows(selection, card) {
  const rows = [];
  if (!selection || typeof selection !== 'object') return rows;

  const it = selection.installation_type;
  const mt = selection.meter_type;

  if (it === 'stationary') rows.push({ key: 'install', label: 'Тип', value: 'Стационарная' });
  else if (it === 'portable') rows.push({ key: 'install', label: 'Тип', value: 'Переносная' });

  if (mt === 'domestic') rows.push({ key: 'meters', label: 'Счётчики', value: 'Бытовые' });
  else if (mt === 'industrial') {
    rows.push({ key: 'meters', label: 'Счётчики', value: 'Бытовые и промышленные' });
  }

  if (selection.flow_range) {
    const fromCard = card && card.flow_range && String(card.flow_range).trim();
    rows.push({
      key: 'flow',
      label: 'Диапазон расходов',
      value: fromCard || labelFlowRange(selection.flow_range),
    });
  }

  if (selection.posts != null && selection.posts !== '') {
    rows.push({ key: 'posts', label: 'Количество постов', value: String(selection.posts) });
  }
  if (selection.lines != null && selection.lines !== '') {
    rows.push({ key: 'lines', label: 'Линий подключения', value: String(selection.lines) });
  }

  if (selection.pressure_limit != null && selection.pressure_limit !== '') {
    rows.push({
      key: 'pressure',
      label: 'Предельное давление',
      value: labelPressure(selection.pressure_limit),
    });
  }

  if (selection.accuracy != null && selection.accuracy !== '') {
    rows.push({
      key: 'accuracy',
      label: 'Погрешность',
      value: (card && card.accuracy && String(card.accuracy).trim()) || labelAccuracy(selection.accuracy),
    });
  } else if (mt === 'domestic' && it === 'stationary') {
    rows.push({
      key: 'accuracy',
      label: 'Погрешность',
      value: (card && card.accuracy && String(card.accuracy).trim()) || '±0,3%',
    });
  } else if (card && card.accuracy && String(card.accuracy).trim() && mt === 'industrial') {
    rows.push({ key: 'accuracy', label: 'Погрешность', value: String(card.accuracy).trim() });
  }

  if (selection.modification === 'nozzles' || selection.modification === 'masters') {
    rows.push({
      key: 'mod',
      label: 'Модификация',
      value: selection.modification === 'nozzles' ? 'Сопла' : 'Мастер-счётчики',
    });
  }

  if (selection.diameter != null && selection.diameter !== '') {
    rows.push({ key: 'dn', label: 'Диаметр линии', value: `DN ${selection.diameter} мм` });
  }

  const ex = selection.extras || {};
  if (ex.ps) rows.push({ key: 'ps', label: 'Датчик PS', value: 'Подключён' });
  if (ex.setter) {
    const map = { v1: 'вариант 1', v2: 'вариант 2', v3: 'вариант 3' };
    rows.push({
      key: 'setter',
      label: 'Задатчик расхода',
      value: map[ex.setter] || String(ex.setter),
    });
  }

  return rows;
}

export function resolveGasSpuCardImageUrl(card) {
  if (!card) return '';
  const u = card.image_url != null && String(card.image_url).trim();
  if (u) return u;
  return resolveEquipmentImageUrl(card.image_path);
}

/**
 * Если пришла карточка СПУ после подбора — показываем виджет вместо голого текста.
 */
export function enhanceBotMessageWithGasSpuCard(botMsg, response) {
  if (botMsg?.kind === 'gas_spu_review') return botMsg;
  const content = (botMsg.text || '').trim();
  if (content.startsWith('Не удалось получить карточку')) return botMsg;

  const sel = response?.data?.gas_spu_selection;
  const card = response?.data?.gas_spu_card;
  if (sel?.step !== 'gas_done' || !gasSpuCardLooksValid(card)) return botMsg;

  const rows = buildGasSpuUserSpecRows(sel, card);
  return {
    ...botMsg,
    kind: 'gas_spu_card',
    gasSpuCard: card,
    gasSpuSpecRows: rows,
    text: '',
  };
}

/** Шаг проверки параметров перед POST карточки: список из API (gas_spu_preview.review_rows). */
export function enhanceBotMessageWithGasSpuReview(botMsg, response) {
  const prev = response?.data?.gas_spu_preview;
  const rows = prev?.review_rows;
  if (!Array.isArray(rows) || rows.length === 0) return botMsg;
  const title = (prev?.review_title || 'Проверьте выбранные параметры').trim();
  return {
    ...botMsg,
    kind: 'gas_spu_review',
    gasSpuReviewTitle: title,
    gasSpuReviewRows: rows,
  };
}

export function GasSpuReviewBlock({ title, rows, headingId }) {
  const hid = headingId || 'gas-spu-review-heading';
  return (
    <div className="chat-widget__gas-spu-review" role="region" aria-labelledby={hid}>
      <h3 id={hid} className="chat-widget__gas-spu-review-title">
        {title}
      </h3>
      <div className="chat-widget__gas-spu-review-rows" role="list">
        {rows.map((row, i) => (
          <div
            key={row.key || `gas-spu-review-${i}`}
            className="chat-widget__gas-spu-review-row"
            role="listitem"
          >
            <span className="chat-widget__gas-spu-review-label">{row.label}</span>
            <span className="chat-widget__gas-spu-review-value">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function GasSpuResultCard({ card, specRows, onLeaveRequest, leaveBusy }) {
  const title = (card?.name || card?.title || '').trim();
  const src = resolveGasSpuCardImageUrl(card);
  const showBtn = typeof onLeaveRequest === 'function';

  return (
    <div className={showBtn ? 'chat-widget__gas-spu-card-outer' : ''}>
      <div className="chat-widget__gas-spu-card" role="article" aria-label={title || 'Карточка подбора СПУ'}>
        {src ? (
          <div className="chat-widget__gas-spu-card-image-wrap">
            <img className="chat-widget__gas-spu-card-img" src={src} alt="" loading="lazy" />
          </div>
        ) : null}
        {title ? <h3 className="chat-widget__gas-spu-card-title">{title}</h3> : null}
        {specRows?.length ? (
          <div className="chat-widget__gas-spu-card-specs">
            {specRows.map((row) => (
              <div key={row.key} className="chat-widget__gas-spu-card-spec">
                <div className="chat-widget__gas-spu-card-spec-label">{row.label}</div>
                <div className="chat-widget__gas-spu-card-spec-value">{row.value}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {showBtn ? (
        <button
          type="button"
          className="chat-widget__gas-spu-card-cta"
          disabled={leaveBusy}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onLeaveRequest();
          }}
        >
          Оставить заявку →
        </button>
      ) : null}
    </div>
  );
}
