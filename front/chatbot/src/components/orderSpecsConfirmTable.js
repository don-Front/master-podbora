/**
 * Таблица итоговых параметров спецификации (шаг order_specs_confirm).
 */
import {
  enhanceBotMessageWithGasSpuCard,
  enhanceBotMessageWithGasSpuReview,
} from './gasSpuResultCard';
import { enhanceBotMessageWithOrderSpecsClarify } from './OrderSpecsTextClarify';

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

export function OrderSpecsConfirmTable({ title, rows, footer, onEditRow, editBusy }) {
  const headingId = 'order-specs-confirm-heading';
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
            {rows.map((row, i) => (
              <tr key={row.key || `spec-row-${i}`} className={i % 2 === 1 ? 'order-specs-confirm__row--alt' : ''}>
                <td className="order-specs-confirm__param">{row.label}</td>
                <td className="order-specs-confirm__value">{row.value}</td>
                <td className="order-specs-confirm__edit-cell">
                  {typeof onEditRow === 'function' ? (
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
