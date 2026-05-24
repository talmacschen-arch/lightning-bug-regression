import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

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
});
