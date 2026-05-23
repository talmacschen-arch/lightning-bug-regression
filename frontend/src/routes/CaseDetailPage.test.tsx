import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import CaseDetailPage from './CaseDetailPage';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReset();
});

const fakeCaseDetail = {
  id: 'CASE-001',
  category: 'bug_regression',
  title: 'Test case title',
  status: 'active',
  destructive: false,
  tags: ['tag-a', 'tag-b'],
  yaml_raw: 'id: CASE-001\ntitle: Test case title\n',
  parsed: {
    description: 'This is a description.',
    procedure: 'Step 1\nStep 2',
    expected: 'All should pass.',
    artifacts: null,
    related_pr: 'https://github.com/example/repo/pull/1',
    related_issue: '',
    links: [
      'https://example.com/link1',
      { url: 'https://example.com/link2', label: 'Label Link 2' },
    ],
  },
  error: null,
};

function renderWithRoute(path: string, initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path={path} element={<CaseDetailPage />} />
        <Route path="/cases" element={<div data-testid="page-cases">Cases</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('CaseDetailPage', () => {
  it('shows loading skeleton initially then renders case detail', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeCaseDetail),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    // Loading skeleton should appear first
    expect(screen.getByTestId('case-detail-loading')).toBeInTheDocument();

    // Wait for the data to load
    await waitFor(() => {
      expect(screen.getByTestId('page-case-detail')).toBeInTheDocument();
    });

    // Verify fetch was called with path substituted
    const [calledUrl] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toContain('/cases/CASE-001');
  });

  it('renders yaml_raw in <pre data-testid="case-yaml-raw">', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeCaseDetail),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-yaml-raw')).toBeInTheDocument();
    });

    const pre = screen.getByTestId('case-yaml-raw');
    expect(pre.tagName).toBe('PRE');
    expect(pre.textContent).toContain('CASE-001');
  });

  it('renders title, status badge, category, and tags', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeCaseDetail),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-title')).toHaveTextContent('Test case title');
    });

    expect(screen.getByTestId('case-detail-status-badge')).toHaveTextContent('active');
    expect(screen.getByTestId('case-detail-category')).toHaveTextContent('bug_regression');
    expect(screen.getByTestId('case-detail-tags')).toBeInTheDocument();
    expect(screen.getByTestId('case-detail-tag-tag-a')).toBeInTheDocument();
    expect(screen.getByTestId('case-detail-tag-tag-b')).toBeInTheDocument();
  });

  it('renders parsed narrative sections when present', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeCaseDetail),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-section-description')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-detail-section-description')).toHaveTextContent('This is a description.');
    expect(screen.getByTestId('case-detail-section-procedure')).toHaveTextContent('Step 1');
    expect(screen.getByTestId('case-detail-section-expected')).toHaveTextContent('All should pass.');
  });

  it('does not render missing parsed sections', async () => {
    const caseWithoutExpected = {
      ...fakeCaseDetail,
      parsed: {
        description: 'Only description',
        // procedure, expected omitted
      },
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(caseWithoutExpected),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-section-description')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('case-detail-section-procedure')).not.toBeInTheDocument();
    expect(screen.queryByTestId('case-detail-section-expected')).not.toBeInTheDocument();
  });

  it('renders related links from parsed.related_pr and parsed.links', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(fakeCaseDetail),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-link-0')).toBeInTheDocument();
    });

    // related_pr is index 0
    const link0 = screen.getByTestId('case-link-0') as HTMLAnchorElement;
    expect(link0.href).toBe('https://github.com/example/repo/pull/1');
    expect(link0.target).toBe('_blank');
    expect(link0.rel).toContain('noreferrer');

    // links[0] is index 1 (related_issue is empty so skipped)
    expect(screen.getByTestId('case-link-1')).toBeInTheDocument();
    // links[1] with label
    expect(screen.getByTestId('case-link-2')).toHaveTextContent('Label Link 2');
  });

  it('renders 404 not-found UI when fetch returns 404', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ detail: 'Case not found' }),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-MISSING');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-not-found')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-detail-back-link')).toBeInTheDocument();
    expect(screen.getByTestId('case-detail-back-link')).toHaveAttribute('href', '/cases');
  });

  it('renders error notice when case has parse error', async () => {
    const invalidCase = {
      ...fakeCaseDetail,
      status: 'invalid',
      error: 'YAML parse failed at line 3',
      parsed: null,
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(invalidCase),
    });

    renderWithRoute('/cases/:id', '/cases/CASE-001');

    await waitFor(() => {
      expect(screen.getByTestId('case-detail-error')).toBeInTheDocument();
    });

    expect(screen.getByTestId('case-detail-error')).toHaveTextContent('YAML parse failed at line 3');
  });
});
