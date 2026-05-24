/**
 * AdminPage landing — smoke test (M6-4, post-Settings refactor 2026-05-25).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminPage from './AdminPage';

describe('AdminPage', () => {
  it('renders skip-list + external-services links (Settings removed 2026-05-25)', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page-admin')).toBeInTheDocument();

    const skip = screen.getByTestId('admin-link-skip-list');
    expect(skip.getAttribute('href')).toBe('/admin/skip-list');

    const extSvc = screen.getByTestId('admin-link-external-services');
    expect(extSvc.getAttribute('href')).toBe('/admin/external-services');

    // Settings link must NOT render — endpoint + page deleted
    expect(screen.queryByTestId('admin-link-settings')).toBeNull();
  });
});
