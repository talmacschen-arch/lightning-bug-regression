import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CaseNewPage from './CaseNewPage';
import { Toaster } from '@/components/ui/toaster';
import { stripSkillFence } from '@/lib/skillFence';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Render CaseNewPage with Toaster so toast() output appears in DOM. */
function renderPage() {
  return render(
    <MemoryRouter>
      <CaseNewPage />
      <Toaster />
    </MemoryRouter>,
  );
}

/** Activate a Radix Tabs trigger using mouseDown (Radix v1 pattern). */
function activateTab(testId: string) {
  fireEvent.mouseDown(screen.getByTestId(testId), { button: 0, ctrlKey: false });
}

// ---------------------------------------------------------------------------
// stripSkillFence — pure function unit tests (M3a-6)
// ---------------------------------------------------------------------------

describe('stripSkillFence', () => {
  it('returns input unchanged when no fence markers are present', () => {
    const input = 'id: my-case\ntitle: test\n';
    expect(stripSkillFence(input)).toBe(input);
  });

  it('strips fence and returns only inner YAML when both markers present', () => {
    const inner = 'id: my-case\ntitle: stripped\n';
    const input = `Some skill preamble\n─── BEGIN YAML ───\n${inner}─── END YAML ───\nSome footer text`;
    expect(stripSkillFence(input)).toBe(inner.trim());
  });

  it('returns input unchanged when BEGIN is present but END is missing (defensive)', () => {
    const input = 'Some text\n─── BEGIN YAML ───\nid: foo\n';
    expect(stripSkillFence(input)).toBe(input);
  });

  it('handles fence markers with no surrounding text', () => {
    const inner = 'id: bare\n';
    const input = `─── BEGIN YAML ───\n${inner}─── END YAML ───`;
    expect(stripSkillFence(input)).toBe(inner.trim());
  });

  it('preserves YAML content exactly (no content munging)', () => {
    const inner = 'id: precise\nsteps:\n  - kind: sql\n    sql: "SELECT 1"\n';
    const input = `preamble\n─── BEGIN YAML ───\n${inner}─── END YAML ───\nfooter`;
    expect(stripSkillFence(input)).toBe(inner.trim());
  });
});

// ---------------------------------------------------------------------------
// CaseNewPage — rendering
// ---------------------------------------------------------------------------

describe('CaseNewPage rendering', () => {
  it('renders page with correct data-testid', () => {
    renderPage();
    expect(screen.getByTestId('page-case-new')).toBeInTheDocument();
    expect(screen.getByTestId('tab-entry-a')).toBeInTheDocument();
    expect(screen.getByTestId('tab-entry-b')).toBeInTheDocument();
    expect(screen.getByTestId('textarea-yaml-editor')).toBeInTheDocument();
    expect(screen.getByTestId('btn-validate')).toBeInTheDocument();
    expect(screen.getByTestId('btn-try')).toBeInTheDocument();
    expect(screen.getByTestId('btn-save')).toBeInTheDocument();
    expect(screen.getByTestId('panel-step-results')).toBeInTheDocument();
  });

  it('btn-try is disabled initially (validateOk=false)', () => {
    renderPage();
    const btn = screen.getByTestId('btn-try') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('btn-save is disabled initially (tryOk=false)', () => {
    renderPage();
    const btn = screen.getByTestId('btn-save') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('btn-validate is enabled initially', () => {
    renderPage();
    const btn = screen.getByTestId('btn-validate') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// M3a-5: btn-generate-stub toast
// ---------------------------------------------------------------------------

describe('M3a-5: btn-generate-stub toast', () => {
  it('btn-generate-stub click shows M3a-5 not yet wired toast', async () => {
    renderPage();
    // btn-generate-stub is in Tab A which is the default active tab
    const btn = screen.getByTestId('btn-generate-stub');
    fireEvent.click(btn);
    // The Toaster renders toasts — findByText searches within the full document
    await screen.findByText(/M3a-5 not yet wired/);
  });
});

// ---------------------------------------------------------------------------
// M3a-6: Tab B paste with skill-fence stripping
// ---------------------------------------------------------------------------

describe('M3a-6: Tab B skill-fence stripping', () => {
  it('plain YAML paste mirrors directly to textarea-yaml-editor', async () => {
    renderPage();
    // Switch to tab B using mouseDown (Radix Tabs v1 activation pattern)
    activateTab('tab-entry-b');
    await waitFor(() =>
      expect(screen.getByTestId('textarea-entry-b')).toBeInTheDocument(),
    );
    const yamlEditor = screen.getByTestId('textarea-yaml-editor') as HTMLTextAreaElement;
    const pasteArea = screen.getByTestId('textarea-entry-b') as HTMLTextAreaElement;

    const plain = 'id: my-case\ntitle: plain paste\n';
    fireEvent.change(pasteArea, { target: { value: plain } });

    expect(yamlEditor.value).toBe(plain);
  });

  it('paste with skill fence strips markers and puts only inner YAML in editor', async () => {
    renderPage();
    activateTab('tab-entry-b');
    await waitFor(() =>
      expect(screen.getByTestId('textarea-entry-b')).toBeInTheDocument(),
    );

    const inner = 'id: my-case\ntitle: fenced\n';
    const fenced = `Some preamble\n─── BEGIN YAML ───\n${inner}─── END YAML ───\nSome footer`;

    const pasteArea = screen.getByTestId('textarea-entry-b') as HTMLTextAreaElement;
    const yamlEditor = screen.getByTestId('textarea-yaml-editor') as HTMLTextAreaElement;

    fireEvent.change(pasteArea, { target: { value: fenced } });

    // entry-b keeps raw
    expect(pasteArea.value).toBe(fenced);
    // yaml editor gets stripped inner
    expect(yamlEditor.value).toBe(inner.trim());
  });

  it('paste with BEGIN but no END does not strip (defensive)', async () => {
    renderPage();
    activateTab('tab-entry-b');
    await waitFor(() =>
      expect(screen.getByTestId('textarea-entry-b')).toBeInTheDocument(),
    );

    const incomplete = 'preamble\n─── BEGIN YAML ───\nid: foo\n';
    const pasteArea = screen.getByTestId('textarea-entry-b') as HTMLTextAreaElement;
    const yamlEditor = screen.getByTestId('textarea-yaml-editor') as HTMLTextAreaElement;

    fireEvent.change(pasteArea, { target: { value: incomplete } });
    expect(yamlEditor.value).toBe(incomplete);
  });
});

// ---------------------------------------------------------------------------
// M3a-7: three-gate state machine
// ---------------------------------------------------------------------------

describe('M3a-7: three-gate state machine', () => {
  beforeEach(() => {
    vi.spyOn(global, 'fetch');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('handleValidate ok=true enables btn-try', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({ ok: true, errors: [] }),
    );

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test-case\n' },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });

    await waitFor(() => {
      const btn = screen.getByTestId('btn-try') as HTMLButtonElement;
      expect(btn.disabled).toBe(false);
    });
  });

  it('handleValidate ok=false renders validate-errors-list', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({
        ok: false,
        errors: [
          { where: 'top-level', reason: 'id is missing' },
          { where: 'schema', reason: 'category is required' },
        ],
      }),
    );

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'bad: yaml\n' },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('validate-errors-list')).toBeInTheDocument();
    });

    const items = screen
      .getByTestId('validate-errors-list')
      .querySelectorAll('li');
    expect(items).toHaveLength(2);
    // btn-try must still be disabled
    expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(true);
  });

  it('handleTry ok=true renders step rows and enables btn-save', async () => {
    // First validate call
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({ ok: true, errors: [] }),
    );
    // Then try call
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({
        ok: true,
        yaml_sha256: 'abc123',
        step_results: [
          { step_id: 'step-0', kind: 'sql', status: 'pass', duration_ms: 5, stderr_preview: null },
          { step_id: 'step-1', kind: 'sql', status: 'fail', duration_ms: 3, stderr_preview: 'error output here' },
        ],
        validation_errors: [],
      }),
    );

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test-case\n' },
    });

    // Validate first
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(false),
    );

    // Try
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-try'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('try-step-row-0')).toBeInTheDocument();
      expect(screen.getByTestId('try-step-row-1')).toBeInTheDocument();
    });

    // step-1 has stderr_preview
    expect(screen.getByTestId('try-stderr-preview-1')).toBeInTheDocument();
    expect(screen.getByTestId('try-stderr-preview-1').textContent).toContain('error output here');

    // btn-save should now be enabled (try ok=true)
    await waitFor(() => {
      expect((screen.getByTestId('btn-save') as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it('editing textarea-yaml-editor resets validateOk and tryOk (btn-try and btn-save go disabled)', async () => {
    // Validate
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({ ok: true, errors: [] }),
    );
    // Try
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({
        ok: true,
        yaml_sha256: 'abc',
        step_results: [],
        validation_errors: [],
      }),
    );

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test\n' },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(false),
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-try'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-save') as HTMLButtonElement).disabled).toBe(false),
    );

    // Edit the YAML — should reset both gates
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: changed\n' },
    });

    expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId('btn-save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('handleValidate network error shows error-msg', async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new Error('network failure'));

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test\n' },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('error-msg')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-msg').textContent).toContain('network failure');
    expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(true);
  });

  it('handleSave success renders link-pr-url', async () => {
    // validate
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({ ok: true, errors: [] }),
    );
    // try
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({
        ok: true,
        yaml_sha256: 'sha999',
        step_results: [],
        validation_errors: [],
      }),
    );
    // submit
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({
        pr_url: 'https://github.com/example/pr/99',
        pr_number: 99,
        branch: 'case/test-case',
      }),
    );

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test-case\ntitle: foo\n' },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(false),
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-try'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-save') as HTMLButtonElement).disabled).toBe(false),
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-save'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('link-pr-url')).toBeInTheDocument();
    });

    const link = screen.getByTestId('link-pr-url') as HTMLAnchorElement;
    expect(link.href).toBe('https://github.com/example/pr/99');
    expect(link.textContent).toContain('#99');
  });
});
