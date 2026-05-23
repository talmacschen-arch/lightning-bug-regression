import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { toast } from '@/hooks/use-toast';
import { stripSkillFence } from '@/lib/skillFence';

// ---------------------------------------------------------------------------
// API shape types (mirrors backend/app/api/cases.py)
// ---------------------------------------------------------------------------

interface ValidateErrorItem {
  where: string;
  reason: string;
}

interface ValidateResponse {
  ok: boolean;
  errors: ValidateErrorItem[];
}

interface StepResultOut {
  step_id: string;
  kind: string;
  status: string; // "pass" | "fail" | "error" | "skipped"
  duration_ms?: number | null;
  stderr_preview?: string | null;
  error?: string | null;
}

interface TryResponse {
  ok: boolean;
  yaml_sha256: string;
  step_results: StepResultOut[];
  validation_errors: { where: string; reason: string }[];
}

interface SubmitResponse {
  pr_url: string;
  pr_number: number;
  branch: string;
}

// ---------------------------------------------------------------------------
// API helpers (plain fetch — these endpoints are not in the generated types.ts)
// ---------------------------------------------------------------------------

const API_BASE =
  (typeof import.meta !== 'undefined' &&
    (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env
      ?.VITE_API_BASE_URL) ??
  'http://127.0.0.1:8000';

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(API_BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${path} failed: ${res.status} ${res.statusText} — ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Extract case_id from YAML text (regex fallback — no new dep)
// ---------------------------------------------------------------------------

function extractCaseId(yaml: string): string | null {
  const m = /^id:\s*(\S+)/m.exec(yaml);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CaseNewPage() {
  const navigate = useNavigate();

  // Entry tab selection
  const [activeEntry, setActiveEntry] = useState<string>('entry-a');

  // Entry B raw paste value (kept separate from yamlText to preserve raw input)
  const [entryBRaw, setEntryBRaw] = useState('');

  // The canonical YAML being edited
  const [yamlText, setYamlText] = useState('');

  // Three-gate state
  const [validateOk, setValidateOk] = useState(false);
  const [tryOk, setTryOk] = useState(false);
  const [tryStepResults, setTryStepResults] = useState<StepResultOut[]>([]);
  const [validateErrors, setValidateErrors] = useState<ValidateErrorItem[]>([]);
  const [yamlSha256, setYamlSha256] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [trying, setTrying] = useState(false);

  // Panel display: holds generic error or success messages
  const [panelMsg, setPanelMsg] = useState<string | null>(null);
  const [prResult, setPrResult] = useState<SubmitResponse | null>(null);

  // Reset gate state whenever the YAML editor changes
  function handleYamlChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setYamlText(e.target.value);
    setValidateOk(false);
    setTryOk(false);
    setTryStepResults([]);
    setYamlSha256(null);
    setValidateErrors([]);
    setPanelMsg(null);
    setPrResult(null);
  }

  // Entry B: paste handler — strip skill fence if present, mirror to yaml editor
  function handleEntryBChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const raw = e.target.value;
    setEntryBRaw(raw);
    const stripped = stripSkillFence(raw);
    setYamlText(stripped);
    // Reset gate on any entry B change
    setValidateOk(false);
    setTryOk(false);
    setTryStepResults([]);
    setYamlSha256(null);
    setValidateErrors([]);
    setPanelMsg(null);
    setPrResult(null);
  }

  // M3a-5: Entry A generate stub — literal placeholder, no LLM
  function handleGenerateStub() {
    toast({
      title: 'M3a-5 not yet wired — 请用 skill 路径（/add-test-case）或 Tab B 粘贴',
    });
  }

  // M3a-7: Validate handler
  async function handleValidate() {
    setValidating(true);
    setValidateErrors([]);
    setPanelMsg(null);
    setPrResult(null);
    try {
      const resp = await postJson<ValidateResponse>('/api/cases/validate', {
        yaml: yamlText,
      });
      setValidateOk(resp.ok);
      setValidateErrors(resp.errors);
      if (!resp.ok) {
        setPanelMsg(null); // errors shown via validateErrors list
      }
    } catch (err) {
      setPanelMsg(err instanceof Error ? err.message : String(err));
      setValidateOk(false);
    } finally {
      setValidating(false);
    }
  }

  // M3a-7: Try handler
  async function handleTry() {
    setTrying(true);
    setTryStepResults([]);
    setPanelMsg(null);
    setPrResult(null);
    try {
      const resp = await postJson<TryResponse>('/api/cases/try', {
        yaml: yamlText,
      });
      setTryOk(resp.ok);
      setYamlSha256(resp.yaml_sha256);
      setTryStepResults(resp.step_results);
    } catch (err) {
      setPanelMsg(err instanceof Error ? err.message : String(err));
      setTryOk(false);
    } finally {
      setTrying(false);
    }
  }

  // M3a-7: Save handler
  async function handleSave() {
    setSubmitting(true);
    setPanelMsg(null);
    setPrResult(null);
    try {
      const caseId = extractCaseId(yamlText);
      if (!caseId) {
        setPanelMsg('Cannot parse case id from YAML (missing "id:" field)');
        return;
      }
      const branchName = `case/${caseId}`;
      const resp = await postJson<SubmitResponse>('/api/cases/submit', {
        yaml: yamlText,
        case_id: caseId,
        branch_name: branchName,
      });
      setPrResult(resp);
      // Navigate to /cases after 2s (optional polish)
      setTimeout(() => {
        void navigate('/cases');
      }, 2000);
    } catch (err) {
      setPanelMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const isAnyInFlight = validating || trying || submitting;

  return (
    <div data-testid="page-case-new" className="p-4 space-y-4">
      <h1 className="text-2xl font-semibold">New Case</h1>

      {/* ---- Entry tabs (A = LLM stub, B = paste) ---- */}
      <Tabs value={activeEntry} onValueChange={setActiveEntry}>
        <TabsList>
          <TabsTrigger value="entry-a" data-testid="tab-entry-a">
            从描述生成
          </TabsTrigger>
          <TabsTrigger value="entry-b" data-testid="tab-entry-b">
            粘贴 YAML
          </TabsTrigger>
        </TabsList>

        {/* Tab A — LLM stub */}
        <TabsContent value="entry-a">
          <div className="space-y-2 pt-2">
            <label htmlFor="textarea-entry-a" className="text-sm font-medium">
              描述（将来会调 LLM 生成 YAML 草稿）
            </label>
            <textarea
              id="textarea-entry-a"
              data-testid="textarea-entry-a"
              className="w-full h-28 border rounded p-2 text-sm font-mono"
              placeholder="在这里输入 Bug 描述…（v1 stub，暂不调 LLM）"
              rows={5}
            />
            <Button
              type="button"
              data-testid="btn-generate-stub"
              onClick={handleGenerateStub}
              disabled={isAnyInFlight}
            >
              生成 YAML 草稿
            </Button>
          </div>
        </TabsContent>

        {/* Tab B — paste raw YAML (with skill-fence stripping) */}
        <TabsContent value="entry-b">
          <div className="space-y-2 pt-2">
            <label htmlFor="textarea-entry-b" className="text-sm font-medium">
              粘贴 YAML（支持 skill 围栏格式，自动剥离）
            </label>
            <textarea
              id="textarea-entry-b"
              data-testid="textarea-entry-b"
              className="w-full h-28 border rounded p-2 text-sm font-mono"
              placeholder="粘贴 YAML 或 skill 输出（含 ─── BEGIN YAML ─── 围栏）…"
              rows={5}
              value={entryBRaw}
              onChange={handleEntryBChange}
            />
          </div>
        </TabsContent>
      </Tabs>

      {/* ---- YAML editor (main edit surface) ---- */}
      <div className="space-y-1">
        <label htmlFor="textarea-yaml-editor" className="text-sm font-medium">
          YAML 编辑器
        </label>
        <textarea
          id="textarea-yaml-editor"
          data-testid="textarea-yaml-editor"
          className="w-full h-64 border rounded p-2 text-sm font-mono"
          placeholder="YAML 内容将出现在这里…"
          value={yamlText}
          onChange={handleYamlChange}
          rows={16}
        />
      </div>

      {/* ---- Three-gate action buttons ---- */}
      <div className="flex gap-3 flex-wrap">
        <Button
          type="button"
          data-testid="btn-validate"
          disabled={validating}
          onClick={() => void handleValidate()}
        >
          {validating ? 'Validating…' : 'Validate'}
        </Button>

        <Button
          type="button"
          data-testid="btn-try"
          disabled={!validateOk || trying || validating}
          title={!validateOk ? '必须先 Validate 通过' : undefined}
          onClick={() => void handleTry()}
        >
          {trying ? 'Trying…' : 'Try'}
        </Button>

        <Button
          type="button"
          data-testid="btn-save"
          disabled={!tryOk || submitting || trying || validating}
          title={!tryOk ? '必须先 Try 一次并通过' : undefined}
          onClick={() => void handleSave()}
        >
          {submitting ? 'Saving…' : 'Save'}
        </Button>
      </div>

      {/* ---- Step results / status panel ---- */}
      <div data-testid="panel-step-results" className="space-y-2 border rounded p-3 min-h-[80px] bg-muted/30">
        {/* Generic error message */}
        {panelMsg !== null && (
          <p data-testid="error-msg" className="text-sm text-destructive">
            {panelMsg}
          </p>
        )}

        {/* Validate errors list */}
        {validateErrors.length > 0 && (
          <ul data-testid="validate-errors-list" className="space-y-1 text-sm text-destructive list-disc list-inside">
            {validateErrors.map((e, i) => (
              <li key={i}>
                <span className="font-mono">[{e.where}]</span> {e.reason}
              </li>
            ))}
          </ul>
        )}

        {/* Validate OK indicator */}
        {validateOk && validateErrors.length === 0 && !trying && !tryOk && (
          <p className="text-sm text-green-700">Validate passed.</p>
        )}

        {/* Try step results */}
        {tryStepResults.map((sr, idx) => (
          <div
            key={idx}
            data-testid={`try-step-row-${idx}`}
            className="border rounded p-2 text-sm space-y-1"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-xs text-muted-foreground">{sr.step_id}</span>
              <span className="text-xs">[{sr.kind}]</span>
              <span
                className={
                  sr.status === 'pass'
                    ? 'text-green-700 font-semibold'
                    : 'text-destructive font-semibold'
                }
              >
                {sr.status}
              </span>
              {sr.duration_ms !== null && sr.duration_ms !== undefined && (
                <span className="text-xs text-muted-foreground">{sr.duration_ms}ms</span>
              )}
            </div>
            {sr.status !== 'pass' && sr.stderr_preview && (
              <pre
                data-testid={`try-stderr-preview-${idx}`}
                className="text-xs bg-muted p-1 rounded overflow-auto max-h-32 whitespace-pre-wrap"
              >
                {sr.stderr_preview.slice(0, 500)}
              </pre>
            )}
          </div>
        ))}

        {/* Try success indicator (no steps shown with error) */}
        {tryOk && tryStepResults.length === 0 && (
          <p className="text-sm text-green-700">Try passed (no steps).</p>
        )}

        {/* Save success: PR link */}
        {prResult !== null && (
          <div className="text-sm">
            <a
              data-testid="link-pr-url"
              href={prResult.pr_url}
              target="_blank"
              rel="noreferrer"
              className="underline text-blue-600"
            >
              PR #{prResult.pr_number}: {prResult.pr_url}
            </a>
          </div>
        )}
      </div>

      {/* Hidden: expose yamlSha256 for test assertions (aria-hidden) */}
      {yamlSha256 !== null && (
        <span data-testid="yaml-sha256" className="sr-only" aria-hidden="true">
          {yamlSha256}
        </span>
      )}
    </div>
  );
}
