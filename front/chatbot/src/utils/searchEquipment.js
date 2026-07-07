/**
 * GET /api/search-equipment — параметры в query string (без тела).
 * Логика синхронизирована с back/chatbot/api/search_equipment.py
 */

import { mediumApiFromValue } from './qmaxHint';

const LEGACY_ALIASES = {
  flow_min: 'flowMin',
  flow_max: 'flowMax',
  pressure_min: 'pressureMin',
  pressure_max: 'pressureMax',
  temperature_min: 'tempMediumMin',
  temperature_max: 'tempMediumMax',
  ambient_temp_min: 'tempAmbientMin',
  ambient_temp_max: 'tempAmbientMax',
};

export const SPEC_KEYS = [
  'medium',
  'gas_type',
  'flowMin',
  'flowMax',
  'flow_unit',
  'pressureMin',
  'pressureMax',
  'pressure_unit',
  'tempMediumMin',
  'tempMediumMax',
  'tempAmbientMin',
  'tempAmbientMax',
  'temperature_unit',
  'accuracy',
  'diameter',
];

export function normalizeSpecs(raw) {
  const src = raw && typeof raw === 'object' ? { ...raw } : {};
  const merged = {};
  Object.entries(LEGACY_ALIASES).forEach(([oldKey, newKey]) => {
    if (src[oldKey] != null && src[newKey] == null) merged[newKey] = src[oldKey];
  });
  Object.entries(src).forEach(([k, v]) => {
    if (SPEC_KEYS.includes(k)) merged[k] = v;
    else if (LEGACY_ALIASES[k] && merged[LEGACY_ALIASES[k]] == null) merged[LEGACY_ALIASES[k]] = v;
  });
  const out = {};
  SPEC_KEYS.forEach((k) => {
    out[k] = merged[k] ?? null;
  });
  return out;
}

function mapGasTypeToApi(gasType) {
  const s = String(gasType || '').trim().toLowerCase();
  if (s.includes('технолог') || s === 'technological' || s === 'tech') return 'technological';
  if (s.includes('природ') || s === 'natural') return 'natural';
  return 'natural';
}

function formatAccuracyForApi(value) {
  if (value == null || value === '') return null;
  const s = String(value).trim().replace(',', '.').replace('%', '').trim();
  const m = s.match(/\d+(?:\.\d+)?/);
  return m ? m[0] : s;
}

function scalarToParam(val) {
  if (val == null) return null;
  if (typeof val === 'number' && !Number.isNaN(val)) {
    return Number.isInteger(val) ? String(val) : String(val);
  }
  const t = String(val).trim();
  return t || null;
}

/** Query-параметры для GET /api/search-equipment */
export function buildSearchEquipmentParams(specs) {
  const s = normalizeSpecs(specs);
  const params = {
    equipment_type: 'flowmeters',
    medium: mediumApiFromValue(s.medium) || 'gas',
    application: 'industrial',
    gas_type: mapGasTypeToApi(s.gas_type),
  };

  [
    'flowMin',
    'flowMax',
    'flow_unit',
    'diameter',
    'pressureMin',
    'pressureMax',
    'pressure_unit',
    'tempMediumMin',
    'tempMediumMax',
    'temperature_unit',
    'tempAmbientMin',
    'tempAmbientMax',
  ].forEach((key) => {
    const v = scalarToParam(s[key]);
    if (v != null) params[key] = v;
  });

  const acc = formatAccuracyForApi(s.accuracy);
  if (acc) params.accuracy = acc;

  return params;
}

export function buildSearchEquipmentUrl(baseUrl, specs) {
  const base = String(baseUrl || '').trim().replace(/\/+$/, '');
  const qs = new URLSearchParams(buildSearchEquipmentParams(specs)).toString();
  return `${base}?${qs}`;
}
