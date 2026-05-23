import { Link, Outlet } from 'react-router-dom';

export function Layout() {
  return (
    <div className="app-shell">
      <header className="header">
        <span className="app-title">Lightning Bug Regression</span>
        <nav className="nav">
          <Link to="/cases" data-testid="nav-cases">Cases</Link>
          <Link to="/cases/new" data-testid="nav-cases-new">New Case</Link>
          <Link to="/runs" data-testid="nav-runs">Runs</Link>
        </nav>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
