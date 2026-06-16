import { useEffect, useLayoutEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Header } from './components/Header';
import { AdminPanel } from './components/AdminPanel';
import { ChatWidget } from './components/ChatWidget';
import './App.css';

function WidgetPage() {
  return (
    <main className="widget-page" aria-label="Чат-виджет Turbo-don">
      <ChatWidget />
    </main>
  );
}

function App() {
  const basename = (process.env.PUBLIC_URL || '').replace(/\/$/, '') || undefined;

  useLayoutEffect(() => {
    const embedded = window.parent !== window;
    document.documentElement.classList.toggle('widget-embed', embedded);
    document.body.classList.toggle('widget-embed', embedded);
    return () => {
      document.documentElement.classList.remove('widget-embed');
      document.body.classList.remove('widget-embed');
    };
  }, []);

  return (
    <Router basename={basename}>
      <div className="App">
        <Routes>
          <Route path="/" element={<WidgetPage />} />
          <Route
            path="/admin"
            element={(
              <>
                <Header />
                <AdminPanel />
              </>
            )}
          />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
