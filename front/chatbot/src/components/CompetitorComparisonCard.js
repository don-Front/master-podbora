import { useMemo, useState } from 'react';
import { RUSSIA_PRIDE_BADGE_URL, TURBO_DON_LOGO_URL } from '../assets/brandingImages';
import { getBundledEquipmentImageUrls } from '../assets/equipmentImages';

function AnimatedCheckIcon() {
  return (
    <svg
      className="competitor-compare__icon competitor-compare__icon--ok"
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.12" />
      <path
        className="competitor-compare__check-path"
        d="M6.5 10.2 8.8 12.5 13.8 7.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength="1"
      />
    </svg>
  );
}

function AnimatedCrossIcon() {
  return (
    <svg
      className="competitor-compare__icon competitor-compare__icon--bad competitor-compare__cross-icon"
      viewBox="0 0 20 20"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.12" />
      <path
        d="M7.2 7.2 12.8 12.8M12.8 7.2 7.2 12.8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function resolveTurboSlideImage(slide) {
  if (!slide || typeof slide !== 'object') return null;
  const imageKey = String(slide.image_key || slide.imageKey || '').trim();
  if (!imageKey) return null;
  const urls = getBundledEquipmentImageUrls({ image: imageKey, model: slide.title });
  return urls[0] || null;
}

export function CompetitorComparisonCard({ card }) {
  const [flipped, setFlipped] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);

  const rows = Array.isArray(card?.rows) ? card.rows : [];
  const slide = card?.turbo_slide || card?.turboSlide || {};
  const slideImageUrl = useMemo(() => resolveTurboSlideImage(slide), [slide]);

  if (!card || typeof card !== 'object' || rows.length === 0) return null;

  const turboBrand = (card.turbo_brand || card.turboBrand || 'Turbo Flow UFG').trim();
  const turboProduct = (card.turbo_product_name || card.turboProductName || 'UFG-F-C').trim();
  const competitorName = (card.competitor_name || card.competitorName || 'Конкурент').trim();
  const competitorFullName = (
    card.competitor_full_name || card.competitorFullName || competitorName
  ).trim();
  const slideTitle = (slide.title || turboProduct).trim();
  const highlights = Array.isArray(slide.highlights) ? slide.highlights : [];
  const cardTitle = (card.title || 'Преимуществ Turbo Flow UFG').trim();

  const toggleFlip = () => setFlipped((value) => !value);

  return (
    <div className={`competitor-compare${flipped ? ' competitor-compare--flipped' : ''}`}>
      <button
        type="button"
        className="competitor-compare__hit"
        onClick={toggleFlip}
        aria-expanded={flipped}
        aria-label={
          flipped
            ? 'Вернуться к сравнению преимуществ'
            : 'Показать презентацию Turbo Flow UFG'
        }
      >
        <div className="competitor-compare__inner">
          <div className="competitor-compare__face competitor-compare__face--front">
            <div className="competitor-compare__head">
              <div className="competitor-compare__kicker">Сравнительный анализ</div>
              <div className="competitor-compare__title">{cardTitle}</div>
            </div>

            <div className="competitor-compare__columns">
              <div className="competitor-compare__col competitor-compare__col--turbo">
                <div className="competitor-compare__col-label">{turboBrand}</div>
                <div className="competitor-compare__col-product">{turboProduct}</div>
              </div>
              <div className="competitor-compare__col competitor-compare__col--vs">vs</div>
              <div className="competitor-compare__col competitor-compare__col--competitor">
                <div className="competitor-compare__col-label">{competitorFullName}</div>
                <div className="competitor-compare__col-product">{competitorName}</div>
              </div>
            </div>

            <ul className="competitor-compare__rows">
              {rows.map((row) => (
                <li key={row.label} className="competitor-compare__row">
                  <div className="competitor-compare__param">{row.label}</div>
                  <div className="competitor-compare__values">
                    <div className="competitor-compare__value competitor-compare__value--turbo">
                      <AnimatedCheckIcon />
                      <span>{row.turbo_value || row.turboValue || '—'}</span>
                    </div>
                    <div className="competitor-compare__value competitor-compare__value--competitor">
                      <AnimatedCrossIcon />
                      <span>{row.competitor_value || row.competitorValue || '—'}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>

            <div className="competitor-compare__hint">Нажмите, чтобы узнать больше о Turbo Flow UFG</div>
          </div>

          <div className="competitor-compare__face competitor-compare__face--back">
            <div className="competitor-compare__slide">
              <div className="competitor-compare__slide-header">
                <img
                  src={TURBO_DON_LOGO_URL}
                  alt="Турбулентность-Дон"
                  className="competitor-compare__slide-logo"
                  decoding="async"
                  draggable={false}
                />
                <img
                  src={RUSSIA_PRIDE_BADGE_URL}
                  alt="Разработано и произведено в России с гордостью"
                  className="competitor-compare__slide-badge"
                  decoding="async"
                  draggable={false}
                />
              </div>

              <div className="competitor-compare__slide-title">{slideTitle}</div>

              {slideImageUrl && !imageFailed ? (
                <div className="competitor-compare__slide-media">
                  <img
                    src={slideImageUrl}
                    alt={slideTitle}
                    className="competitor-compare__slide-img"
                    decoding="async"
                    draggable={false}
                    onError={() => setImageFailed(true)}
                  />
                </div>
              ) : null}

              {highlights.length > 0 ? (
                <ul className="competitor-compare__slide-list">
                  {highlights.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}

              <div className="competitor-compare__slide-footer">www.turbo-don.ru</div>
            </div>

            <div className="competitor-compare__hint competitor-compare__hint--back">
              Нажмите ещё раз, чтобы вернуться к сравнению
            </div>
          </div>
        </div>
      </button>
    </div>
  );
}
