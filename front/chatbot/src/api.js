import axios from 'axios';
import {
  API_BASE_URL,
  ESTIMATE_PRICE_URL,
  ONE_C_AUTHORIZATION,
  ONE_C_DATA_URL,
  TKP_ACCESSORIES_URL,
  TKP_PDF_URL,
} from './config';

function equipmentParamsTimestamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

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
 * Отправка итоговой спецификации на мост 1С (тело как в ТЗ: type, timestamp, Authorization, data).
 */
export function postEquipmentSpecsTo1c(specsObject) {
  const body = {
    type: 'equipment_params',
    timestamp: equipmentParamsTimestamp(),
    Authorization: ONE_C_AUTHORIZATION,
    data: specsObject,
  };
  return axios.post(ONE_C_DATA_URL, body, {
    headers: { 'Content-Type': 'application/json' },
  });
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

export default api;
