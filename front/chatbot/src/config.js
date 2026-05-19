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

/** Origin Django (тот же, что у `/api/...`). */
export function getDjangoApiOrigin() {
  const base = (API_BASE_URL || '').trim().replace(/\/+$/, '');
  if (!base) return '';
  try {
    const u = new URL(/^https?:\/\//i.test(base) ? base : `http://${base}`);
    return u.origin;
  } catch {
    return '';
  }
}

/**
 * Базовый URL статики Django (`.../static` без завершающего слэша).
 * На runserver может работать `/static/equipment/...`; на Daphne часто нет — см. `/api/equipment-media/`.
 */
function getChatbotStaticBaseUrl() {
  const raw = (process.env.REACT_APP_EQUIPMENT_STATIC_BASE_URL || '').trim();
  if (raw) {
    return raw.replace(/\/+$/, '');
  }
  const origin = getDjangoApiOrigin();
  return origin ? `${origin}/static` : '';
}

/** React dev server раздаёт файлы из `public/` от корня сайта. */
function getReactPublicBaseUrl() {
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin.replace(/\/+$/, '');
  }
  return '';
}

/**
 * Убирает ведущие слэши и префикс `static/`, чтобы получить путь относительно `templates/static/`.
 * Примеры: `/static/equipment/a.png` → `equipment/a.png`, `equipment/a.png` → `equipment/a.png`.
 */
function normalizeTemplatesStaticRelativePath(raw) {
  let s = String(raw || '').trim().replace(/^\/+/, '');
  if (s.toLowerCase().startsWith('static/')) {
    s = s.slice('static/'.length);
  }
  return s;
}

/** Декодирует %20 в сегментах пути, чтобы подобрать варианты имён файлов на диске. */
function decodeRelativePathForVariantLookup(relPath) {
  const rel = String(relPath || '').trim().replace(/^\/+/, '');
  if (!rel) return '';
  try {
    return rel
      .split('/')
      .filter(Boolean)
      .map((seg) => decodeURIComponent(seg))
      .join('/');
  } catch {
    return rel;
  }
}

/** Добавляет URL вида `/api/equipment-media/<path>` для каждого варианта имени файла. */
function pushEquipmentMediaApiUrls(urls, relUnderTemplatesStatic) {
  const norm = normalizeTemplatesStaticRelativePath(relUnderTemplatesStatic);
  const rel = decodeRelativePathForVariantLookup(norm) || norm;
  if (!rel) return;
  const base = (API_BASE_URL || '').trim().replace(/\/+$/, '');
  if (!base) return;
  for (const v of relativeEquipmentPathVariants(rel)) {
    urls.push(`${base}/equipment-media/${encodePathSegments(v)}`);
  }
}

/** Добавляет URL из `front/chatbot/public/...` — быстрый локальный fallback для CRA. */
function pushReactPublicUrls(urls, relUnderTemplatesStatic) {
  const norm = normalizeTemplatesStaticRelativePath(relUnderTemplatesStatic);
  const rel = decodeRelativePathForVariantLookup(norm) || norm;
  if (!rel) return;
  const base = getReactPublicBaseUrl();
  if (!base) return;
  for (const v of relativeEquipmentPathVariants(rel)) {
    urls.push(`${base}/${encodePathSegments(v)}`);
  }
}

function encodePathSegments(relPath) {
  return relPath
    .split('/')
    .filter((seg) => seg.length > 0)
    .map((seg) => {
      try {
        return encodeURIComponent(decodeURIComponent(seg));
      } catch {
        return encodeURIComponent(seg);
      }
    })
    .join('/');
}

/**
 * Варианты относительного пути из API: имя файла может быть с пробелами (`Turbo Flow CFM.png`),
 * а в `back/templates/static/equipment` лежит `Turbo_Flow_CFM.png`.
 */
function relativeEquipmentPathVariants(relPath) {
  const rel = String(relPath || '').trim().replace(/^\//, '');
  if (!rel) return [];
  const segs = rel.split('/').filter(Boolean);
  if (segs.length === 0) return [];
  const file = segs[segs.length - 1];
  const dirPrefix = segs.length > 1 ? `${segs.slice(0, -1).join('/')}/` : '';

  const ordered = [];
  const seen = new Set();
  const pushFile = (f) => {
    if (!f || seen.has(f)) return;
    seen.add(f);
    ordered.push(f);
  };
  pushFile(file);
  if (file.includes(' ')) {
    pushFile(file.replace(/ +/g, '_'));
  }
  if (file.includes('_')) {
    pushFile(file.replace(/_/g, ' '));
  }
  return ordered.map((f) => (dirPrefix ? `${dirPrefix}${f}` : f));
}

function defaultLiquidTzQuestionnaireUrl() {
  const base = API_BASE_URL.replace(/\/+$/, '');
  return `${base}/templates/purs-questionnaire/`;
}

/** Ссылка на скачивание шаблона опросного листа ПУРС (шаг ТЗ «жидкость»). По умолчанию — endpoint Django. */
export const LIQUID_TZ_QUESTIONNAIRE_URL = (
  process.env.REACT_APP_LIQUID_TZ_QUESTIONNAIRE_URL || ''
).trim() || defaultLiquidTzQuestionnaireUrl();

/**
 * POST итоговых параметров в 1С (legacy, estimate-price и др.).
 * Переопределение: REACT_APP_1C_DATA_URL.
 */
export const ONE_C_DATA_URL = (
  process.env.REACT_APP_1C_DATA_URL || 'http://192.168.5.49:8010/api/1c/data'
).trim();

/**
 * GET подбор расходомеров по query-параметрам (без тела).
 * Переопределение: REACT_APP_SEARCH_EQUIPMENT_URL.
 */
export const SEARCH_EQUIPMENT_URL = (
  process.env.REACT_APP_SEARCH_EQUIPMENT_URL || 'http://192.168.5.49:8010/api/search-equipment'
).trim();

export function getSearchEquipmentUrl() {
  return SEARCH_EQUIPMENT_URL;
}

/** POST расчёта ориентировочной цены по выбранному прибору и итоговой спецификации. */
export const ESTIMATE_PRICE_URL = (
  process.env.REACT_APP_ESTIMATE_PRICE_URL || 'http://192.168.5.49:8010/api/estimate-price'
).trim();

/** POST подбора аксессуаров для точного ТКП по выбранному прибору и итоговой спецификации. */
export const TKP_ACCESSORIES_URL = (
  process.env.REACT_APP_TKP_ACCESSORIES_URL || 'http://192.168.5.49:8010/api/tkp-accessories'
).trim();

/** POST генерации PDF ТКП. */
export const TKP_PDF_URL = (
  process.env.REACT_APP_TKP_PDF_URL || 'http://192.168.5.49:8010/api/tkp-pdf'
).trim();

/** Origin сервиса 1С (fallback для картинок, если не задан Django static). */
export function getOneCApiOrigin() {
  try {
    return new URL(ONE_C_DATA_URL).origin;
  } catch {
    return 'http://192.168.5.49:8010';
  }
}

/**
 * GET прайс бытовых счётчиков Гранд — на сервисе 1С на :8010.
 * Дефолт держим отдельным URL, чтобы старый `REACT_APP_1C_DATA_URL` не уводил прайс на другой host.
 * Переопределение полного URL: `REACT_APP_GRAND_GAS_PRICE_URL`.
 */
const DEFAULT_GRAND_GAS_PRICE_URL = 'http://192.168.5.49:8010/api/prices/grand-gas-meters';

export function getGrandGasMetersPriceUrl() {
  const env = (process.env.REACT_APP_GRAND_GAS_PRICE_URL || '').trim();
  if (env) {
    return env.replace(/\/+$/, '');
  }
  return DEFAULT_GRAND_GAS_PRICE_URL;
}

/** POST заявки «бытовые счётчики газа» на :8010 (для отладочного вывода в консоль). */
export function getSubmitHouseholdGasRequestUrl() {
  const env = (process.env.REACT_APP_SUBMIT_HOUSEHOLD_GAS_URL || '').trim();
  if (env) {
    return env.replace(/\/+$/, '');
  }
  // Совпадает с дефолтом бэкенда (SERVICE_8010_ORIGIN + путь)
  return 'http://192.168.5.49:8010/api/submit-household-gas-request';
}

/** POST заявки по подобранной СПУ (газ); фактический вызов из Django — для лога в консоли. */
export function getSubmitSpuApplicationUrl() {
  return 'http://192.168.5.49:8010/api/submit-spu-application';
}

/**
 * Кодирует pathname URL по сегментам (пробелы и кириллица в имени файла не ломают запрос).
 */
function encodeAbsoluteUrlPath(urlString) {
  try {
    const u = new URL(urlString);
    const segs = u.pathname.split('/').filter((seg) => seg.length > 0);
    const encoded = segs
      .map((seg) => {
        try {
          return encodeURIComponent(decodeURIComponent(seg));
        } catch {
          return encodeURIComponent(seg);
        }
      })
      .join('/');
    u.pathname = encoded ? `/${encoded}` : '/';
    return u.toString();
  } catch {
    return urlString;
  }
}

/**
 * Полный список URL для `<img>` по строковому полю `image` (или абсолютному URL).
 * Основной источник файлов — `back/templates/static/` через GET `/api/equipment-media/...`
 * (работает и под Daphne). Дополнительно — `/static/...` на dev-runserver.
 */
export function getEquipmentImageCandidateUrls(path) {
  if (path == null || path === '') return [];
  const s = String(path).trim();
  if (/^https?:\/\//i.test(s)) {
    return [encodeAbsoluteUrlPath(s)];
  }
  const rel = decodeRelativePathForVariantLookup(normalizeTemplatesStaticRelativePath(s)) || normalizeTemplatesStaticRelativePath(s);
  if (!rel) return [];
  const urls = [];
  pushEquipmentMediaApiUrls(urls, rel);
  pushReactPublicUrls(urls, rel);
  const djangoStatic = getChatbotStaticBaseUrl();
  if (djangoStatic) {
    for (const v of relativeEquipmentPathVariants(rel)) {
      urls.push(`${djangoStatic}/${encodePathSegments(v)}`);
    }
  }
  return [...new Set(urls)];
}

/**
 * URL превью по объекту прибора из ответа 1С: `image_url`, `image_path`, затем `image`.
 * Пути вида `/static/equipment/...` сопоставляются с файлами в `back/templates/static/equipment/`.
 */
export function getEquipmentImageCandidateUrlsFromItem(item) {
  if (!item || typeof item !== 'object') return [];
  const urls = [];
  const collect = (raw) => {
    if (raw == null || raw === '') return;
    const s = String(raw).trim();
    if (/^https?:\/\//i.test(s)) {
      urls.push(encodeAbsoluteUrlPath(s));
      return;
    }
    pushEquipmentMediaApiUrls(urls, s);
    pushReactPublicUrls(urls, s);
    const rel =
      decodeRelativePathForVariantLookup(normalizeTemplatesStaticRelativePath(s)) ||
      normalizeTemplatesStaticRelativePath(s);
    const djangoStatic = getChatbotStaticBaseUrl();
    if (djangoStatic && rel) {
      for (const v of relativeEquipmentPathVariants(rel)) {
        urls.push(`${djangoStatic}/${encodePathSegments(v)}`);
      }
    }
  };
  collect(item.image_url);
  collect(item.image_path);
  collect(item.image);
  const dedup = [...new Set(urls)];
  return dedup.length ? dedup : getEquipmentImageCandidateUrls(item.image);
}

/**
 * URL превью прибора в слайдере (первый кандидат).
 */
export function resolveEquipmentImageUrl(path) {
  const urls = getEquipmentImageCandidateUrls(path);
  return urls[0] || '';
}

/** Значение поля `Authorization` в теле JSON (как в контракте 1С). */
export const ONE_C_AUTHORIZATION = (
  process.env.REACT_APP_1C_AUTHORIZATION || 'Bearer change-me'
).trim();
