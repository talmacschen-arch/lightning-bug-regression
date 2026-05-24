/**
 * Strips the skill output fence markers that `/add-test-case` wraps YAML in.
 *
 * Format (from skill output):
 *   ... (any preamble) ...
 *   ─── BEGIN YAML ───
 *   <inner YAML>
 *   ─── END YAML ───
 *   ... (any footer) ...
 *
 * Rules:
 * - If both BEGIN and END markers are present, return only the inner content
 *   between them (trimmed).
 * - If only BEGIN (but no END), return the input unchanged — defensive.
 * - If neither marker is present, return the input unchanged.
 * - **NEW (M4a-1 dogfood fix)**: After extracting the inner block, if the
 *   inner content is itself wrapped in a markdown code fence (```yaml ...
 *   ``` or ```yml ... ``` or plain ``` ... ```), strip that nested fence
 *   too. The skill spec §5.5.1 forbids nested fences inside BEGIN/END but
 *   the model has been observed to emit them (M4a-1 case lg-bug-0007 had
 *   a ```yaml fence inside the BEGIN/END block that broke yaml_loader);
 *   this client-side strip is defense-in-depth so users don't have to
 *   manually awk the fence away when pasting.
 */
export function stripSkillFence(input: string): string {
  const BEGIN = '─── BEGIN YAML ───';
  const END = '─── END YAML ───';

  const beginIdx = input.indexOf(BEGIN);
  if (beginIdx === -1) {
    return input;
  }

  const endIdx = input.indexOf(END);
  if (endIdx === -1) {
    // BEGIN present but no END — defensive: return unchanged
    return input;
  }

  // Extract content between the markers (after the BEGIN line, before END line)
  const afterBegin = input.slice(beginIdx + BEGIN.length);
  const endInAfter = afterBegin.indexOf(END);
  const inner = afterBegin.slice(0, endInAfter).trim();

  // Strip nested markdown fence (```yaml / ```yml / ``` plain)
  return stripNestedFence(inner);
}

/**
 * If `content` is wrapped in a markdown code fence (```yaml\n...\n``` or
 * ```yml\n...\n``` or ```\n...\n```), return only the inner body.
 * Otherwise return `content` unchanged.
 *
 * Exported for unit testing.
 */
export function stripNestedFence(content: string): string {
  const trimmed = content.trim();
  // Opening fence on its own line: ``` or ```yaml or ```yml (case-insensitive),
  // closing fence on its own line: ```.
  // Match ENTIRE string from opening fence through closing fence.
  const m = /^```(?:yaml|yml)?\s*\n([\s\S]*?)\n```\s*$/i.exec(trimmed);
  if (m) {
    return m[1].trim();
  }
  return trimmed;
}
