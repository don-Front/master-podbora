/** Параметры и сравнение для GET /api/qmax-hint (turbo-podbor.ru). */

const MEDIUM_ALIASES = {
  gas: 'gas',
  газ: 'gas',
  liquid: 'liquid',
  жидкость: 'liquid',
};

/** Число из ячейки таблицы («100 мм», «3100–244000 ст.м³/ч»). */
export function parseSpecNumber(value, { preferMax = false } = {}) {
  if (value == null || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const s = String(value).trim().replace(/,/g, '.');
  const matches = s.match(/-?\d+(?:\.\d+)?/g);
  if (!matches?.length) return null;
  const nums = matches.map((m) => Number(m)).filter((n) => Number.isFinite(n));
  if (!nums.length) return null;
  return preferMax ? Math.max(...nums) : nums[0];
}

export function mediumApiFromValue(raw) {
  const s = String(raw ?? '')
    .trim()
    .toLowerCase()
    .replace('ё', 'е');
  if (!s) return null;
  if (MEDIUM_ALIASES[s]) return MEDIUM_ALIASES[s];
  if (s.includes('газ')) return 'gas';
  if (s.includes('жидк')) return 'liquid';
  if (s === 'gas' || s === 'liquid') return s;
  return null;
}

/**
 * diameter + medium + userFlowMax из строк таблицы и/или черновика specs.
 * @returns {{ diameter: number, medium: string, userFlowMax: number|null } | null}
 */
export function extractQmaxHintParams(rows, specsDraft = null) {
  const rowByKey = {};
  if (Array.isArray(rows)) {
    for (const row of rows) {
      if (row?.key) rowByKey[row.key] = row.value;
    }
  }

  const draft = specsDraft && typeof specsDraft === 'object' ? specsDraft : {};

  let diameter =
    parseSpecNumber(rowByKey.diameter) ??
    parseSpecNumber(draft.diameter) ??
    parseSpecNumber(draft.dn);

  let medium =
    mediumApiFromValue(rowByKey.medium) ?? mediumApiFromValue(draft.medium);

  const userFlowMax =
    parseSpecNumber(rowByKey.flowMax, { preferMax: true }) ??
    parseSpecNumber(draft.flowMax, { preferMax: true });

  if (diameter == null || !medium) return null;

  return {
    diameter: Math.trunc(diameter),
    medium,
    userFlowMax: userFlowMax ?? null,
  };
}

/** qmax из API меньше введённого пользователем максимального расхода. */
export function isQmaxFlowWarning(qmaxM3h, userFlowMax) {
  if (qmaxM3h == null || userFlowMax == null) return false;
  const q = Number(qmaxM3h);
  const u = Number(userFlowMax);
  if (!Number.isFinite(q) || !Number.isFinite(u)) return false;
  return q < u;
}
