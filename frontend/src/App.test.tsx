import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

beforeEach(() => {
  // v1.17: routes are gated on localStorage.authToken via <RequireAuth>.
  // Seed a token so protected-route tests get past the gate. Mock fetch
  // for Layout's useEffect → fetchMe() + DashboardPage data fetches.
  if (typeof localStorage !== 'undefined') {
    localStorage.clear();
    localStorage.setItem('authToken', 'test-token');
  }
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ username: 'admin', must_change_password: false }),
    }),
  );
});

describe('App routing', () => {
  it('redirects "/" to "/dashboard" (M5-2)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    // DashboardPage starts in loading state when first mounted (fetches data)
    expect(screen.getByTestId('page-dashboard-loading')).toBeInTheDocument();
  });

  it('renders NotFoundPage for unknown routes', () => {
    render(
      <MemoryRouter initialEntries={['/no-such-route']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page-404')).toBeInTheDocument();
  });

  it('redirects to /login when no auth token (v1.17 RequireAuth)', () => {
    if (typeof localStorage !== 'undefined') localStorage.removeItem('authToken');
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page-login')).toBeInTheDocument();
  });
});
