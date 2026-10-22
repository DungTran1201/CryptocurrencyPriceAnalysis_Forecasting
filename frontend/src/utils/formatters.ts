/**
 * Centralized formatting utilities using explicit en-US locale.
 * Guarantees consistent decimal/grouping conventions and distinguishes unavailable data from zero.
 */

const CURRENCY_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

const PRECISE_CURRENCY_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 4,
  maximumFractionDigits: 4
});

const NUMBER_FORMATTER = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

/**
 * Format numeric value as USD currency string in en-US.
 * Returns fallback (default "—") when val is null, undefined, or NaN.
 * Never formats unavailable data as "$0.00".
 */
export function formatCurrency(val?: number | null, fallback = '—'): string {
  if (val === null || val === undefined || Number.isNaN(val)) {
    return fallback;
  }
  if (val > 0 && val < 0.1) {
    return PRECISE_CURRENCY_FORMATTER.format(val);
  }
  return CURRENCY_FORMATTER.format(val);
}

/**
 * Format standard number with commas and specified decimals.
 */
export function formatNumber(val?: number | null, decimals = 2, fallback = '—'): string {
  if (val === null || val === undefined || Number.isNaN(val)) {
    return fallback;
  }
  if (decimals === 2) {
    return NUMBER_FORMATTER.format(val);
  }
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  }).format(val);
}


/**
 * Format percentage change with explicit + or - sign.
 */
export function formatPercent(val?: number | null, fallback = '—'): string {
  if (val === null || val === undefined || Number.isNaN(val)) {
    return fallback;
  }
  const prefix = val > 0 ? '+' : '';
  return `${prefix}${val.toFixed(2)}%`;
}

/**
 * Format market volume into readable compact notation (e.g. 1.2M, 450.5K).
 */
export function formatVolume(val?: number | null, fallback = '—'): string {
  if (val === null || val === undefined || Number.isNaN(val)) {
    return fallback;
  }
  if (val >= 1_000_000_000) {
    return `${(val / 1_000_000_000).toFixed(2)}B`;
  }
  if (val >= 1_000_000) {
    return `${(val / 1_000_000).toFixed(2)}M`;
  }
  if (val >= 1_000) {
    return `${(val / 1_000).toFixed(1)}K`;
  }
  return val.toFixed(1);
}

/**
 * Format ISO datetime string to readable UTC string.
 */
export function formatDateTime(dateStr?: string | null, fallback = '—'): string {
  if (!dateStr) return fallback;
  try {
    const d = new Date(dateStr.endsWith('Z') || dateStr.includes('+') ? dateStr : `${dateStr}Z`);
    if (Number.isNaN(d.getTime())) {
      return dateStr.replace('T', ' ').slice(0, 19);
    }
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  } catch {
    return dateStr.replace('T', ' ').slice(0, 19);
  }
}

/**
 * Format relative time (e.g. "2m ago", "1h ago", "Never synced").
 */
export function formatRelativeTime(dateStr?: string | null, fallback = 'Never synced'): string {
  if (!dateStr) return fallback;
  try {
    const d = new Date(dateStr.endsWith('Z') || dateStr.includes('+') ? dateStr : `${dateStr}Z`);
    if (Number.isNaN(d.getTime())) return fallback;
    const now = Date.now();
    const diffSec = Math.floor((now - d.getTime()) / 1000);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return `${Math.floor(diffSec / 86400)}d ago`;
  } catch {
    return fallback;
  }
}
