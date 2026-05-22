/**
 * Блок уточнения недостающих параметров (шаг order_specs_text_clarify).
 */

const DEFAULT_MISSING_HINT =
  'Числовые значения уже определены. Уточните, пожалуйста, в каких единицах они указаны (ниже — только примеры):';

const DEFAULT_FOOTER =
  'Напишите единицы измерения одним сообщением — можно в свободной форме, например: «расход в ст.м³/ч, давление в бар».';

function getResponseData(response) {
  return response?.data ?? response ?? {};
}

function parseBulletLines(block) {
  return String(block || '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('-'))
    .map((line) => line.replace(/^-\s*/, ''));
}

function parseFoundRow(line) {
  const colon = line.indexOf(':');
  if (colon === -1) return { label: line, value: '' };
  return {
    label: line.slice(0, colon).trim(),
    value: line.slice(colon + 1).trim(),
  };
}

function parseMissingRow(line) {
  const exampleMatch = line.match(/^(.+?)\s*[—–-]\s*например:\s*(.+)$/i);
  if (exampleMatch) {
    return { label: exampleMatch[1].trim(), example: exampleMatch[2].trim() };
  }
  const colon = line.indexOf(':');
  if (colon !== -1) {
    return {
      label: line.slice(0, colon).trim(),
      example: line.slice(colon + 1).trim(),
    };
  }
  return { label: line, example: '' };
}

/** Собирает preview из plain-text ответа бота (если API ещё без order_specs_clarify_preview). */
export function parseClarifyMessageFromText(text) {
  const source = String(text || '').trim();
  if (!source.includes('Необходимо уточнить')) return null;

  const parts = source.split(/Необходимо уточнить:?\s*/i);
  const head = parts[0] || '';
  let tail = parts.slice(1).join('Необходимо уточнить').trim();

  let footer = DEFAULT_FOOTER;
  const footerMatch =
    tail.match(/Напишите (?:недостающие параметры|единицы измерения)[\s\S]*/i);
  if (footerMatch) {
    footer = footerMatch[0].trim();
    tail = tail.slice(0, tail.indexOf(footerMatch[0])).trim();
  }

  tail = tail
    .replace(/^Укажите недостающие параметры[^\n]*\n?/i, '')
    .replace(/^Числовые значения уже определены[^\n]*\n?/i, '')
    .replace(/^Если числа уже указаны выше[^\n]*\n?/i, '')
    .trim();

  let warning = '';
  let foundPart = head;
  const introMarker = /Для подбора расходомера я определил следующие параметры:?/i;
  const introMatch = head.match(introMarker);
  if (introMatch) {
    const introIndex = head.search(introMarker);
    warning = head.slice(0, introIndex).trim();
    foundPart = head.slice(introIndex + introMatch[0].length).trim();
  }

  const foundRows = parseBulletLines(foundPart).map(parseFoundRow);
  const missingRows = parseBulletLines(tail).map(parseMissingRow);
  if (missingRows.length === 0 && foundRows.length === 0) return null;

  return {
    warning,
    intro: 'Для подбора расходомера я определил следующие параметры:',
    found_rows: foundRows,
    missing_title: 'Необходимо уточнить',
    missing_hint: DEFAULT_MISSING_HINT,
    missing_rows: missingRows,
    footer,
  };
}

export function OrderSpecsTextClarify({ preview }) {
  if (!preview) return null;

  const {
    warning,
    intro,
    found_rows: foundRows = [],
    missing_title: missingTitle,
    missing_hint: missingHint,
    missing_rows: missingRows = [],
    footer,
  } = preview;

  return (
    <div className="order-specs-clarify">
      {warning ? <p className="order-specs-clarify__warning">{warning}</p> : null}

      {intro ? <p className="order-specs-clarify__intro">{intro}</p> : null}

      {foundRows.length > 0 ? (
        <ul className="order-specs-clarify__found-list">
          {foundRows.map((row) => (
            <li key={row.label} className="order-specs-clarify__found-item">
              <span className="order-specs-clarify__found-label">{row.label}:</span>{' '}
              <span className="order-specs-clarify__found-value">{row.value}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="order-specs-clarify__found-empty">— пока не удалось надёжно определить параметры</p>
      )}

      <div className="order-specs-clarify__missing-box" role="note">
        {missingTitle ? <p className="order-specs-clarify__missing-title">{missingTitle}</p> : null}
        {missingHint ? <p className="order-specs-clarify__missing-hint">{missingHint}</p> : null}
        {missingRows.length > 0 ? (
          <ul className="order-specs-clarify__missing-list">
            {missingRows.map((row) => (
              <li key={row.label} className="order-specs-clarify__missing-item">
                <span className="order-specs-clarify__missing-label">{row.label}</span>
                {row.example ? (
                  <span className="order-specs-clarify__missing-example">например: {row.example}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {footer ? <p className="order-specs-clarify__footer">{footer}</p> : null}
    </div>
  );
}

/** Заменяет plain-text уточнение на структурированный блок. */
export function enhanceBotMessageWithOrderSpecsClarify(botMsg, response) {
  const data = getResponseData(response);
  let preview = data?.order_specs_clarify_preview;

  if (!preview || typeof preview !== 'object') {
    const state = data?.hint_state?.current_state;
    const text = (botMsg?.text || '').trim();
    if (state === 'order_specs_text_clarify' || text.includes('Необходимо уточнить')) {
      preview = parseClarifyMessageFromText(text);
    }
  }

  if (!preview || typeof preview !== 'object') return botMsg;

  return {
    ...botMsg,
    kind: 'order_specs_text_clarify',
    orderSpecsClarifyPreview: preview,
    text: '',
  };
}
