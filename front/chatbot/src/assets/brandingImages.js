/** URL статики брендинга из public/branding (учитывает PUBLIC_URL /podbor-chat). */

export function getBrandingImageUrl(fileName) {
  const name = String(fileName || '').trim().replace(/^\/+/, '');
  if (!name) return '';
  const base = (process.env.PUBLIC_URL || '/podbor-chat').replace(/\/+$/, '');
  return `${base}/branding/${name}`;
}

export const TURBO_DON_LOGO_URL = getBrandingImageUrl('turbo-don-logo.png');
export const RUSSIA_PRIDE_BADGE_URL = getBrandingImageUrl('russia-pride-badge.png');
