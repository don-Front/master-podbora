/**
 * Копия ответа GET /api/hints/?state=start (см. back/chatbot/api/hints_tree.py).
 * Используется, если сервер недоступен — чтобы приветствие и кнопки совпадали с бэкендом.
 */
export const FALLBACK_HINTS_START = {
  current_state: 'start',
  bot_message: 'Здравствуйте! Чем я могу Вам помочь?',
  hints: [
    { text: 'Оформить заказ', next_state: 'order_pdf_request' },
    { text: 'Продажа оборудования', next_state: 'sales' },
    { text: 'Поверка', next_state: 'verification' },
    { text: 'Пуско-наладочные работы', next_state: 'commissioning' },
    { text: 'Техническая поддержка', next_state: 'tech_support' },
    { text: 'Претензии', next_state: 'claims' },
    { text: 'Отклик на вакансию', next_state: 'vacancy' },
    { text: 'Другое', next_state: 'other' },
  ],
  show_back: false,
  is_final: false,
  expects_input: false,
};
