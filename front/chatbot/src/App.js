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
  return (
    <Router>
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
