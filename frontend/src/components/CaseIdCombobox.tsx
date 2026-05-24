/**
 * CaseIdCombobox — pick a case_id from /cases (fuzzy search id + title).
 *
 * Why a combobox vs plain `<input>`: case_ids like
 * `lg-bug-0009-union-all-const-distributed-row-order` are long and
 * easy to typo. Admin UI flows that take a case_id (skip-list etc.)
 * should let the user search by either id segment or title keyword.
 *
 * Behavior:
 *  - Trigger is a button (shadcn pattern) showing current selection.
 *  - Click → popover opens with searchable Command list.
 *  - Filter matches id OR title (via cmdk default substring match on
 *    `value={id + ' ' + title}`).
 *  - Each row: mono `case_id` + title (truncated) + status badge.
 *  - **Restricted to existing cases** — no free-text entry. If user needs
 *    to add a skip for a not-yet-created case, do it via SQL or extend
 *    this component with a "Use as new" CommandItem at top (followup).
 *
 * Data source: GET /cases (all categories). Loaded once on mount;
 * 15-100 cases comfortably fit client-side.
 */
import { useEffect, useState } from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import { apiFetch } from '@/api/client';
import type { components } from '@/api/types';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';

type CaseSummary = components['schemas']['CaseSummary'];

interface CaseIdComboboxProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** testid root; sub-elements derive from this. */
  testid?: string;
}

function statusBadgeVariant(
  status: string,
): 'default' | 'secondary' | 'destructive' | 'outline' {
  // Reuse common semantic mapping; not category-aware (combobox doesn't
  // have category context). pass / stable / fixed → green-ish (default);
  // open / fail → red (destructive); rest → outline.
  const s = status.toLowerCase();
  if (s === 'fixed' || s === 'stable' || s === 'pass') return 'default';
  if (s === 'open' || s === 'fail') return 'destructive';
  return 'outline';
}

export function CaseIdCombobox({
  value,
  onChange,
  placeholder = 'Pick a case_id…',
  testid = 'case-id-combobox',
}: CaseIdComboboxProps) {
  const [open, setOpen] = useState(false);
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/cases', 'get')
      .then((data) => {
        if (cancelled) return;
        setCases(data as CaseSummary[]);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          data-testid={`${testid}-trigger`}
          className="w-full justify-between font-mono"
        >
          {value ? (
            <span className="truncate">{value}</span>
          ) : (
            <span className="text-muted-foreground font-sans">{placeholder}</span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[640px] p-0"
        data-testid={`${testid}-popover`}
      >
        <Command>
          <CommandInput
            placeholder="搜索 case_id 或 title 关键词…"
            data-testid={`${testid}-search`}
          />
          <CommandList>
            {error !== null && (
              <div
                data-testid={`${testid}-error`}
                className="p-3 text-sm text-destructive"
              >
                Failed to load cases: {error}
              </div>
            )}
            {error === null && cases === null && (
              <div
                data-testid={`${testid}-loading`}
                className="p-3 text-sm text-muted-foreground"
              >
                Loading cases…
              </div>
            )}
            {error === null && cases !== null && cases.length === 0 && (
              <CommandEmpty>No cases.</CommandEmpty>
            )}
            {error === null && cases !== null && cases.length > 0 && (
              <>
                <CommandEmpty>No matches.</CommandEmpty>
                {cases.map((c) => (
                  <CommandItem
                    key={c.id}
                    /* cmdk's default filter matches against `value` substring,
                       so concatenating id + title makes both searchable. */
                    value={`${c.id} ${c.title ?? ''}`}
                    onSelect={() => {
                      onChange(c.id);
                      setOpen(false);
                    }}
                    data-testid={`${testid}-item-${c.id}`}
                  >
                    <Check
                      className={cn(
                        'h-4 w-4',
                        value === c.id ? 'opacity-100' : 'opacity-0',
                      )}
                    />
                    <span className="font-mono text-xs shrink-0">{c.id}</span>
                    <span className="text-xs text-muted-foreground truncate flex-1">
                      {c.title}
                    </span>
                    <Badge
                      variant={statusBadgeVariant(c.status)}
                      className="ml-auto shrink-0"
                    >
                      {c.status}
                    </Badge>
                  </CommandItem>
                ))}
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
