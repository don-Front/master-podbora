import { parseSpecNumber } from './qmaxHint';

/** Пары min/max в таблице подтверждения спецификации. */
const RANGE_PAIRS = [
  {
    id: 'flow',
    minKey: 'flowMin',
    maxKey: 'flowMax',
    hint: 'Минимальный расход не должен превышать максимальный',
  },
  {
    id: 'pressure',
    minKey: 'pressureMin',
    maxKey: 'pressureMax',
    hint: 'Минимальное давление не должно превышать максимальное',
  },
  {
    id: 'tempMedium',
    minKey: 'tempMediumMin',
    maxKey: 'tempMediumMax',
    hint: 'Мин. температура рабочей среды не должна превышать макс.',
  },
  {
    id: 'tempAmbient',
    minKey: 'tempAmbientMin',
    maxKey: 'tempAmbientMax',
    hint: 'Мин. температура окружающей среды не должна превышать макс.',
  },
];

function rowsByKey(rows) {
  const map = {};
  if (!Array.isArray(rows)) return map;
  for (const row of rows) {
    if (row?.key) map[row.key] = row;
  }
  return map;
}

function unitSuffix(byKey, pairId) {
  if (pairId === 'flow') {
    const u = String(byKey.flow_unit?.value ?? '').trim();
    return u || '';
  }
  if (pairId === 'pressure') {
    const u = String(byKey.pressure_unit?.value ?? '').trim();
    return u || '';
  }
  const u = String(byKey.temperature_unit?.value ?? '').trim();
  return u || '°C';
}

function formatRangeAmount(num, unit) {
  const text =
    Number.isInteger(num) || Math.abs(num - Math.trunc(num)) < 1e-9
      ? String(Math.trunc(num))
      : String(num).replace('.', ',');
  return unit ? `${text} ${unit}` : text;
}

/**
 * Находит диапазоны, где минимум больше максимума.
 * @returns {Array<{ id: string, hint: string, minText: string, maxText: string }>}
 */
export function detectOrderSpecsRangeIssues(rows) {
  const byKey = rowsByKey(rows);
  const issues = [];

  for (const pair of RANGE_PAIRS) {
    const minNum = parseSpecNumber(byKey[pair.minKey]?.value);
    const maxNum = parseSpecNumber(byKey[pair.maxKey]?.value, { preferMax: true });
    if (minNum == null || maxNum == null) continue;
    if (minNum <= maxNum) continue;

    const unit = unitSuffix(byKey, pair.id);
    issues.push({
      id: pair.id,
      hint: pair.hint,
      minText: formatRangeAmount(minNum, unit),
      maxText: formatRangeAmount(maxNum, unit),
    });
  }

  return issues;
}
