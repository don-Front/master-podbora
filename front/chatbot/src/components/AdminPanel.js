import { useEffect, useState } from 'react';
import {
  getActiveChats,
  getArchivedChats,
  getMessages,
  updateChat,
  deleteChat,
  getGeoLocation,
  unarchiveChat,
  archiveOldChats,
  cleanupEmptyChats,
} from '../api';
import { formatTime } from '../utils/formatTime';
import { groupChatsByDate } from '../utils/groupChatsByDate';

export function AdminPanel() {
  const [activeChats, setActiveChats] = useState([]);
  const [archivedChats, setArchivedChats] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [geoLocation, setGeoLocation] = useState(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [showArchive, setShowArchive] = useState(false);

  useEffect(() => {
    fetchChats();
    archiveOldChats().catch(console.error);
    cleanupEmptyChats().catch(console.error);
  }, []);

  const fetchChats = async () => {
    try {
      const [activeRes, archivedRes] = await Promise.all([
        getActiveChats(),
        getArchivedChats(),
      ]);
      setActiveChats(activeRes.data);
      setArchivedChats(archivedRes.data);
    } catch (error) {
      console.error('Error fetching chats:', error);
    }
  };

  const fetchMessages = async (chatId) => {
    try {
      const response = await getMessages(chatId);
      setMessages(response.data);
    } catch (error) {
      console.error('Error fetching messages:', error);
    }
  };

  const fetchGeoLocation = async (ip) => {
    const location = await getGeoLocation(ip);
    setGeoLocation(location);
  };

  const handleChatClick = (chat) => {
    setSelectedChat(chat);
    setNewTitle(chat.title);
    setEditingTitle(false);
    fetchMessages(chat.id);
    if (chat.ip_address && chat.ip_address !== '0.0.0.0') {
      fetchGeoLocation(chat.ip_address);
    } else {
      setGeoLocation(null);
    }
  };

  const handleDeleteChat = async (chatId) => {
    if (window.confirm('Вы уверены, что хотите удалить этот чат?')) {
      try {
        await deleteChat(chatId);
        setActiveChats(activeChats.filter((chat) => chat.id !== chatId));
        setArchivedChats(archivedChats.filter((chat) => chat.id !== chatId));
        if (selectedChat && selectedChat.id === chatId) {
          setSelectedChat(null);
          setMessages([]);
          setGeoLocation(null);
        }
      } catch (error) {
        console.error('Error deleting chat:', error);
        alert('Ошибка при удалении чата');
      }
    }
  };

  const handleUnarchive = async (chatId, e) => {
    e.stopPropagation();
    try {
      await unarchiveChat(chatId);
      fetchChats();
    } catch (error) {
      console.error('Error unarchiving chat:', error);
    }
  };

  const handleTitleEdit = () => {
    setEditingTitle(true);
  };

  const handleTitleSave = async () => {
    try {
      await updateChat(selectedChat.id, { title: newTitle });
      setSelectedChat({ ...selectedChat, title: newTitle });
      setEditingTitle(false);
      fetchChats();
    } catch (error) {
      console.error('Error updating chat title:', error);
      alert('Ошибка при обновлении заголовка');
    }
  };

  const handleTitleCancel = () => {
    setNewTitle(selectedChat.title);
    setEditingTitle(false);
  };

  const currentChats = showArchive ? archivedChats : activeChats;
  const groupedChats = groupChatsByDate(currentChats);

  return (
    <div className="admin-panel">
      <h1>Админ панель - История чатов</h1>

      <div className="admin-tabs">
        <button
          type="button"
          className={`tab-btn ${!showArchive ? 'active' : ''}`}
          onClick={() => setShowArchive(false)}
        >
          Активные ({activeChats.length})
        </button>
        <button
          type="button"
          className={`tab-btn ${showArchive ? 'active' : ''}`}
          onClick={() => setShowArchive(true)}
        >
          Архив ({archivedChats.length})
        </button>
      </div>

      <div className="admin-content">
        <div className="chats-list">
          <h2>{showArchive ? 'Архив' : 'Чаты'}</h2>

          {Object.keys(groupedChats).length === 0 ? (
            <p className="no-chats">Нет чатов</p>
          ) : (
            Object.entries(groupedChats).map(([dateLabel, chats]) => (
              <div key={dateLabel} className="chat-day-group">
                <div className="day-label">{dateLabel}</div>
                <ul>
                  {chats.map((chat) => (
                    <li
                      key={chat.id}
                      onClick={() => handleChatClick(chat)}
                      className={selectedChat && selectedChat.id === chat.id ? 'selected' : ''}
                    >
                      <div className="chat-info">
                        <div className="chat-icon">💬</div>
                        <div className="chat-details">
                          <div className="chat-title">{chat.title}</div>
                          <div className="chat-meta">
                            {formatTime(chat.created_at)} • IP: {chat.ip_address || 'Неизвестен'}
                          </div>
                        </div>
                      </div>
                      <div className="chat-actions">
                        {showArchive && (
                          <button
                            type="button"
                            className="unarchive-btn"
                            onClick={(e) => handleUnarchive(chat.id, e)}
                            title="Восстановить из архива"
                          >
                            📤
                          </button>
                        )}
                        <button
                          type="button"
                          className="delete-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteChat(chat.id);
                          }}
                          title="Удалить чат"
                        >
                          🗑️
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>

        {selectedChat && (
          <div className="chat-messages">
            <div className="chat-header">
              {editingTitle ? (
                <div className="title-edit">
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleTitleSave()}
                  />
                  <button type="button" onClick={handleTitleSave}>
                    💾
                  </button>
                  <button type="button" onClick={handleTitleCancel}>
                    ❌
                  </button>
                </div>
              ) : (
                <div className="title-display">
                  <h2 onClick={handleTitleEdit} style={{ cursor: 'pointer' }}>
                    {selectedChat.title}
                  </h2>
                  <button type="button" onClick={handleTitleEdit} className="edit-btn">
                    ✏️
                  </button>
                </div>
              )}
              <div className="chat-info">
                <p>
                  <strong>Дата создания:</strong>{' '}
                  {new Date(selectedChat.created_at).toLocaleString('ru-RU')}
                </p>
                <p>
                  <strong>IP адрес:</strong> {selectedChat.ip_address || 'Неизвестен'}
                </p>
                {selectedChat.is_archived && (
                  <p>
                    <strong>Статус:</strong> В архиве
                  </p>
                )}
                {geoLocation && (
                  <p>
                    <strong>Местоположение:</strong> {geoLocation.city}, {geoLocation.region},{' '}
                    {geoLocation.country_name}
                  </p>
                )}
              </div>
            </div>
            <div className="messages-container">
              <h3>Сообщения ({messages.length})</h3>
              <ul>
                {messages.map((message) => {
                  const isUser = message.is_user;
                  return (
                    <li key={message.id} className={isUser ? 'user' : 'bot'}>
                      {isUser ? (
                        <>
                          <div className={`message-content ${isUser ? 'user' : 'bot'}`}>
                            <div className={`message-bubble ${isUser ? 'user' : 'bot'}`}>
                              {message.content}
                              {message.image_url && (
                                <div className="message-image">
                                  <img
                                    src={message.image_url}
                                    alt="Прикреплённое фото"
                                    onClick={() => window.open(message.image_url, '_blank')}
                                  />
                                </div>
                              )}
                              {message.attachment_url && (
                                <div className="message-attachment">
                                  <a href={message.attachment_url} target="_blank" rel="noopener noreferrer">
                                    📎 Вложение (PDF / файл)
                                  </a>
                                </div>
                              )}
                            </div>
                            <div className={`message-time ${isUser ? 'user' : 'bot'}`}>
                              {formatTime(message.created_at)}
                            </div>
                          </div>
                          <div className={`avatar ${isUser ? 'user' : 'bot'}`}>U</div>
                        </>
                      ) : (
                        <>
                          <div className={`avatar ${isUser ? 'user' : 'bot'}`}>B</div>
                          <div className={`message-content ${isUser ? 'user' : 'bot'}`}>
                            <div className={`message-bubble ${isUser ? 'user' : 'bot'}`}>
                              {message.content}
                              {message.image_url && (
                                <div className="message-image">
                                  <img
                                    src={message.image_url}
                                    alt="Прикреплённое фото"
                                    onClick={() => window.open(message.image_url, '_blank')}
                                  />
                                </div>
                              )}
                              {message.attachment_url && (
                                <div className="message-attachment">
                                  <a href={message.attachment_url} target="_blank" rel="noopener noreferrer">
                                    📎 Вложение (PDF / файл)
                                  </a>
                                </div>
                              )}
                            </div>
                            <div className={`message-time ${isUser ? 'user' : 'bot'}`}>
                              {formatTime(message.created_at)}
                            </div>
                          </div>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
