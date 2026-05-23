import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div data-testid="page-404">
      404 — page not found{' '}
      <Link to="/" data-testid="404-home">home</Link>
    </div>
  );
}
