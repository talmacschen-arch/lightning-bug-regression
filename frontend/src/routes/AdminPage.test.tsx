/**
 * AdminPage landing — smoke test (M6-4).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminPage from './AdminPage';

describe('AdminPage', () => {
  it('renders skip-list + settings links', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('page-admin')).toBeInTheDocument();
    const skip = screen.getByTestId('admin-link-skip-list');
    const settings = screen.getByTestId('admin-link-settings');
    expect(skip.getAttribute('href')).toBe('/admin/skip-list');
    expect(settings.getAttribute('href')).toBe('/admin/settings');
  });
});
