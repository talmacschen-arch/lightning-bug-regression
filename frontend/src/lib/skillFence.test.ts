/**
 * Tests for skillFence helpers.
 *
 * M4a-1 dogfood (case bug-0007-orca-sort-pathkey) exposed a footgun:
 * the skill emitted a markdown code fence (```yaml ... ```) inside the
 * BEGIN/END block, which broke yaml_loader on POST /cases/validate. The
 * skill spec §5.5.1 forbids this but the model drifted. stripSkillFence
 * now defensively strips both layers (outer ─── BEGIN/END markers + inner
 * markdown fence) so users don't have to awk it away manually.
 */

import { describe, it, expect } from 'vitest';
import { stripSkillFence, stripNestedFence } from './skillFence';

describe('stripSkillFence', () => {
  it('returns input unchanged when no BEGIN/END markers', () => {
    expect(stripSkillFence('no markers here')).toBe('no markers here');
    expect(stripSkillFence('id: foo\ntitle: bar')).toBe('id: foo\ntitle: bar');
  });

  it('extracts content between BEGIN/END markers', () => {
    const input = [
      'preamble line',
      '─── BEGIN YAML ───',
      'id: bug-0001',
      'title: demo',
      '─── END YAML ───',
      'footer line',
    ].join('\n');
    expect(stripSkillFence(input)).toBe('id: bug-0001\ntitle: demo');
  });

  it('returns input unchanged when only BEGIN present (defensive)', () => {
    const input = '─── BEGIN YAML ───\nid: foo';
    expect(stripSkillFence(input)).toBe(input);
  });

  it('strips nested ```yaml fence inside BEGIN/END (M4a-1 regression)', () => {
    // This is the EXACT footgun pattern bug-0007 exhibited.
    const input = [
      '─── BEGIN YAML ───',
      '```yaml',
      'id: bug-0007',
      'title: demo',
      '```',
      '─── END YAML ───',
    ].join('\n');
    expect(stripSkillFence(input)).toBe('id: bug-0007\ntitle: demo');
  });

  it('strips nested ```yml fence (lowercase variant)', () => {
    const input = [
      '─── BEGIN YAML ───',
      '```yml',
      'id: bug-0008',
      '```',
      '─── END YAML ───',
    ].join('\n');
    expect(stripSkillFence(input)).toBe('id: bug-0008');
  });

  it('strips nested ``` fence with no language tag', () => {
    const input = [
      '─── BEGIN YAML ───',
      '```',
      'id: bug-0009',
      '```',
      '─── END YAML ───',
    ].join('\n');
    expect(stripSkillFence(input)).toBe('id: bug-0009');
  });

  it('leaves content unchanged when no nested fence present', () => {
    // Real well-formed skill output (the desired pattern per §5.5.1).
    const input = [
      '─── BEGIN YAML ───',
      'id: bug-0010',
      'title: well-formed',
      '─── END YAML ───',
    ].join('\n');
    expect(stripSkillFence(input)).toBe('id: bug-0010\ntitle: well-formed');
  });
});

describe('stripNestedFence', () => {
  it('strips ```yaml fence', () => {
    const input = '```yaml\nid: foo\n```';
    expect(stripNestedFence(input)).toBe('id: foo');
  });

  it('strips ```yml fence (variant)', () => {
    const input = '```yml\nid: bar\n```';
    expect(stripNestedFence(input)).toBe('id: bar');
  });

  it('strips plain ``` fence without language tag', () => {
    const input = '```\nid: baz\n```';
    expect(stripNestedFence(input)).toBe('id: baz');
  });

  it('returns content unchanged when not fenced', () => {
    expect(stripNestedFence('id: foo\ntitle: bar')).toBe('id: foo\ntitle: bar');
  });

  it('returns content unchanged when fence is mid-content (not wrapping)', () => {
    // notes block legitimately contains ```sql in its body — don't strip
    const input = [
      'id: foo',
      'notes: |',
      '  see also:',
      '  ```sql',
      '  SELECT 1',
      '  ```',
    ].join('\n');
    expect(stripNestedFence(input)).toBe(input);
  });

  it('handles multiline yaml content inside fence', () => {
    const input = '```yaml\nid: foo\ntitle: bar\nsteps:\n  - kind: sql\n    sql: SELECT 1\n```';
    expect(stripNestedFence(input)).toBe(
      'id: foo\ntitle: bar\nsteps:\n  - kind: sql\n    sql: SELECT 1',
    );
  });
});
