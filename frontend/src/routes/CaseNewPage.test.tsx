import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import CaseNewPage from './CaseNewPage';
import { stripSkillFence } from '@/lib/skillFence';
import * as clientModule from '@/api/client';
import { flags } from '@/lib/featureFlags';

// ---------------------------------------------------------------------------
// Mock apiFetch for generate-draft tests
// ---------------------------------------------------------------------------

vi.mock('@/api/client', () => ({
  apiFetch: vi.fn(),
}));

const mockApiFetch = vi.mocked(clientModule.apiFetch);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Render CaseNewPage. */
function renderPage() {
  return render(
    <MemoryRouter>
      <CaseNewPage />
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

  it('shows llm-status-idle initially', () => {
    renderPage();
    expect(screen.getByTestId('llm-status-idle')).toBeInTheDocument();
  });

  it('btn-generate-real is disabled when description is empty', () => {
    renderPage();
    const btn = screen.getByTestId('btn-generate-real') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('btn-generate-real is disabled even when description is non-empty (LLM_FEATURE_ENABLED=false)', async () => {
    renderPage();
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'some description' } });
    const btn = screen.getByTestId('btn-generate-real') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// §M7-followup: LLM feature disabled notice + button wiring
// ---------------------------------------------------------------------------

describe('§M7-followup: LLM disabled notice and button lock', () => {
  it('renders llm-feature-unavailable-notice in Tab A (default tab)', () => {
    renderPage();
    expect(screen.getByTestId('llm-feature-unavailable-notice')).toBeInTheDocument();
  });

  it('btn-generate-real stays disabled even when description is non-empty (LLM_FEATURE_ENABLED wiring)', () => {
    renderPage();
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'some non-empty description that should not unlock the button' } });
    const btn = screen.getByTestId('btn-generate-real') as HTMLButtonElement;
    expect(btn).toBeDisabled();
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

// ---------------------------------------------------------------------------
// M3a-9: Try spinner + elapsed counter
// ---------------------------------------------------------------------------

describe('M3a-9: Try spinner and elapsed counter', () => {
  beforeEach(() => {
    vi.spyOn(global, 'fetch');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('try-spinner and try-elapsed are visible while handleTry is in flight, hidden after resolve', async () => {
    // First: validate
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({ ok: true, errors: [] }),
    );

    // Second: try — manually resolvable promise
    let resolveTry!: (value: Response) => void;
    const tryPromise = new Promise<Response>((r) => {
      resolveTry = r;
    });
    vi.mocked(global.fetch).mockImplementationOnce(() => tryPromise);

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test-case\n' },
    });

    // Validate first to enable btn-try
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(false),
    );

    // Click Try — spinner should appear immediately
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-try'));
    });

    // Spinner and elapsed element must be visible while in flight
    expect(screen.getByTestId('try-spinner')).toBeInTheDocument();
    expect(screen.getByTestId('try-elapsed')).toBeInTheDocument();

    // Resolve the try promise
    await act(async () => {
      resolveTry(
        makeJsonResponse({
          ok: true,
          yaml_sha256: 'abc',
          step_results: [],
          validation_errors: [],
        }),
      );
    });

    // After resolution spinner should be gone
    await waitFor(() => {
      expect(screen.queryByTestId('try-spinner')).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('try-elapsed')).not.toBeInTheDocument();
  });

  it('elapsed counter shows "0.0s" pattern initially while try is in flight', async () => {
    // validate
    vi.mocked(global.fetch).mockResolvedValueOnce(
      makeJsonResponse({ ok: true, errors: [] }),
    );

    // try — manually resolvable (never auto-resolves during this test)
    let resolveTry!: (value: Response) => void;
    const tryPromise = new Promise<Response>((r) => {
      resolveTry = r;
    });
    vi.mocked(global.fetch).mockImplementationOnce(() => tryPromise);

    renderPage();
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: test-case\n' },
    });

    // Validate to enable btn-try
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-validate'));
    });
    await waitFor(() =>
      expect((screen.getByTestId('btn-try') as HTMLButtonElement).disabled).toBe(false),
    );

    // Click Try — spinner appears immediately
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-try'));
    });

    // Right after click: elapsed starts at 0ms → text matches "0.Xs" pattern
    const elapsedEl = screen.getByTestId('try-elapsed');
    expect(elapsedEl.textContent).toMatch(/Trying…\s+\d+\.\ds/);

    // Specifically should start at or very near 0.0s
    expect(elapsedEl.textContent).toContain('Trying…');
    expect(elapsedEl.textContent).toMatch(/\d+\.\ds/);

    // Resolve to clean up
    await act(async () => {
      resolveTry(
        makeJsonResponse({
          ok: true,
          yaml_sha256: 'abc',
          step_results: [],
          validation_errors: [],
        }),
      );
    });

    // After resolution, spinner is gone
    await waitFor(() => {
      expect(screen.queryByTestId('try-elapsed')).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// M7-3: LLM generate-draft state machine
// ---------------------------------------------------------------------------

describe('M7-3: LLM generate-draft state machine', () => {
  beforeEach(() => {
    flags.llmFeatureEnabled = true;
    vi.clearAllMocks();
  });

  afterEach(() => {
    flags.llmFeatureEnabled = false;
    vi.restoreAllMocks();
  });

  /** Type a description and click btn-generate-real */
  async function clickGenerate(description = 'VACUUM crash bug') {
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: description } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate-real'));
    });
  }

  it('shows llm-status-loading while request is in-flight', async () => {
    let resolveGenerate!: (value: unknown) => void;
    mockApiFetch.mockImplementationOnce(
      () => new Promise((r) => { resolveGenerate = r; }),
    );

    renderPage();
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'some description' } });

    act(() => {
      fireEvent.click(screen.getByTestId('btn-generate-real'));
    });

    expect(screen.getByTestId('llm-status-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('llm-status-idle')).not.toBeInTheDocument();

    // Cleanup
    await act(async () => {
      resolveGenerate({
        yaml_draft: 'id: test\n',
        attempts: 1,
        validation_errors_during_retry: [],
      });
    });
  });

  it('success (200): transitions to llm-status-loaded, injects draft into YAML editor', async () => {
    const draftYaml = 'id: lg-bug-test\ntitle: Test bug\ncategory: bug_regression\n';
    mockApiFetch.mockResolvedValueOnce({
      yaml_draft: draftYaml,
      attempts: 1,
      validation_errors_during_retry: [],
    });

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-loaded')).toBeInTheDocument();
    });

    const yamlEditor = screen.getByTestId('textarea-yaml-editor') as HTMLTextAreaElement;
    expect(yamlEditor.value).toBe(draftYaml);
    expect(screen.queryByTestId('llm-status-idle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('llm-status-error')).not.toBeInTheDocument();
  });

  it('success with attempts=3: loaded state shows validation_errors_during_retry', async () => {
    mockApiFetch.mockResolvedValueOnce({
      yaml_draft: 'id: lg-bug-retry\ntitle: retry\ncategory: bug_regression\n',
      attempts: 3,
      validation_errors_during_retry: ['missing field: steps', 'invalid status value'],
    });

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-loaded')).toBeInTheDocument();
    });

    // Should mention retry errors visually
    const loadedEl = screen.getByTestId('llm-status-loaded');
    expect(loadedEl.textContent).toContain('3');
  });

  it('401: transitions to llm-status-error and shows error message', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new Error('generate 失败：HTTP 401 · Not authenticated'),
    );

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    const errorEl = screen.getByTestId('llm-status-error');
    expect(errorEl.textContent).toContain('HTTP 401');
    expect(errorEl.textContent).toContain('Not authenticated');
    expect(screen.queryByTestId('llm-status-loaded')).not.toBeInTheDocument();
  });

  it('413: error panel shows HTTP 413 · detail', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new Error('generate 失败：HTTP 413 · description exceeds 8 KB limit'),
    );

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    const errorEl = screen.getByTestId('llm-status-error');
    expect(errorEl.textContent).toContain('HTTP 413');
    expect(errorEl.textContent).toContain('description exceeds 8 KB limit');
  });

  it('429: error panel shows HTTP 429 · detail', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new Error('generate 失败：HTTP 429 · Anthropic rate limited — try again shortly'),
    );

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    const errorEl = screen.getByTestId('llm-status-error');
    expect(errorEl.textContent).toContain('HTTP 429');
    expect(errorEl.textContent).toContain('rate limited');
  });

  it('502: error panel shows HTTP 502 · detail', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new Error('generate 失败：HTTP 502 · Anthropic API error'),
    );

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    const errorEl = screen.getByTestId('llm-status-error');
    expect(errorEl.textContent).toContain('HTTP 502');
    expect(errorEl.textContent).toContain('Anthropic API error');
  });

  it('503: error panel shows HTTP 503 · detail', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new Error('generate 失败：HTTP 503 · ANTHROPIC_API_KEY not configured'),
    );

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    const errorEl = screen.getByTestId('llm-status-error');
    expect(errorEl.textContent).toContain('HTTP 503');
    expect(errorEl.textContent).toContain('ANTHROPIC_API_KEY');
  });

  it('504: error panel shows HTTP 504 · detail', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new Error('generate 失败：HTTP 504 · LLM request timed out'),
    );

    renderPage();
    await clickGenerate();

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    const errorEl = screen.getByTestId('llm-status-error');
    expect(errorEl.textContent).toContain('HTTP 504');
    expect(errorEl.textContent).toContain('timed out');
  });
});

// ---------------------------------------------------------------------------
// M7-3: Confirm checkbox gate — wiring tests (spec §5.4)
// ---------------------------------------------------------------------------

describe('M7-3: Confirm checkbox gate wiring', () => {
  beforeEach(() => {
    flags.llmFeatureEnabled = true;
    vi.clearAllMocks();
  });

  afterEach(() => {
    flags.llmFeatureEnabled = false;
    vi.restoreAllMocks();
  });

  it('btn-validate is DISABLED (attribute) after draft loads and checkbox unchecked', async () => {
    mockApiFetch.mockResolvedValueOnce({
      yaml_draft: 'id: lg-bug-draft\ntitle: Draft\ncategory: bug_regression\n',
      attempts: 1,
      validation_errors_during_retry: [],
    });

    renderPage();
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'bug description' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate-real'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-loaded')).toBeInTheDocument();
    });

    // Checkbox must be visible and unchecked
    const checkbox = screen.getByTestId('confirm-draft-checkbox') as HTMLInputElement;
    expect(checkbox).toBeInTheDocument();
    expect(checkbox.checked).toBe(false);

    // Validate button MUST have disabled attribute (wiring, not just visual)
    const validateBtn = screen.getByTestId('btn-validate') as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(true);
  });

  it('btn-validate becomes ENABLED after checkbox is checked (wiring)', async () => {
    mockApiFetch.mockResolvedValueOnce({
      yaml_draft: 'id: lg-bug-draft\ntitle: Draft\ncategory: bug_regression\n',
      attempts: 1,
      validation_errors_during_retry: [],
    });

    renderPage();
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'bug description' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate-real'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-loaded')).toBeInTheDocument();
    });

    // Check the checkbox
    const checkbox = screen.getByTestId('confirm-draft-checkbox') as HTMLInputElement;
    fireEvent.click(checkbox);

    // Validate button must now be enabled
    const validateBtn = screen.getByTestId('btn-validate') as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(false);
  });

  it('clicking Validate when checkbox unchecked does NOT trigger validate network call', async () => {
    mockApiFetch.mockResolvedValueOnce({
      yaml_draft: 'id: lg-bug-draft\ntitle: Draft\ncategory: bug_regression\n',
      attempts: 1,
      validation_errors_during_retry: [],
    });

    // Spy on fetch to detect any validate call
    vi.spyOn(global, 'fetch');

    renderPage();
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'bug description' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate-real'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-loaded')).toBeInTheDocument();
    });

    // Checkbox is unchecked — btn-validate is disabled
    const validateBtn = screen.getByTestId('btn-validate') as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(true);

    // Attempt to click validate (should be blocked by disabled attribute)
    fireEvent.click(validateBtn);

    // fetch must NOT have been called (validate flow did not fire)
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('checkbox not shown in idle or error states', async () => {
    // Idle state
    renderPage();
    expect(screen.queryByTestId('confirm-draft-checkbox')).not.toBeInTheDocument();

    // Error state
    mockApiFetch.mockRejectedValueOnce(new Error('generate 失败：HTTP 503 · key missing'));
    const textarea = screen.getByTestId('textarea-entry-a') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'bug description' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-generate-real'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('llm-status-error')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('confirm-draft-checkbox')).not.toBeInTheDocument();
  });

  it('btn-validate is enabled (no draft pending) when YAML typed directly without LLM', () => {
    renderPage();
    // No LLM call — just type YAML directly
    fireEvent.change(screen.getByTestId('textarea-yaml-editor'), {
      target: { value: 'id: manual\n' },
    });
    const validateBtn = screen.getByTestId('btn-validate') as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(false);
  });
});
