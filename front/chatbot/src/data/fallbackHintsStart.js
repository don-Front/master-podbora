/**
 * Копия ответа GET /api/hints/?state=start (см. back/chatbot/api/hints_tree.py).
 * Используется, если сервер недоступен — чтобы приветствие и кнопки совпадали с бэкендом.
 */
export const FALLBACK_HINTS_START = {
  current_state: 'start',
  bot_message:
    'Здравствуйте! Я виртуальный помощник сервиса «Турбо-дон чат». Готов помочь с подбором оборудования по Вашим параметрам и ответить на вопросы по ассортименту и характеристикам изделий. Выберите раздел ниже или опишите задачу в сообщении.',
  hints: [
    { text: 'Подбор оборудования', next_state: 'equipment_pick' },
    { text: 'Продажа оборудования', next_state: 'sales' },
    { text: 'Поверка', next_state: 'verification' },
    { text: 'Пуско-наладочные работы', next_state: 'commissioning' },
    { text: 'Обратная связь', next_state: 'feedback_pick' },
    { text: 'Отклик на вакансию', next_state: 'vacancy' },
    { text: 'Другое', next_state: 'other' },
  ],
  show_back: false,
  is_final: false,
  expects_input: false,
  hints_only: false,
};
