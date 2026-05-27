import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/client';
import { Button } from '@/components/ui/button';
import { fetchMe, type MeResponse } from '@/lib/auth';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';

type CategoryOut = components['schemas']['CategoryOut'];
type CaseSummary = components['schemas']['CaseSummary'];

type TargetVersionOption = {
  id: number;
  name: string;
  is_default: boolean;
};

interface ConflictError {
  detail: string;
  active_run_id: number;
}

// Derive checked/indeterminate/unchecked state for a "select all" checkbox
// given a set of selected ids and the full list of ids in that group.
function groupCheckState(
  selectedIds: Set<string>,
  groupIds: string[],
): 'all' | 'none' | 'indeterminate' {
  const count = groupIds.filter((id) => selectedIds.has(id)).length;
  if (count === 0) return 'none';
  if (count === groupIds.length) return 'all';
  return 'indeterminate';
}

export default function RunNewPage() {
  const navigate = useNavigate();
  // M5-5 — Dashboard Quick Actions navigate here with ?category=X&status=Y
  // to pre-select cases matching that filter. The preset is one-shot:
  // applied on first cases-loaded render, then user can edit freely.
  const [searchParams, setSearchParams] = useSearchParams();
  const presetCategory = searchParams.get('category');
  const presetStatus = searchParams.get('status');
  // M6-D1: explicit case_id list from ?case_ids= (comma-separated) and ?from_run= source hint
  const presetCaseIdsRaw = searchParams.get('case_ids');
  const presetFromRun = searchParams.get('from_run');
  const presetTargetVersionParam = searchParams.get('target_version');
  // Split + deduplicate; empty string handled by filtering
  const presetCaseIdList: string[] = presetCaseIdsRaw
    ? presetCaseIdsRaw
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
    : [];

  const [categories, setCategories] = useState<CategoryOut[]>([]);
  const [casesByCategory, setCasesByCategory] = useState<Record<string, CaseSummary[]>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [targetVersion, setTargetVersion] = useState('');
  const [versionOptions, setVersionOptions] = useState<TargetVersionOption[]>([]);
  const [versionLoadError, setVersionLoadError] = useState(false);
  // Tracks the URL preset key string that has been applied, so navigating
  // to a NEW preset (?category=…&status=…) triggers re-apply, but the
  // same URL stays sticky after the user edits selection.
  const [appliedPresetKey, setAppliedPresetKey] = useState<string | null>(null);
  // M6-D1: separate notice state for deleted cases and stale target_version
  const [skippedCount, setSkippedCount] = useState<number>(0);
  const [staleVersionNotice, setStaleVersionNotice] = useState<string | null>(null);
  // Preset key: case_ids list takes priority over category/status
  const presetKey: string | null = (() => {
    if (presetCaseIdList.length > 0) {
      // Use the raw param string as key (stable; changes when user navigates to new rerun URL)
      return `case_ids:${presetCaseIdsRaw ?? ''}|from_run:${presetFromRun ?? ''}`;
    }
    if (presetCategory || presetStatus) {
      return `${presetCategory ?? ''}|${presetStatus ?? ''}`;
    }
    return null;
  })();

  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState<ConflictError | null>(null);
  const [conflictOpen, setConflictOpen] = useState(false);

  // v1.17: show "Triggered by: <username>" as a readonly hint. Backend
  // auto-fills triggered_by from the authenticated user on POST /runs;
  // we don't send it in the body. This is purely informational.
  const [me, setMe] = useState<MeResponse | null>(null);
  useEffect(() => {
    void fetchMe().then(setMe);
  }, []);

  // Fetch available target versions from the registry on mount.
  // Failure is non-fatal: select renders with only "— None —" + a warning.
  //
  // /admin/target-versions is not yet in the generated OpenAPI types
  // (PR-A lands in parallel). We cast through `unknown` to call apiFetch
  // with a string path. Migrate to the fully-typed overload after running
  // `npm run gen:types` post PR-A merge.
  useEffect(() => {
    let cancelled = false;
    const fetchVersions = apiFetch as unknown as (
      p: string,
      m: string,
      i?: { query?: Record<string, string> },
    ) => Promise<unknown>;
    fetchVersions('/admin/target-versions', 'get', { query: { active: 'true' } })
      .then((data) => {
        if (cancelled) return;
        const opts = data as TargetVersionOption[];
        setVersionOptions(opts);
        // Pre-select the default version if one exists
        const defaultOpt = opts.find((v) => v.is_default);
        if (defaultOpt) setTargetVersion(defaultOpt.name);
      })
      .catch(() => {
        if (!cancelled) setVersionLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Refs for per-category indeterminate checkbox DOM nodes
  const categoryCheckboxRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const globalCheckboxRef = useRef<HTMLInputElement | null>(null);

  // Fetch categories and all cases on mount
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const cats = (await apiFetch('/admin/categories', 'get')) as CategoryOut[];
        if (cancelled) return;
        setCategories(cats);

        // Fetch cases for all categories in parallel
        const results = await Promise.all(
          cats.map((cat) =>
            apiFetch('/cases', 'get', { query: { category: cat.name } }).then(
              (r) => r as CaseSummary[],
            ),
          ),
        );
        if (cancelled) return;

        const byCategory: Record<string, CaseSummary[]> = {};
        cats.forEach((cat, i) => {
          byCategory[cat.name] = results[i];
        });
        setCasesByCategory(byCategory);
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // M5-5 / M6-D1 — Apply URL preset after cases load.
  //
  // Priority: case_ids (explicit list) > category/status (filter)
  //
  // case_ids path:
  //   - Intersect with cases that actually exist on disk (allCases).
  //   - Dropped ids are counted in skippedCount for the banner.
  //   - Guard: re-entry prevented via appliedPresetKey.
  //
  // category/status path (M5-5):
  //   - Both params optional: only category → all in category;
  //     only status → all with that status anywhere; both → AND-filter.
  //
  // Re-applies if presetKey changes (e.g., user navigates to a NEW preset
  // via Dashboard Quick Action without page reload).
  useEffect(() => {
    if (loading) return;
    if (presetKey === null) return;
    if (appliedPresetKey === presetKey) return;

    const allCases = categories.flatMap((cat) => casesByCategory[cat.name] ?? []);

    if (presetCaseIdsRaw && presetCaseIdsRaw.length > 0) {
      // M6-D1: explicit case_ids preset — intersect with disk-existing cases
      const parsedIds = presetCaseIdsRaw
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const existingIds = new Set(allCases.map((c) => c.id));
      const surviving = parsedIds.filter((id) => existingIds.has(id));
      const dropped = parsedIds.length - surviving.length;
      setSelected(new Set(surviving));
      setSkippedCount(dropped);
      setAppliedPresetKey(presetKey);
    } else {
      // M5-5: category/status filter preset
      const matched = allCases
        .filter((c) => (presetCategory ? c.category === presetCategory : true))
        .filter((c) => (presetStatus ? c.status === presetStatus : true))
        .map((c) => c.id);
      setSelected(new Set(matched));
      setAppliedPresetKey(presetKey);
    }
  }, [
    loading,
    categories,
    casesByCategory,
    presetCategory,
    presetStatus,
    presetKey,
    appliedPresetKey,
    presetCaseIdsRaw,
  ]);

  // M6-D1 — Apply ?target_version= preselect after version options load.
  // If the passed value exists in the active version dropdown → preselect it.
  // If NOT (stale/renamed/deleted) → fall back to default + show notice.
  useEffect(() => {
    if (presetTargetVersionParam === null) return;
    if (versionOptions.length === 0 && !versionLoadError) return; // still loading
    const exists = versionOptions.some((v) => v.name === presetTargetVersionParam);
    if (exists) {
      setTargetVersion(presetTargetVersionParam);
      setStaleVersionNotice(null);
    } else {
      // Fall back to default (already set in the versions fetch effect)
      setStaleVersionNotice(
        `Version "${presetTargetVersionParam}" is no longer available — using default`,
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionOptions, versionLoadError, presetTargetVersionParam]);

  // M5-5 / M6-D1 — Clear the URL preset (also empties selection).
  function clearPreset() {
    setSearchParams({}, { replace: true });
    setSelected(new Set());
    setAppliedPresetKey(null);
    setSkippedCount(0);
    setStaleVersionNotice(null);
  }

  // Keep indeterminate state on DOM checkboxes (React does not support indeterminate as a prop)
  useEffect(() => {
    categories.forEach((cat) => {
      const el = categoryCheckboxRefs.current[cat.name];
      if (!el) return;
      const ids = (casesByCategory[cat.name] ?? []).map((c) => c.id);
      const state = groupCheckState(selected, ids);
      el.indeterminate = state === 'indeterminate';
      el.checked = state === 'all';
    });

    if (globalCheckboxRef.current) {
      const allIds = categories.flatMap((cat) =>
        (casesByCategory[cat.name] ?? []).map((c) => c.id),
      );
      const state = groupCheckState(selected, allIds);
      globalCheckboxRef.current.indeterminate = state === 'indeterminate';
      globalCheckboxRef.current.checked = state === 'all';
    }
  }, [selected, categories, casesByCategory]);

  function toggleCase(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleCategoryAll(categoryName: string) {
    const ids = (casesByCategory[categoryName] ?? []).map((c) => c.id);
    const state = groupCheckState(selected, ids);
    setSelected((prev) => {
      const next = new Set(prev);
      if (state === 'all') {
        ids.forEach((id) => next.delete(id));
      } else {
        ids.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  function toggleGlobalAll() {
    const allIds = categories.flatMap((cat) =>
      (casesByCategory[cat.name] ?? []).map((c) => c.id),
    );
    const state = groupCheckState(selected, allIds);
    setSelected((prev) => {
      const next = new Set(prev);
      if (state === 'all') {
        allIds.forEach((id) => next.delete(id));
      } else {
        allIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  function invertSelection() {
    const allIds = categories.flatMap((cat) =>
      (casesByCategory[cat.name] ?? []).map((c) => c.id),
    );
    setSelected(() => {
      const next = new Set<string>();
      allIds.forEach((id) => {
        if (!selected.has(id)) next.add(id);
      });
      return next;
    });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (selected.size === 0) return;

    setSubmitting(true);
    try {
      const body = {
        case_ids: Array.from(selected),
        target_version: targetVersion.trim() !== '' ? targetVersion.trim() : null,
      };

      const result = await apiFetch('/runs', 'post', {
        body,
        allowedStatuses: [409],
      });

      const data = result as { run_id?: number; status?: string; active_run_id?: number; detail?: string };

      if (data.active_run_id !== undefined) {
        // 409 conflict
        setConflict({ detail: data.detail ?? 'Active run in progress', active_run_id: data.active_run_id });
        setConflictOpen(true);
      } else if (data.run_id !== undefined) {
        navigate(`/runs/${data.run_id}`);
      }
    } catch (err) {
      // Unexpected error — surface to ErrorBoundary or show inline
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div data-testid="page-run-new">
        <p>Loading cases…</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div data-testid="page-run-new">
        <p data-testid="load-error">Error: {loadError}</p>
      </div>
    );
  }

  const allIds = categories.flatMap((cat) =>
    (casesByCategory[cat.name] ?? []).map((c) => c.id),
  );
  const globalState = groupCheckState(selected, allIds);

  // M5-5 — Find matched cases count for banner display (does not affect
  // selection state; selection is committed via the effect above).
  // Only used when NOT in case_ids preset mode.
  const presetMatchedCount =
    presetKey !== null && presetCaseIdList.length === 0
      ? categories
          .flatMap((cat) => casesByCategory[cat.name] ?? [])
          .filter((c) => (presetCategory ? c.category === presetCategory : true))
          .filter((c) => (presetStatus ? c.status === presetStatus : true)).length
      : 0;

  return (
    <div data-testid="page-run-new" className="p-4 space-y-4">
      <h1 className="text-2xl font-semibold">Trigger New Run</h1>

      {/* M6-D1 — Rerun banner (case_ids present) */}
      {presetKey !== null && presetCaseIdList.length > 0 && (
        <div
          data-testid="preset-banner"
          className="flex flex-col gap-1 px-3 py-2 rounded border border-blue-200 bg-blue-50 text-sm"
        >
          <div className="flex items-center gap-3">
            <span data-testid="preset-banner-label">
              {presetFromRun
                ? (
                  <>
                    <strong>Re-run from Run #{presetFromRun}</strong>:{' '}
                    <span data-testid="preset-banner-count">
                      {selected.size} case{selected.size === 1 ? '' : 's'}
                    </span>
                  </>
                )
                : (
                  <>
                    <strong>Preset</strong>:{' '}
                    <span data-testid="preset-banner-count">
                      {selected.size} case{selected.size === 1 ? '' : 's'}
                    </span>
                  </>
                )
              }
            </span>
            <button
              type="button"
              data-testid="preset-banner-clear"
              className="ml-auto text-xs underline text-blue-700"
              onClick={clearPreset}
            >
              Clear preset
            </button>
          </div>
          {skippedCount > 0 && (
            <span data-testid="preset-banner-skipped" className="text-amber-700 text-xs">
              {skippedCount} case(s) from Run #{presetFromRun ?? '?'} no longer exist — skipped
            </span>
          )}
        </div>
      )}

      {/* M5-5 — Preset banner shown when URL has ?category=…&status=… */}
      {presetKey !== null && presetCaseIdList.length === 0 && (
        <div
          data-testid="preset-banner"
          className="flex items-center gap-3 px-3 py-2 rounded border border-blue-200 bg-blue-50 text-sm"
        >
          <span data-testid="preset-banner-label">
            <strong>Preset from Dashboard</strong>:{' '}
            {presetCategory && (
              <span data-testid="preset-banner-category">
                category={presetCategory}
              </span>
            )}
            {presetCategory && presetStatus && ' · '}
            {presetStatus && (
              <span data-testid="preset-banner-status">
                status={presetStatus}
              </span>
            )}
            {' — '}
            <span data-testid="preset-banner-count">
              {presetMatchedCount} case{presetMatchedCount === 1 ? '' : 's'} matched
            </span>
          </span>
          <button
            type="button"
            data-testid="preset-banner-clear"
            className="ml-auto text-xs underline text-blue-700"
            onClick={clearPreset}
          >
            Clear preset
          </button>
        </div>
      )}

      {/* M6-D1 — Stale target_version notice */}
      {staleVersionNotice !== null && (
        <div
          data-testid="stale-version-notice"
          className="px-3 py-2 rounded border border-amber-200 bg-amber-50 text-sm text-amber-800"
        >
          {staleVersionNotice}
        </div>
      )}

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
        {/* Global controls row */}
        <div className="flex items-center gap-4 border-b pb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              data-testid="select-all-global"
              ref={globalCheckboxRef}
              onChange={toggleGlobalAll}
              aria-label="Select all cases"
            />
            <span className="text-sm font-medium">
              Select all ({selected.size} / {allIds.length})
            </span>
          </label>

          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="invert-selection"
            onClick={invertSelection}
          >
            Invert
          </Button>
        </div>

        {/* Per-category groups */}
        {categories.map((cat) => {
          const cases = casesByCategory[cat.name] ?? [];
          const catIds = cases.map((c) => c.id);

          return (
            <div key={cat.name} className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  data-testid={`select-all-${cat.name}`}
                  ref={(el) => {
                    categoryCheckboxRefs.current[cat.name] = el;
                  }}
                  onChange={() => toggleCategoryAll(cat.name)}
                  aria-label={`Select all ${cat.display_name} cases`}
                />
                <span className="font-medium">{cat.display_name}</span>
                <span className="text-xs text-gray-500">
                  ({catIds.filter((id) => selected.has(id)).length}/{cases.length})
                </span>
              </div>

              {cases.length === 0 ? (
                <p className="ml-6 text-sm text-gray-400">No cases in this category.</p>
              ) : (
                <ul className="ml-6 space-y-1">
                  {cases.map((c) => (
                    <li key={c.id} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id={`case-${c.id}`}
                        data-testid={`case-checkbox-${c.id}`}
                        checked={selected.has(c.id)}
                        onChange={() => toggleCase(c.id)}
                      />
                      <label htmlFor={`case-${c.id}`} className="text-sm cursor-pointer">
                        {c.id}
                        {c.title ? ` — ${c.title}` : ''}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}

        {/* Target version */}
        <div className="flex items-center gap-3 pt-2">
          <label htmlFor="input-target-version" className="text-sm font-medium">
            Target version
          </label>
          <select
            id="input-target-version"
            data-testid="input-target-version"
            value={targetVersion}
            onChange={(e) => setTargetVersion(e.target.value)}
            className="border rounded px-2 py-1 text-sm w-48"
          >
            <option value="">— None —</option>
            {versionOptions.map((v) => (
              <option key={v.id} value={v.name}>{v.name}</option>
            ))}
          </select>
          {versionLoadError && (
            <span
              data-testid="version-load-error"
              className="text-xs text-amber-600"
            >
              Could not load version list
            </span>
          )}
        </div>

        {/* v1.17 triggered_by hint — backend auto-fills from auth user */}
        <div
          data-testid="run-new-triggered-by-hint"
          className="flex items-center gap-2 text-xs text-gray-500"
        >
          <span>👤 Triggered by:</span>
          <span data-testid="run-new-triggered-by-value" className="font-mono">
            {me?.username ?? '…'}
          </span>
          <span className="text-gray-400">(自动填，对应当前登录用户)</span>
        </div>

        {/* Submit */}
        <Button
          type="submit"
          data-testid="btn-submit-run"
          disabled={selected.size === 0 || submitting}
        >
          {submitting ? 'Triggering…' : `Trigger Run (${selected.size} case${selected.size === 1 ? '' : 's'})`}
        </Button>
      </form>

      {/* 409 conflict dialog */}
      <Dialog open={conflictOpen} onOpenChange={setConflictOpen}>
        <DialogContent data-testid="modal-active-run-conflict">
          <DialogHeader>
            <DialogTitle>Active Run In Progress</DialogTitle>
            <DialogDescription>
              {conflict?.detail ?? 'Another run is already active.'}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm">
            Run{' '}
            <Link
              to={`/runs/${conflict?.active_run_id ?? ''}`}
              data-testid="link-existing-run"
              className="underline text-blue-600"
              onClick={() => setConflictOpen(false)}
            >
              #{conflict?.active_run_id}
            </Link>{' '}
            is currently active. Wait for it to finish or view it below.
          </p>
        </DialogContent>
      </Dialog>

      {/* Report global state for tests that inspect checkboxes */}
      {globalState === 'none' && (
        <span data-testid="global-state-none" className="sr-only">none selected</span>
      )}
    </div>
  );
}
