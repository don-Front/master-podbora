import axios from 'axios';
import {
  API_BASE_URL,
  ESTIMATE_PRICE_URL,
  buildQmaxHintUrl,
  getGrandGasMetersPriceUrl,
  getSearchEquipmentUrl,
  TKP_ACCESSORIES_URL,
  TKP_PDF_URL,
} from './config';
import { buildSearchEquipmentUrl } from './utils/searchEquipment';

const api = axios.create({
  baseURL: API_BASE_URL,
});

// Chats
export const getChats = (params = {}) => api.get('/chats/', { params });

export const getActiveChats = () => api.get('/chats/', { params: { archived: 'false', exclude_empty: 'true' } });

export const getArchivedChats = () => api.get('/chats/', { params: { archived: 'true' } });

export const createChat = (data) => api.post('/chats/', data);

export const updateChat = (id, data) => api.put(`/chats/${id}/`, data);

export const deleteChat = (id) => api.delete(`/chats/${id}/`);

// Chat actions
export const finalizeChat = (id) => api.post(`/chats/${id}/finalize/`);

export const generateChatTitle = (id) => api.post(`/chats/${id}/generate_title/`);

export const archiveChat = (id) => api.post(`/chats/${id}/archive/`);

export const unarchiveChat = (id) => api.post(`/chats/${id}/unarchive/`);

export const archiveOldChats = () => api.post('/chats/archive_old/');

export const cleanupEmptyChats = () => api.post('/chats/cleanup_empty/');

// Messages
export const getMessages = (chatId) => api.get(`/chats/${chatId}/messages/`);

export const createMessage = (chatId, data, image = null, pdf = null) => {
  if (image || pdf) {
    const formData = new FormData();
    formData.append('content', data.content || '');
    formData.append('hint_state', data.hint_state || 'start');
    formData.append('is_hint_selection', data.is_hint_selection || false);
    formData.append('hint_locked', data.hint_locked || false);
    if (data.equipment_for_price != null) {
      const raw =
        typeof data.equipment_for_price === 'string'
          ? data.equipment_for_price
          : JSON.stringify(data.equipment_for_price);
      formData.append('equipment_for_price', raw);
    }
    if (data.order_specs_for_price != null) {
      const raw =
        typeof data.order_specs_for_price === 'string'
          ? data.order_specs_for_price
          : JSON.stringify(data.order_specs_for_price);
      formData.append('order_specs_for_price', raw);
    }
    if (data.liquid_installation_lead != null) {
      const raw =
        typeof data.liquid_installation_lead === 'string'
          ? data.liquid_installation_lead
          : JSON.stringify(data.liquid_installation_lead);
      formData.append('liquid_installation_lead', raw);
    }
    if (data.gas_spu_application_lead != null) {
      const raw =
        typeof data.gas_spu_application_lead === 'string'
          ? data.gas_spu_application_lead
          : JSON.stringify(data.gas_spu_application_lead);
      formData.append('gas_spu_application_lead', raw);
    }
    if (data.household_gas_lead != null) {
      const raw =
        typeof data.household_gas_lead === 'string'
          ? data.household_gas_lead
          : JSON.stringify(data.household_gas_lead);
      formData.append('household_gas_lead', raw);
    }
    if (data.gas_spu_selection != null) {
      const raw =
        typeof data.gas_spu_selection === 'string'
          ? data.gas_spu_selection
          : JSON.stringify(data.gas_spu_selection);
      formData.append('gas_spu_selection', raw);
    }
    if (data.order_specs_edit_field != null && data.order_specs_edit_field !== '') {
      formData.append('order_specs_edit_field', String(data.order_specs_edit_field));
    }
    if (data.debug_skip_equipment_price_verify != null) {
      formData.append(
        'debug_skip_equipment_price_verify',
        data.debug_skip_equipment_price_verify ? 'true' : 'false',
      );
    }
    if (image) {
      formData.append('image', image);
    }
    if (pdf) {
      formData.append('attachment', pdf);
    }

    return api.post(`/chats/${chatId}/messages/`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  }

  return api.post(`/chats/${chatId}/messages/`, data);
};

// Hints system
export const getHints = (state = 'start') => api.get('/hints/', { params: { state } });

export const transitionHints = (data) => api.post('/hints/', data);

// Email validation
export const validateEmail = (email) => api.post('/validate-email/', { email });

// Geo location
export const getGeoLocation = async (ip) => {
  try {
    const response = await axios.get(`https://ipapi.co/${ip}/json/`);
    return response.data;
  } catch (error) {
    console.error('Error fetching geo location:', error);
    return null;
  }
};

/**
 * Подбор оборудования: GET /api/search-equipment?… (параметры в URL, без тела).
 */
export function fetchSearchEquipment(specsObject) {
  const url = buildSearchEquipmentUrl(getSearchEquipmentUrl(), specsObject);
  // eslint-disable-next-line no-console
  console.log('[search-equipment] GET URL:', url);
  return axios
    .get(url, { timeout: 120000 })
    .then((res) => ({ ...res, requestUrl: url }))
    .catch((err) => {
      // eslint-disable-next-line no-console
      console.error('[search-equipment] GET failed:', url, err?.response?.status ?? err?.message);
      return Promise.reject(err);
    });
}

/** GET подсказка qmax-hint при изменении диаметра / среды измерения. */
export function fetchQmaxHint(diameter, medium, options = {}) {
  const url = buildQmaxHintUrl(diameter, medium);
  return axios.get(url, { timeout: 30000, ...options });
}

/** @deprecated используйте fetchSearchEquipment */
export function postEquipmentSpecsTo1c(specsObject) {
  return fetchSearchEquipment(specsObject);
}

export function postEstimatePrice(body) {
  return axios.post(ESTIMATE_PRICE_URL, body, {
    headers: { 'Content-Type': 'application/json' },
  });
}

export function postTkpAccessories(body) {
  return axios.post(TKP_ACCESSORIES_URL, body, {
    headers: { 'Content-Type': 'application/json' },
  });
}

export function postTkpPdf(body) {
  return axios.post(TKP_PDF_URL, body, {
    headers: { 'Content-Type': 'application/json' },
    responseType: 'arraybuffer',
    transformResponse: [(data) => data],
  });
}

/** GET прайс СГ Гранд с сервиса подбора (см. `getGrandGasMetersPriceUrl`). */
export function getGrandGasMetersPrices() {
  return axios.get(getGrandGasMetersPriceUrl(), { timeout: 60000 });
}

export default api;
