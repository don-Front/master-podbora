import { useEffect, useState, useCallback, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { 
  getActiveChats, getArchivedChats, getMessages, createChat, createMessage, 
  updateChat, deleteChat, getGeoLocation, finalizeChat, unarchiveChat,
  archiveOldChats, cleanupEmptyChats
} from './api';
import './App.css';

function App() {
  return (
    <Router>
      <div className="App">
        <Header />
        <Routes>
          <Route path="/" element={<ChatWidget />} />
          <Route path="/admin" element={<AdminPanel />} />
        </Routes>
      </div>
    </Router>
  );
}

function Header() {
  return (
    <header className="app-header">
      <nav>
        <Link to="/admin">Админ панель</Link>
      </nav>
    </header>
  );
}

// Группировка чатов по дням
function groupChatsByDate(chats) {
  const groups = {};
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  
  chats.forEach(chat => {
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
        year: chatDate.getFullYear() !== today.getFullYear() ? 'numeric' : undefined
      });
    }
    
    if (!groups[label]) {
      groups[label] = [];
    }
    groups[label].push(chat);
  });
  
  return groups;
}

function AdminPanel() {
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
    // Архивируем старые чаты и удаляем пустые при загрузке
    archiveOldChats().catch(console.error);
    cleanupEmptyChats().catch(console.error);
  }, []);

  const fetchChats = async () => {
    try {
      const [activeRes, archivedRes] = await Promise.all([
        getActiveChats(),
        getArchivedChats()
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
        setActiveChats(activeChats.filter(chat => chat.id !== chatId));
        setArchivedChats(archivedChats.filter(chat => chat.id !== chatId));
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

  const formatTime = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const currentChats = showArchive ? archivedChats : activeChats;
  const groupedChats = groupChatsByDate(currentChats);

  return (
    <div className="admin-panel">
      <h1>Админ панель - История чатов</h1>
      
      <div className="admin-tabs">
        <button 
          className={`tab-btn ${!showArchive ? 'active' : ''}`}
          onClick={() => setShowArchive(false)}
        >
          Активные ({activeChats.length})
        </button>
        <button 
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
                  {chats.map(chat => (
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
                            className="unarchive-btn"
                            onClick={(e) => handleUnarchive(chat.id, e)}
                            title="Восстановить из архива"
                          >
                            📤
                          </button>
                        )}
                        <button 
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
                    onKeyPress={(e) => e.key === 'Enter' && handleTitleSave()}
                  />
                  <button onClick={handleTitleSave}>💾</button>
                  <button onClick={handleTitleCancel}>❌</button>
                </div>
              ) : (
                <div className="title-display">
                  <h2 onClick={handleTitleEdit} style={{cursor: 'pointer'}}>{selectedChat.title}</h2>
                  <button onClick={handleTitleEdit} className="edit-btn">✏️</button>
                </div>
              )}
              <div className="chat-info">
                <p><strong>Дата создания:</strong> {new Date(selectedChat.created_at).toLocaleString('ru-RU')}</p>
                <p><strong>IP адрес:</strong> {selectedChat.ip_address || 'Неизвестен'}</p>
                {selectedChat.is_archived && <p><strong>Статус:</strong> В архиве</p>}
                {geoLocation && (
                  <p><strong>Местоположение:</strong> {geoLocation.city}, {geoLocation.region}, {geoLocation.country_name}</p>
                )}
              </div>
            </div>
            <div className="messages-container">
              <h3>Сообщения ({messages.length})</h3>
              <ul>
                {messages.map(message => (
                  <li key={message.id} className={message.is_user ? 'user' : 'bot'}>
                    <div className={`avatar ${message.is_user ? 'user' : 'bot'}`}>
                      {message.is_user ? 'U' : 'B'}
                    </div>
                    <div className={`message-content ${message.is_user ? 'user' : 'bot'}`}>
                      <div className={`message-bubble ${message.is_user ? 'user' : 'bot'}`}>
                        {message.content}
                      </div>
                      <div className={`message-time ${message.is_user ? 'user' : 'bot'}`}>
                        {formatTime(message.created_at)}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState([
    {
      id: 1,
      from: 'bot',
      text: 'Здравствуйте! Я консультант по оборудованию. Чем могу помочь?',
      time: new Date()
    }
  ]);
  const [isTyping, setIsTyping] = useState(false);
  const [chatId, setChatId] = useState(null);
  const hasMessages = useRef(false);

  const initializeChat = useCallback(async () => {
    try {
      // Всегда создаём новый чат при каждом заходе на страницу
      const createResponse = await createChat({ 
        title: `Новый чат` 
      });
      const chat = createResponse.data;
      setChatId(chat.id);
      hasMessages.current = false;
      
      // Начинаем с приветственного сообщения
      setMessages([
        {
          id: 1,
          from: 'bot',
          text: 'Здравствуйте! Я консультант по оборудованию. Чем могу помочь?',
          time: new Date()
        }
      ]);
    } catch (error) {
      console.error('Error initializing chat:', error);
    }
  }, []);

  // Инициализация при монтировании
  useEffect(() => {
    initializeChat();
  }, [initializeChat]);

  // Обработка покидания страницы
  useEffect(() => {
    const handleBeforeUnload = async () => {
      if (chatId) {
        // Используем sendBeacon для надёжной отправки при закрытии
        const url = `http://localhost:8000/api/chats/${chatId}/finalize/`;
        navigator.sendBeacon(url, JSON.stringify({}));
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden' && chatId && hasMessages.current) {
        // Завершаем чат при скрытии страницы
        finalizeChat(chatId).catch(console.error);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      
      // Завершаем чат при размонтировании компонента
      if (chatId && hasMessages.current) {
        finalizeChat(chatId).catch(console.error);
      }
    };
  }, [chatId]);

  const toggleOpen = () => {
    setIsOpen((prev) => !prev);
  };

  const addMessage = async (text, from = 'user') => {
    if (!text.trim()) return;

    const newMessage = {
      id: Date.now(),
      from,
      text: text.trim(),
      time: new Date()
    };

    setMessages((prev) => [...prev, newMessage]);

    // Save to backend and get bot response
    if (chatId && from === 'user') {
      hasMessages.current = true;
      setIsTyping(true);
      try {
        const response = await createMessage(chatId, {
          content: text.trim(),
        });
        
        // Add bot response
        const botMessage = response.data.find(msg => !msg.is_user);
        if (botMessage) {
          const botMsg = {
            id: botMessage.id,
            from: 'bot',
            text: botMessage.content,
            time: new Date(botMessage.created_at)
          };
          setMessages((prev) => [...prev, botMsg]);
        }
      } catch (error) {
        console.error('Error saving message:', error);
        const errorMsg = {
          id: Date.now() + 1,
          from: 'bot',
          text: 'Извините, произошла ошибка. Попробуйте позже.',
          time: new Date()
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setIsTyping(false);
      }
    }
  };

  const handleSend = () => {
    if (!inputValue.trim()) return;
    addMessage(inputValue, 'user');
    setInputValue('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleEmojiClick = (emoji) => {
    setInputValue((prev) => prev + emoji);
  };

  const formatTime = (date) => {
    try {
      const d = date instanceof Date ? date : new Date(date);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  useEffect(() => {
    const container = document.querySelector('.chat-widget__messages');
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, [messages, isOpen, isTyping]);

  return (
    <div className="chat-widget">
      <button
        className={`chat-widget__toggle ${isOpen ? 'chat-widget__toggle--open' : ''}`}
        onClick={toggleOpen}
        aria-label="Открыть чат"
      />

      <div className={`chat-widget__window ${isOpen ? 'chat-widget__window--visible' : ''}`}>
        <header className="chat-widget__header">
          <div className="chat-widget__header-info">
            <div className="chat-widget__avatar" />
            <div>
              <div className="chat-widget__title">Turbo-don чат</div>
              <div className="chat-widget__subtitle">Онлайн • обычно отвечает за пару секунд</div>
            </div>
          </div>
          <button className="chat-widget__close" onClick={toggleOpen} aria-label="Закрыть чат">
            ×
          </button>
        </header>

        <div className="chat-widget__messages">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`chat-widget__message chat-widget__message--${message.from}`}
            >
              <div className="chat-widget__bubble">
                <span>{message.text}</span>
              </div>
              <div className="chat-widget__meta">
                <span className="chat-widget__time">{formatTime(message.time)}</span>
              </div>
            </div>
          ))}

          {isTyping && (
            <div className="chat-widget__message chat-widget__message--bot">
              <div className="chat-widget__bubble chat-widget__bubble--typing">
                <span className="typing-dots">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
              <div className="chat-widget__meta">
                <span className="chat-widget__time">печатает...</span>
              </div>
            </div>
          )}
        </div>

        <div className="chat-widget__footer">
          <div className="chat-widget__emoji-row">
            {['😊', '👍', '💬', '❓'].map((emoji) => (
              <button
                key={emoji}
                type="button"
                className="chat-widget__emoji-btn"
                onClick={() => handleEmojiClick(emoji)}
              >
                {emoji}
              </button>
            ))}
          </div>
          <div className="chat-widget__input-row">
            <textarea
              className="chat-widget__input"
              rows={1}
              placeholder="Напишите сообщение..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            <button
              className="chat-widget__send-btn"
              type="button"
              onClick={handleSend}
              disabled={!inputValue.trim()}
            >
              ➤
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
