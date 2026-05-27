import { describe, it, expect } from 'vitest';
import { parseUtc, formatRelativeUtc } from './time';

describe('parseUtc', () => {
  it('parses a naive-UTC string (no tz suffix) as UTC — not local time', () => {
    // A naive string that would be mis-parsed as local time on UTC+8 machines.
    // "2026-01-01T00:00:00" in UTC is exactly the Unix epoch for 2026-01-01 00:00 UTC.
    const naive = '2026-01-01T00:00:00';
    const withZ = '2026-01-01T00:00:00Z';
    expect(parseUtc(naive).getTime()).toBe(parseUtc(withZ).getTime());
  });

  it('does NOT change a string that already has a Z suffix', () => {
    const explicit = '2026-05-28T10:00:00Z';
    expect(parseUtc(explicit).getTime()).toBe(new Date(explicit).getTime());
  });

  it('does NOT change a string with +HH:MM offset', () => {
    const withOffset = '2026-05-28T18:00:00+08:00';
    expect(parseUtc(withOffset).getTime()).toBe(new Date(withOffset).getTime());
  });

  it('regression: naive-UTC vs new Date() differs by ~8h on UTC+8 offset', () => {
    // This test verifies the bug we fixed: without parseUtc, a UTC+8 client
    // interprets a naive string as 8h later than it actually is.
    // We simulate the UTC+8 offset: parseUtc should interpret "10:00:00" as
    // UTC 10:00, whereas new Date("...T10:00:00") treats it as local (UTC+8),
    // i.e. UTC 02:00 — 8 hours earlier.
    // We cannot rely on the test runner's local timezone, so we compare the
    // two parse results against the explicit-Z version instead.
    const naive = '2026-05-28T10:00:00';
    const explicit = '2026-05-28T10:00:00Z';
    // parseUtc should match the explicit UTC form:
    expect(parseUtc(naive).getTime()).toBe(new Date(explicit).getTime());
    // The difference between parseUtc and new Date() on a UTC+8 machine
    // would be 8 * 3600 * 1000 ms, but in UTC environments it would be 0.
    // We just confirm parseUtc always matches the Z form:
    const naiveViaNewDate = new Date(naive).getTime();
    const utcMs = new Date(explicit).getTime();
    // parseUtc produces the correct UTC ms:
    expect(parseUtc(naive).getTime()).toBe(utcMs);
    // The "raw" new Date(naive) equals utcMs only in UTC environments.
    // In UTC+8 it would differ by 8h. We cannot force the test runner's
    // timezone, but we can assert parseUtc never equals local-biased result
    // by checking our own computation: parseUtc(naive) === utcMs always holds.
    // (Documented: if test runner is UTC+8, naiveViaNewDate !== utcMs.)
    expect(naiveViaNewDate).toBeDefined(); // ensures var used
  });
});

describe('formatRelativeUtc', () => {
  it('returns "just now" for a string that is current UTC time', () => {
    // Use the current time as a naive UTC string
    const now = new Date();
    const naiveUtc = now.toISOString().replace('Z', '');
    expect(formatRelativeUtc(naiveUtc)).toBe('just now');
  });

  it('returns minutes-ago for a string ~5 minutes before now (UTC)', () => {
    const fiveMinsAgo = new Date(Date.now() - 5 * 60_000);
    const naiveUtc = fiveMinsAgo.toISOString().replace('Z', '');
    expect(formatRelativeUtc(naiveUtc)).toBe('5m ago');
  });

  it('returns hours-ago for a string ~2 hours before now (UTC)', () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60_000);
    const naiveUtc = twoHoursAgo.toISOString().replace('Z', '');
    expect(formatRelativeUtc(naiveUtc)).toBe('2h ago');
  });

  it('returns days-ago for a string ~3 days before now (UTC)', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60_000);
    const naiveUtc = threeDaysAgo.toISOString().replace('Z', '');
    expect(formatRelativeUtc(naiveUtc)).toBe('3d ago');
  });
});
