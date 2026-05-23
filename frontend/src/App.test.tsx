import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

describe('App routing', () => {
  it('redirects "/" to "/cases" and renders CasesPage', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page-cases')).toBeInTheDocument();
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
