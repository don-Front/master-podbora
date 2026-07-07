import { useMemo, useState } from 'react';
import { getCompetitorImageUrl } from '../assets/competitorImages';

function formatAllowed(values) {
  if (!Array.isArray(values) || values.length === 0) return '';
  if (values.length <= 6) return values.join(', ');
  return `${values.slice(0, 6).join(', ')}…`;
}

export function CompetitorMaskCard({ card }) {
  const [flipped, setFlipped] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);

  const imageUrl = useMemo(() => getCompetitorImageUrl(card), [card]);
  if (!card || typeof card !== 'object') return null;

  const competitor = (card.competitor || '').trim();
  const productName = (card.product_name || card.productName || '').trim();
  const parameters = Array.isArray(card.parameters) ? card.parameters : [];
  const errors = Array.isArray(card.errors) ? card.errors : [];
  const isValid = Boolean(card.is_valid ?? card.isValid);

  const toggleFlip = () => setFlipped((value) => !value);

  return (
    <div
      className={`chat-widget__competitor-card${flipped ? ' chat-widget__competitor-card--flipped' : ''}${
        isValid ? ' chat-widget__competitor-card--valid' : ' chat-widget__competitor-card--invalid'
      }`}
    >
      <button
        type="button"
        className="chat-widget__competitor-card-hit"
        onClick={toggleFlip}
        aria-expanded={flipped}
        aria-label={flipped ? 'Свернуть расшифровку маски' : 'Развернуть расшифровку маски'}
      >
        <div className="chat-widget__competitor-card-inner">
          <div className="chat-widget__competitor-card-face chat-widget__competitor-card-face--front">
            <div className="chat-widget__competitor-card-media">
              {imageUrl && !imageFailed ? (
                <img
                  className="chat-widget__competitor-card-img"
                  src={imageUrl}
                  alt={productName || competitor || 'Прибор конкурента'}
                  decoding="async"
                  draggable={false}
                  onError={() => setImageFailed(true)}
                />
              ) : (
                <div className="chat-widget__competitor-card-placeholder">
                  {imageFailed ? 'Фото не загрузилось' : 'Нет фото'}
                </div>
              )}
            </div>
            <div className="chat-widget__competitor-card-caption">
              <div className="chat-widget__competitor-card-kicker">Оборудование конкурента</div>
              <div className="chat-widget__competitor-card-title">{competitor || '—'}</div>
              {productName ? (
                <div className="chat-widget__competitor-card-subtitle">{productName}</div>
              ) : null}
              <div className="chat-widget__competitor-card-hint">Нажмите, чтобы увидеть расшифровку маски</div>
            </div>
          </div>

          <div className="chat-widget__competitor-card-face chat-widget__competitor-card-face--back">
            <div className="chat-widget__competitor-card-back-head">
              <div className="chat-widget__competitor-card-back-title">Расшифровка маски</div>
              <div
                className={`chat-widget__competitor-card-badge${
                  isValid ? ' chat-widget__competitor-card-badge--ok' : ' chat-widget__competitor-card-badge--err'
                }`}
              >
                {isValid ? 'Все сегменты из РЭ' : 'Есть несоответствия РЭ'}
              </div>
            </div>

            {card.raw_mask ? (
              <div className="chat-widget__competitor-card-mask">{card.raw_mask}</div>
            ) : null}

            {parameters.length > 0 ? (
              <ul className="chat-widget__competitor-card-params">
                {parameters.map((item) => (
                  <li key={`${item.field_id || item.label}-${item.position}`} className="chat-widget__competitor-card-param">
                    <span className="chat-widget__competitor-card-param-label">
                      [{item.position}] {item.label}
                    </span>
                    <span className="chat-widget__competitor-card-param-value">{item.value}</span>
                    {item.hint && item.hint !== item.label ? (
                      <span className="chat-widget__competitor-card-param-hint">{item.hint}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="chat-widget__competitor-card-empty">Параметры маски не распознаны.</div>
            )}

            {errors.length > 0 ? (
              <div className="chat-widget__competitor-card-errors">
                <div className="chat-widget__competitor-card-errors-title">Ошибки по РЭ</div>
                <ul>
                  {errors.map((err) => (
                    <li key={`${err.field_id}-${err.raw_value}`}>
                      <strong>{err.label}:</strong> «{err.raw_value}» — допустимо: {formatAllowed(err.allowed)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="chat-widget__competitor-card-hint chat-widget__competitor-card-hint--back">
              Нажмите ещё раз, чтобы вернуться к фото
            </div>
          </div>
        </div>
      </button>
    </div>
  );
}
