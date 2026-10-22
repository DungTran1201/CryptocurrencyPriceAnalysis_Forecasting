import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  formatVolume,
  formatRelativeTime
} from './formatters.ts';

test('formatCurrency correctly formats in en-US and handles unavailable values', () => {
  // Unavailable cases
  assert.equal(formatCurrency(null), '—');
  assert.equal(formatCurrency(undefined), '—');
  assert.equal(formatCurrency(NaN), '—');
  assert.equal(formatCurrency(null, 'Unavailable'), 'Unavailable');

  // Real numeric zero
  assert.equal(formatCurrency(0), '$0.00');

  // Standard values with comma separation
  assert.equal(formatCurrency(81819.31), '$81,819.31');
  assert.equal(formatCurrency(60000), '$60,000.00');

  // Small sub-dollar values
  assert.equal(formatCurrency(0.0425), '$0.0425');
});

test('formatPercent handles positive, negative, and unavailable values', () => {
  assert.equal(formatPercent(null), '—');
  assert.equal(formatPercent(undefined), '—');
  assert.equal(formatPercent(0), '0.00%');
  assert.equal(formatPercent(5.25), '+5.25%');
  assert.equal(formatPercent(-3.14), '-3.14%');
});

test('formatVolume formats thousands and millions cleanly', () => {
  assert.equal(formatVolume(null), '—');
  assert.equal(formatVolume(120), '120.0');
  assert.equal(formatVolume(45000), '45.0K');
  assert.equal(formatVolume(1250000), '1.25M');
  assert.equal(formatVolume(2500000000), '2.50B');
});

test('formatNumber formats commas and decimals', () => {
  assert.equal(formatNumber(null), '—');
  assert.equal(formatNumber(1234567.89), '1,234,567.89');
  assert.equal(formatNumber(50, 0), '50');
});

test('formatRelativeTime handles null and valid ISO dates', () => {
  assert.equal(formatRelativeTime(null), 'Never synced');
  assert.equal(formatRelativeTime(undefined), 'Never synced');
  const nowIso = new Date().toISOString();
  assert.equal(formatRelativeTime(nowIso), 'Just now');
});
