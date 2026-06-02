import turboFlowCfm from './equipment/Turbo_Flow_CFM.png';
import turboFlowTfgH from './equipment/Turbo Flow TFG-H.png';
import turboFlowTfgS from './equipment/Turbo Flow TFG-S.png';
import turboFlowUdm from './equipment/Turbo Flow UDM.png';
import turboFlowUfg from './equipment/turbo_flow_ufg.jpg';
import turboFlowUfgFC from './equipment/Turbo Flow UFG-F-C.png';
import turboFlowUfgH from './equipment/Turbo Flow UFG-H.png';
import turboFlowUfl from './equipment/Turbo Flow UFL.png';

const IMAGE_BY_FILE = new Map([
  ['turbo flow cfm.png', turboFlowCfm],
  ['turbo_flow_cfm.png', turboFlowCfm],
  ['turbo flow tfg-h.png', turboFlowTfgH],
  ['turbo_flow_tfg-h.png', turboFlowTfgH],
  ['turbo flow tfg-s.png', turboFlowTfgS],
  ['turbo_flow_tfg-s.png', turboFlowTfgS],
  ['turbo flow udm.png', turboFlowUdm],
  ['turbo_flow_udm.png', turboFlowUdm],
  ['turbo flow ufg.jpg', turboFlowUfg],
  ['turbo_flow_ufg.jpg', turboFlowUfg],
  ['turbo flow ufg-f-c.png', turboFlowUfgFC],
  ['turbo_flow_ufg-f-c.png', turboFlowUfgFC],
  ['turbo flow ufg-h.png', turboFlowUfgH],
  ['turbo_flow_ufg-h.png', turboFlowUfgH],
  ['turbo flow ufl.png', turboFlowUfl],
  ['turbo_flow_ufl.png', turboFlowUfl],
]);

function decodePathSegment(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function fileNameFromPath(value) {
  const s = String(value || '').trim();
  if (!s) return '';
  const withoutQuery = s.split('?')[0].split('#')[0];
  const parts = withoutQuery.replace(/\\/g, '/').split('/').filter(Boolean);
  return decodePathSegment(parts[parts.length - 1] || '').trim();
}

function addFileNameVariants(keys, fileName) {
  if (!fileName) return;
  keys.push(fileName);
  keys.push(fileName.replace(/ +/g, '_'));
  keys.push(fileName.replace(/_/g, ' '));
}

function addModelVariants(keys, value) {
  const s = String(value || '').trim();
  if (!s) return;
  keys.push(`${s}.png`);
  keys.push(`${s}.jpg`);
  keys.push(`${s.replace(/ +/g, '_')}.png`);
  keys.push(`${s.replace(/ +/g, '_')}.jpg`);
}

export function getBundledEquipmentImageUrls(item) {
  if (!item || typeof item !== 'object') return [];

  const keys = [];
  addFileNameVariants(keys, fileNameFromPath(item.image_url));
  addFileNameVariants(keys, fileNameFromPath(item.image_path));
  addFileNameVariants(keys, fileNameFromPath(item.image));
  addModelVariants(keys, item.model);
  addModelVariants(keys, item.name);

  const urls = [];
  const seen = new Set();
  for (const key of keys) {
    const normalized = String(key || '').trim().toLowerCase();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    const url = IMAGE_BY_FILE.get(normalized);
    if (url && !urls.includes(url)) {
      urls.push(url);
    }
  }
  return urls;
}
