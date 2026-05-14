/**
 * Базовый URL REST API Django (путь до `/api`, без завершающего слэша).
 *
 * В development по умолчанию — прямой адрес бэкенда :8002 (не зависит от proxy CRA).
 * Если REACT_APP_API_URL случайно указывает на порт React (3000/3001), он игнорируется.
 */
const DEV_DJANGO_API = 'http://127.0.0.1:8002/api';

function apiUrlPointsToCraDevServer(urlString) {
  try {
    const u = new URL(urlString);
    const port = u.port;
    const h = (u.hostname || '').toLowerCase();
    if (h !== 'localhost' && h !== '127.0.0.1') return false;
    return port === '3000' || port === '3001';
  } catch {
    return false;
  }
}

function resolveApiBaseUrl() {
  let raw = (process.env.REACT_APP_API_URL || '').trim();
  if (raw) {
    raw = raw.replace(/\/+$/, '');
    try {
      const withProto = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
      const u = new URL(withProto);
      if (u.pathname === '/' || u.pathname === '') {
        raw = `${u.origin}/api`;
      } else {
        raw = `${u.origin}${u.pathname}`.replace(/\/+$/, '');
      }
    } catch {
      /* оставляем raw как есть */
    }
    if (process.env.NODE_ENV === 'development' && apiUrlPointsToCraDevServer(raw)) {
      return DEV_DJANGO_API;
    }
    return raw;
  }
  if (process.env.NODE_ENV === 'development') {
    return DEV_DJANGO_API;
  }
  return 'http://192.168.5.219:8000/api';
}

export const API_BASE_URL = resolveApiBaseUrl();

function defaultLiquidTzQuestionnaireUrl() {
  const base = API_BASE_URL.replace(/\/+$/, '');
  return `${base}/templates/purs-questionnaire/`;
}

/** Ссылка на скачивание шаблона опросного листа ПУРС (шаг ТЗ «жидкость»). По умолчанию — endpoint Django. */
export const LIQUID_TZ_QUESTIONNAIRE_URL = (
  process.env.REACT_APP_LIQUID_TZ_QUESTIONNAIRE_URL || ''
).trim() || defaultLiquidTzQuestionnaireUrl();

/**
 * POST итоговых параметров в 1С после готового JSON (см. ChatWidget).
 * Переопределение: REACT_APP_1C_DATA_URL.
 */
export const ONE_C_DATA_URL = (
  process.env.REACT_APP_1C_DATA_URL || 'http://192.168.2.41:8010/api/1c/data'
).trim();

/** POST расчёта ориентировочной цены по выбранному прибору и итоговой спецификации. */
export const ESTIMATE_PRICE_URL = (
  process.env.REACT_APP_ESTIMATE_PRICE_URL || 'http://192.168.2.41:8010/api/estimate-price'
).trim();

/** POST подбора аксессуаров для точного ТКП по выбранному прибору и итоговой спецификации. */
export const TKP_ACCESSORIES_URL = (
  process.env.REACT_APP_TKP_ACCESSORIES_URL || 'http://192.168.2.41:8010/api/tkp-accessories'
).trim();

/** POST генерации PDF ТКП. */
export const TKP_PDF_URL = (
  process.env.REACT_APP_TKP_PDF_URL || 'http://192.168.2.41:8010/api/tkp-pdf'
).trim();

/** Origin сервиса 1C (картинки `equipment/...` обычно с того же хоста). */
export function getOneCApiOrigin() {
  try {
    return new URL(ONE_C_DATA_URL).origin;
  } catch {
    return 'http://192.168.2.41:8010';
  }
}

/**
 * URL превью прибора. Путь кодируется по сегментам (пробелы в `Turbo Flow TFG-S.png` и т.д.).
 * REACT_APP_1C_IMAGE_PATH_PREFIX — при необходимости, напр. `static` → http://host:8001/static/equipment/...
 */
export function resolveEquipmentImageUrl(path) {
  if (path == null || path === '') return '';
  const s = String(path).trim();
  if (/^https?:\/\//i.test(s)) {
    return s;
  }
  const base = getOneCApiOrigin().replace(/\/$/, '');
  const prefix = (process.env.REACT_APP_1C_IMAGE_PATH_PREFIX || '')
    .trim()
    .replace(/^\/+/, '')
    .replace(/\/+$/, '');
  const rel = s.replace(/^\//, '');
  const full = [prefix, rel].filter((x) => x).join('/');
  const encodedPath = full
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/');
  return `${base}/${encodedPath}`;
}

/** Значение поля `Authorization` в теле JSON (как в контракте 1С). */
export const ONE_C_AUTHORIZATION = (
  process.env.REACT_APP_1C_AUTHORIZATION || 'Bearer change-me'
).trim();
