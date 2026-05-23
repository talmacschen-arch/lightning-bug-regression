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
  const inner = afterBegin.slice(0, endInAfter);

  return inner.trim();
}
