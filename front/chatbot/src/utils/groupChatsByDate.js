/** Группировка чатов по календарным дням для списка в админке. */
export function groupChatsByDate(chats) {
  const groups = {};
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  chats.forEach((chat) => {
    const chatDate = new Date(chat.created_at);
    chatDate.setHours(0, 0, 0, 0);

    let label;
    if (chatDate.getTime() === today.getTime()) {
      label = 'Сегодня';
    } else if (chatDate.getTime() === yesterday.getTime()) {
      label = 'Вчера';
    } else {
      label = chatDate.toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: chatDate.getFullYear() !== today.getFullYear() ? 'numeric' : undefined,
      });
    }

    if (!groups[label]) {
      groups[label] = [];
    }
    groups[label].push(chat);
  });

  return groups;
}
