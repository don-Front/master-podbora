import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
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

export const createMessage = (chatId, data, image = null) => {
  // Если есть изображение, используем FormData
  if (image) {
    const formData = new FormData();
    formData.append('content', data.content || '');
    formData.append('hint_state', data.hint_state || 'start');
    formData.append('is_hint_selection', data.is_hint_selection || false);
    formData.append('hint_locked', data.hint_locked || false);
    formData.append('image', image);
    
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

export default api;
