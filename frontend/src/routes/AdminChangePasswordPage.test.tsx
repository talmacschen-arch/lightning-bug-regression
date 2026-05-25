/**
 * AdminChangePasswordPage unit tests (v1.17).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AdminChangePasswordPage from './AdminChangePasswordPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
  if (typeof localStorage !== 'undefined') {
    localStorage.clear();
    localStorage.setItem('authToken', 'test-token');
  }
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockJson(body: unknown, ok = true, status = ok ? 200 : 400) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Bad',
    json: () => Promise.resolve(body),
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminChangePasswordPage />
    </MemoryRouter>,
  );
}

describe('AdminChangePasswordPage', () => {
  it('renders 3 password inputs + submit', () => {
    renderPage();
    expect(screen.getByTestId('cp-current')).toBeInTheDocument();
    expect(screen.getByTestId('cp-new')).toBeInTheDocument();
    expect(screen.getByTestId('cp-confirm')).toBeInTheDocument();
    expect(screen.getByTestId('cp-submit')).toBeInTheDocument();
  });

  it('rejects new password <4 chars', async () => {
    renderPage();
    fireEvent.change(screen.getByTestId('cp-current'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('cp-new'), { target: { value: 'abc' } });
    fireEvent.change(screen.getByTestId('cp-confirm'), { target: { value: 'abc' } });
    fireEvent.click(screen.getByTestId('cp-submit'));
    await waitFor(() => {
      expect(screen.getByTestId('cp-error')).toHaveTextContent('at least 4');
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('rejects when new == current', async () => {
    renderPage();
    fireEvent.change(screen.getByTestId('cp-current'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('cp-new'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('cp-confirm'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByTestId('cp-submit'));
    await waitFor(() => {
      expect(screen.getByTestId('cp-error')).toHaveTextContent('differ');
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('rejects when new != confirm', async () => {
    renderPage();
    fireEvent.change(screen.getByTestId('cp-current'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('cp-new'), { target: { value: 'newpass1' } });
    fireEvent.change(screen.getByTestId('cp-confirm'), { target: { value: 'newpass2' } });
    fireEvent.click(screen.getByTestId('cp-submit'));
    await waitFor(() => {
      expect(screen.getByTestId('cp-error')).toHaveTextContent('match');
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('successful change → success message + bearer header sent + body shape', async () => {
    mockFetch.mockResolvedValueOnce(mockJson({}, true, 204));
    renderPage();
    fireEvent.change(screen.getByTestId('cp-current'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('cp-new'), { target: { value: 'newpass1' } });
    fireEvent.change(screen.getByTestId('cp-confirm'), { target: { value: 'newpass1' } });
    fireEvent.click(screen.getByTestId('cp-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('cp-success')).toBeInTheDocument();
    });

    const call = mockFetch.mock.calls[0];
    expect(call[0]).toContain('/auth/change-password');
    expect(call[1].method).toBe('POST');
    expect(call[1].headers.Authorization).toBe('Bearer test-token');
    expect(JSON.parse(call[1].body)).toEqual({
      current_password: 'admin',
      new_password: 'newpass1',
    });
  });

  it('shows backend error (e.g. wrong current password 401)', async () => {
    mockFetch.mockResolvedValueOnce(
      mockJson({ detail: 'current password is wrong' }, false, 401),
    );
    renderPage();
    fireEvent.change(screen.getByTestId('cp-current'), { target: { value: 'wrong' } });
    fireEvent.change(screen.getByTestId('cp-new'), { target: { value: 'newpass1' } });
    fireEvent.change(screen.getByTestId('cp-confirm'), { target: { value: 'newpass1' } });
    fireEvent.click(screen.getByTestId('cp-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('cp-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('cp-error')).toHaveTextContent('current password is wrong');
  });
});
