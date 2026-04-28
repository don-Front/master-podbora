import { Link } from 'react-router-dom';

export function Header() {
  return (
    <header className="app-header">
      <nav>
        <Link to="/admin">Админ панель</Link>
      </nav>
    </header>
  );
}
