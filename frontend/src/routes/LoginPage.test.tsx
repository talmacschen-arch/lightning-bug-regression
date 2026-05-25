/**
 * LoginPage unit tests (v1.17).
 */
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import LoginPage from './LoginPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockJson(body: unknown, ok = true, status = ok ? 200 : 401) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Unauthorized',
    json: () => Promise.resolve(body),
  };
}

function renderAt(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<div data-testid="page-dashboard">Home</div>} />
        <Route path="/admin" element={<div data-testid="page-admin">Admin</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('LoginPage', () => {
  it('renders username + password inputs + submit button', () => {
    renderAt();
    expect(screen.getByTestId('page-login')).toBeInTheDocument();
    expect(screen.getByTestId('login-username')).toBeInTheDocument();
    expect(screen.getByTestId('login-password')).toBeInTheDocument();
    expect(screen.getByTestId('login-submit')).toBeInTheDocument();
  });

  it('shows initial credentials hint (admin/admin)', () => {
    renderAt();
    const text = screen.getByTestId('page-login').textContent ?? '';
    expect(text).toContain('admin');
    expect(text).toContain('初始账号');
  });

  it('successful login stores token + navigates to /dashboard', async () => {
    mockFetch.mockResolvedValueOnce(
      mockJson({
        token: 'fake-token-xyz',
        username: 'admin',
        must_change_password: true,
      }),
    );

    renderAt();
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByTestId('login-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
    });
    expect(localStorage.getItem('authToken')).toBe('fake-token-xyz');
  });

  it('honors ?next=<path> for deep link redirect after login', async () => {
    mockFetch.mockResolvedValueOnce(
      mockJson({ token: 't', username: 'admin', must_change_password: false }),
    );

    renderAt('/login?next=%2Fadmin');
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByTestId('login-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('page-admin')).toBeInTheDocument();
    });
  });

  it('shows error on wrong credentials, does not store token', async () => {
    mockFetch.mockResolvedValueOnce(
      mockJson({ detail: 'invalid username or password' }, false, 401),
    );

    renderAt();
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByTestId('login-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('login-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('login-error')).toHaveTextContent('invalid');
    expect(localStorage.getItem('authToken')).toBeNull();
  });

  it('submit button disabled while submitting', async () => {
    let resolve!: (v: typeof mockFetch) => void;
    mockFetch.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r as unknown as typeof resolve;
      }),
    );

    renderAt();
    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByTestId('login-submit'));

    const btn = screen.getByTestId('login-submit') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Signing in');

    // Cleanup: resolve so the promise doesn't hang
    resolve(mockJson({ token: 'x', username: 'admin', must_change_password: false }) as never);
  });
});
