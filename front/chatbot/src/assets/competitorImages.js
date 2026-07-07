/**
 * Фото конкурентов для flip-карточки расшифровки маски.
 * Положите PNG/JPG в public/competitors/ с именами из YAML (image).
 */

function publicCompetitorUrl(fileName) {
  const base = (process.env.PUBLIC_URL || '').replace(/\/+$/, '');
  const clean = String(fileName || '').trim().replace(/^\/+/, '');
  if (!clean) return '';
  return `${base}/competitors/${encodeURIComponent(clean)}`;
}

export function getCompetitorImageUrl(card) {
  if (!card || typeof card !== 'object') return '';
  const fromCard = card.image_url || card.imageUrl;
  if (fromCard) return String(fromCard);
  return publicCompetitorUrl(card.image || `${card.catalog_id || 'unknown'}.png`);
}
