/**
 * Таблица итоговых параметров спецификации (шаг order_specs_confirm).
 */
import { useMemo } from 'react';
import { detectOrderSpecsRangeIssues } from '../utils/orderSpecsRangeWarnings';
import {
  enhanceBotMessageWithGasSpuCard,
  enhanceBotMessageWithGasSpuReview,
} from './gasSpuResultCard';
import { enhanceBotMessageWithOrderSpecsClarify } from './OrderSpecsTextClarify';

export const FLOW_MAX_AT_25_ROW_KEY = 'flowMaxAt25ms';

const COMPUTED_ROW_KEYS = new Set([FLOW_MAX_AT_25_ROW_KEY]);

/** Число из отображаемого значения («100 мм», «7,35 МПа»). */
function parseNumberFromSpec(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const s = String(value).trim().replace(/,/g, '.');
  const matches = s.match(/-?\d+(?:\.\d+)?/g);
  if (!matches?.length) return null;
  const nums = matches.map((m) => Number(m)).filter((n) => Number.isFinite(n));
  return nums.length ? nums[0] : null;
}

/** 2.83 × 0.001 × 25 × d² (d — диаметр в мм). */
export function computeMaxFlowAt25ms(diameterMm) {
  const d = parseNumberFromSpec(diameterMm);
  if (d == null) return null;
  return 2.83 * 0.001 * 25 * d * d;
}

function formatMaxFlowAt25Display(rows) {
  const diameterRow = rows.find((r) => r.key === 'diameter');
  const flowUnitRow = rows.find((r) => r.key === 'flow_unit');
  const flowUnit = (flowUnitRow?.value || '').trim() || 'ст.м³/ч';
  const computed = computeMaxFlowAt25ms(diameterRow?.value);
  if (computed == null) return '—';
  const formatted = computed.toLocaleString('ru-RU', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${formatted} ${flowUnit}`;
}

/** Вставляет вычисляемую строку сразу после «Максимальный расход». */
export function buildOrderSpecsDisplayRows(rows, flowMaxAt25Enabled) {
  if (!Array.isArray(rows)) return [];
  const baseRows = rows.filter((row) => !COMPUTED_ROW_KEYS.has(row?.key));
  if (!flowMaxAt25Enabled) return baseRows;

  const computedRow = {
    key: FLOW_MAX_AT_25_ROW_KEY,
    label: 'Макс. расход при скорости 25 м/с',
    value: formatMaxFlowAt25Display(baseRows),
    computed: true,
  };

  const flowMaxIdx = baseRows.findIndex((r) => r.key === 'flowMax');
  if (flowMaxIdx < 0) return [...baseRows, computedRow];

  const next = [...baseRows];
  next.splice(flowMaxIdx + 1, 0, computedRow);
  return next;
}

export function isComputedOrderSpecRow(row) {
  return Boolean(row?.computed) || COMPUTED_ROW_KEYS.has(row?.key);
}

function SpeedGaugeIcon() {
  return (
    <svg
      className="order-specs-confirm__flow-max-toggle-icon"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <circle cx="12" cy="13" r="8" stroke="currentColor" strokeWidth="1.5" />
      <path d="M12 13V7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M12 13l4.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M6 4h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function WarningTriangleIcon() {
  return (
    <svg
      className="order-specs-confirm__qmax-hint-icon"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M12 3.5 20.5 19.5H3.5L12 3.5Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <path d="M12 9v5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      <circle cx="12" cy="16.25" r="0.9" fill="currentColor" />
    </svg>
  );
}

function QmaxHintPanel({ qmaxHint }) {
  if (!qmaxHint) return null;

  if (qmaxHint.loading) {
    return (
      <div className="order-specs-confirm__qmax-hint order-specs-confirm__qmax-hint--loading" role="status">
        Загрузка подсказки по максимальному расходу…
      </div>
    );
  }

  const data = qmaxHint.data;
  if (!data || data.status !== 'success') return null;

  const messages = data.messages || {};
  const recommended = messages.recommended_diameter;
  const maxFlow = messages.max_flow;
  if (!recommended && !maxFlow) return null;

  const warn = Boolean(qmaxHint.isWarning);

  return (
    <div
      className={`order-specs-confirm__qmax-hint${warn ? ' order-specs-confirm__qmax-hint--warn' : ''}`}
      role="note"
      aria-live="polite"
    >
      {warn ? (
        <div className="order-specs-confirm__qmax-hint-head">
          <WarningTriangleIcon />
          <span className="order-specs-confirm__qmax-hint-title">Превышение макс. расхода</span>
        </div>
      ) : null}
      {recommended ? (
        <p className="order-specs-confirm__qmax-hint-line">{recommended}</p>
      ) : null}
      {maxFlow ? <p className="order-specs-confirm__qmax-hint-line">{maxFlow}</p> : null}
      {warn ? (
        <p className="order-specs-confirm__qmax-hint-warn">
          Введённый максимальный расход выше допустимого — проверьте параметры.
        </p>
      ) : null}
    </div>
  );
}

function OrderSpecsRangeWarningsPanel({ rows }) {
  const issues = useMemo(() => detectOrderSpecsRangeIssues(rows), [rows]);
  if (!issues.length) return null;

  return (
    <div className="order-specs-confirm__range-warn" role="note" aria-live="polite">
      <ul className="order-specs-confirm__range-warn-list">
        {issues.map((issue) => (
          <li key={issue.id} className="order-specs-confirm__range-warn-item">
            <span className="order-specs-confirm__range-warn-hint">{issue.hint}</span>
            {' — '}
            <span className="order-specs-confirm__range-warn-values">
              сейчас{' '}
              <span className="order-specs-confirm__range-warn-value">{issue.minText}</span>
              {' > '}
              <span className="order-specs-confirm__range-warn-value">{issue.maxText}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FlowMaxAt25Toggle({ enabled, onToggle, disabled }) {
  return (
    <div className="order-specs-confirm__flow-max-widget">
      <div className="order-specs-confirm__flow-max-widget-head">
        <span className="order-specs-confirm__flow-max-widget-badge">Виджет</span>
        <span className="order-specs-confirm__flow-max-widget-headline">Дополнительный расчёт</span>
      </div>
      <button
        type="button"
        className={`order-specs-confirm__flow-max-toggle${enabled ? ' order-specs-confirm__flow-max-toggle--selected' : ''}`}
        onClick={onToggle}
        disabled={disabled}
        aria-pressed={enabled}
        title="Показать или скрыть расчётный максимальный расход при скорости 25 м/с"
      >
        <SpeedGaugeIcon />
        <span className="order-specs-confirm__flow-max-toggle-label">
          Максимальный расход при скорости 25 м/с
        </span>
        <span className="order-specs-confirm__flow-max-toggle-state" aria-hidden="true">
          {enabled ? 'Вкл.' : 'Выкл.'}
        </span>
      </button>
      <p className="order-specs-confirm__flow-max-widget-hint">
        {enabled
          ? 'Строка «Макс. расход при скорости 25 м/с» добавлена в таблицу. Нажмите ещё раз, чтобы скрыть её. Значение пересчитывается автоматически при изменении диаметра.'
          : 'Нажмите, чтобы добавить в таблицу строку «Макс. расход при скорости 25 м/с». Повторный клик скроет строку.'}
      </p>
    </div>
  );
}

function PencilIcon() {
  return (
    <svg
      className="order-specs-confirm__edit-icon"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M4 20h4l10.5-10.5a1.5 1.5 0 0 0 0-2.12l-2.38-2.38a1.5 1.5 0 0 0-2.12 0L4 15.5V20z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13.5 6.5l4 4"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function OrderSpecsConfirmTable({
  title,
  rows,
  footer,
  onEditRow,
  editBusy,
  flowMaxAt25Enabled = false,
  onFlowMaxAt25Toggle,
  qmaxHint = null,
}) {
  const headingId = 'order-specs-confirm-heading';
  const displayRows = useMemo(
    () => buildOrderSpecsDisplayRows(rows, flowMaxAt25Enabled),
    [rows, flowMaxAt25Enabled],
  );
  const showFlowMaxToggle = typeof onFlowMaxAt25Toggle === 'function';

  return (
    <div className="order-specs-confirm" role="region" aria-labelledby={headingId}>
      <h3 id={headingId} className="order-specs-confirm__title">
        {title || 'Проверьте итоговые параметры спецификации:'}
      </h3>
      <div className="order-specs-confirm__table-wrap">
        <table className="order-specs-confirm__table">
          <thead>
            <tr>
              <th scope="col">параметры</th>
              <th scope="col">значение</th>
              <th scope="col" className="order-specs-confirm__th-edit" aria-label="Редактировать" />
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, i) => (
              <tr key={row.key || `spec-row-${i}`} className={i % 2 === 1 ? 'order-specs-confirm__row--alt' : ''}>
                <td className="order-specs-confirm__param">{row.label}</td>
                <td className="order-specs-confirm__value">{row.value}</td>
                <td className="order-specs-confirm__edit-cell">
                  {typeof onEditRow === 'function' && !isComputedOrderSpecRow(row) ? (
                    <button
                      type="button"
                      className="order-specs-confirm__edit-btn"
                      disabled={editBusy}
                      aria-label={`Изменить: ${row.label}`}
                      title={`Изменить: ${row.label}`}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        onEditRow(row);
                      }}
                    >
                      <PencilIcon />
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {showFlowMaxToggle ? (
        <FlowMaxAt25Toggle
          enabled={flowMaxAt25Enabled}
          onToggle={onFlowMaxAt25Toggle}
          disabled={editBusy}
        />
      ) : null}
      <QmaxHintPanel qmaxHint={qmaxHint} />
      <OrderSpecsRangeWarningsPanel rows={rows} />
      {footer ? <p className="order-specs-confirm__footer">{footer}</p> : null}
    </div>
  );
}

/** Заменяет текстовую сводку на таблицу, если API отдал order_specs_preview. */
export function enhanceBotMessageWithOrderSpecsConfirm(botMsg, response) {
  if (botMsg?.kind === 'gas_spu_review' || botMsg?.kind === 'gas_spu_card') return botMsg;
  const prev = response?.data?.order_specs_preview;
  const rows = prev?.review_rows;
  if (!Array.isArray(rows) || rows.length === 0) return botMsg;
  const footer = (prev.footer || botMsg.text || '').trim();
  return {
    ...botMsg,
    kind: 'order_specs_confirm',
    orderSpecsTitle: prev.review_title,
    orderSpecsRows: rows,
    text: footer,
  };
}

export function shouldShowOrderSpecsBotMessage(response, botMessages) {
  const preview = response?.data?.order_specs_preview;
  const t = (botMessages[0]?.content || '').trim();
  if (t) return true;
  return Array.isArray(preview?.review_rows) && preview.review_rows.length > 0;
}

function enhanceBotMessageWithFaqCard(botMsg, response) {
  const faqCard = response?.data?.faq_card;
  if (!faqCard || typeof faqCard !== 'object') return botMsg;
  const actions = Array.isArray(faqCard.actions) ? faqCard.actions : [];
  const attachmentUrl = botMsg?.attachmentUrl || response?.data?.messages?.find((msg) => !msg.is_user)?.attachment_url;
  const attachmentName = botMsg?.pdfName || response?.data?.messages?.find((msg) => !msg.is_user)?.attachment_name;
  return {
    ...botMsg,
    kind: 'faq_card',
    text: '',
    faqCard: {
      ...faqCard,
      actions: actions.map((action) => {
        if (action?.type !== 'file') return action;
        return {
          ...action,
          href: action.href || attachmentUrl || '',
          value: action.value || attachmentName || 'Файл',
        };
      }),
    },
  };
}

/** Цепочка обогащения ответа бота (FAQ + СПУ + таблица спецификации + уточнение параметров). */
export function enrichBotMessage(botMsg, response) {
  return enhanceBotMessageWithFaqCard(
    enhanceBotMessageWithOrderSpecsClarify(
      enhanceBotMessageWithOrderSpecsConfirm(
        enhanceBotMessageWithGasSpuCard(enhanceBotMessageWithGasSpuReview(botMsg, response), response),
        response,
      ),
      response,
    ),
    response,
  );
}
