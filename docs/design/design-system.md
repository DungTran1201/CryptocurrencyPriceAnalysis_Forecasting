# Design System Specifications & Tokens

**Document Version**: 2.0.0  
**Design Theme**: Institutional Binance Dark & Yellow (Charcoal Graphite Palette)  
**Applicability**: Frontend Core (`frontend/src/index.css`, `frontend/src/components/*`)  

---

## 1. Color Tokens & Semantic Roles

All colors are exposed as native CSS custom properties in `:root`.

```css
:root {
  /* Surfaces & Backgrounds */
  --bg-app: #0B0E11;            /* Deep dark graphite base application background */
  --bg-sidebar: #12161C;        /* Persistent sidebar & persistent chrome */
  --bg-topbar: rgba(18, 22, 28, 0.95); /* Header with subtle backdrop blur */
  --bg-card: #181E26;           /* Standard panel and card background */
  --bg-card-hover: #1F2630;     /* Interactive card hover state */
  --bg-surface-elevated: #262E3B; /* Modal dialogs, dropdown menus, drawers */
  --bg-input: #1F2630;          /* Form input controls */
  --bg-input-focus: #262E3B;    /* Focused inputs */

  /* Primary Brand Accent (Binance Gold / Yellow) */
  --accent-yellow: #FCD535;      /* Primary CTA buttons, key highlights */
  --accent-yellow-hover: #F0B90B;/* Hover state for primary yellow */
  --accent-yellow-subtle: rgba(252, 213, 53, 0.12); /* Active badge background */
  --accent-yellow-border: rgba(252, 213, 53, 0.35); /* Focus rings and active borders */
  --text-on-yellow: #12161C;    /* Maximum contrast on yellow buttons */

  /* Semantic Market & Operational Colors */
  --color-success: #2EBD85;     /* Bullish candles, upward returns, healthy status */
  --color-success-bg: rgba(46, 189, 133, 0.12);
  --color-danger: #F6465D;      /* Bearish candles, negative returns, critical failures */
  --color-danger-bg: rgba(246, 70, 93, 0.12);
  --color-warning: #F59E0B;     /* Stale data, anomalies, warnings */
  --color-warning-bg: rgba(245, 158, 11, 0.12);
  --color-info: #3B82F6;        /* Informational indicators, model versions */
  --color-info-bg: rgba(59, 130, 246, 0.12);
  --color-neutral: #707A8A;     /* Muted/offline/unavailable */
  --color-neutral-bg: rgba(112, 122, 138, 0.12);

  /* Borders & Dividers */
  --border-subtle: #202630;     /* Card dividers, inner table borders */
  --border-default: #2A3340;    /* Standard card perimeter borders */
  --border-strong: #3B4759;     /* Interactive hover borders, input outlines */

  /* Text & Typography */
  --text-primary: #EAECEF;      /* High emphasis headers, primary figures */
  --text-secondary: #929AA5;    /* Subheadings, table headers, labels */
  --text-muted: #707A8A;        /* Timestamps, footnotes, tooltips */
  --text-disabled: #4F5867;     /* Inactive elements */

  /* Typography Scales */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', 'Roboto Mono', 'SF Mono', Consolas, monospace;

  /* Spacing Scale (8pt grid convention) */
  --space-2xs: 2px;
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;
  --space-2xl: 32px;

  /* Border Radii */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 9999px;

  /* Elevation Shadows */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 12px 32px rgba(0, 0, 0, 0.6);
}
```

---

## 2. Component Design Tokens & Standards

### AppShell & Layout Grid
- **Sidebar Width**: `240px` (desktop expanded), `64px` (collapsed icon-only mode), overlay drawer on mobile `< 768px`.
- **TopBar Height**: `56px`, fixed top with `backdrop-filter: blur(8px)`.
- **Main Viewport**: Fluid container with max-width `1680px`, horizontal padding `24px` on desktop, `16px` on tablet, `12px` on mobile.
- **Card Padding**: Standard `20px`, compact `12px` for table cells and sub-metric panels.

### MetricCard (KPI)
- **Top Row**: Metric label (`--text-secondary`, font-size `0.75rem`, uppercase, letter-spacing `0.05em`) paired with a muted icon (`size={16}`).
- **Center**: Prominent numerical value (`--text-primary`, font-size `1.5rem` to `1.75rem`, font-weight `700`, monospace `tabular-nums`).
- **Bottom Row**: Micro-badge showing trend or operational context (`+2.45% 24h` or `100% SLA PASS`).

### StatusBadge
- **Variants**:
  - `SUCCESS` / `ONLINE` / `PASS`: Green text with 12% alpha green background.
  - `WARNING` / `AWAITING_DATA` / `STALE`: Amber text with 12% alpha amber background.
  - `CRITICAL` / `FAILED` / `OFFLINE`: Red text with 12% alpha red background.
  - `INFO` / `RUNNING`: Blue text with 12% alpha blue background.
  - `UNAVAILABLE` / `PENDING`: Gray text with 12% alpha gray background.
- Pulse dot for live engine states.

### Data Table
- **Header**: Sticky `top: 0`, height `36px`, font-size `0.72rem`, uppercase, `--text-muted`, background `--bg-card`.
- **Row**: Height `44px`, hover background `--bg-card-hover`, bottom border `1px solid var(--border-subtle)`.
- **Numeric Alignment**: Right-aligned, monospace font (`var(--font-mono)`), `tabular-nums`.

### Chart Panels & Canvas
- Candlestick bull: `--color-success` (`#2EBD85`), bear: `--color-danger` (`#F6465D`).
- Gridlines: `--border-subtle` (`#202630`) with dashed canvas strokes.
- High-contrast axes: labels in `--text-muted`, price crosshairs in `--accent-yellow`.
- Responsive canvas container with `ResizeObserver` listener.

---

## 3. Responsive Breakpoints

| Breakpoint | Window Width | Layout Treatment |
| :--- | :--- | :--- |
| **Desktop XL** | `≥ 1440px` | Full 240px sidebar, 4-column KPI grid, 2-column analytics split |
| **Desktop Standard** | `1024px – 1439px` | 240px sidebar, 2-column to 4-column adaptive grids |
| **Tablet** | `768px – 1023px` | Collapsed 64px sidebar (icons only with tooltips), stacked KPI rows |
| **Mobile** | `< 768px` | Hidden sidebar with top-header hamburger menu drawer, single-column full-width cards |
