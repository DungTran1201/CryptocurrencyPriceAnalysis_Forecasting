# Design Research & Synthesis

**Document Version**: 2.0.0  
**Date**: October 2026  
**Project**: Binance Predict Value & Trend — Data Engineering, Analytics & Forecasting Platform  
**Authors**: Senior Product Designer & Design Systems Engineer  

---

## 1. Executive Summary

This document synthesizes empirical design research from five authoritative sources:
1. **DungTran1201/AgentHarnessBuilderTools** (Workspace & UX Architecture Reference)
2. **Binance Production Web Application** (`https://www.binance.com/en`)
3. **shadcn/ui Dashboard Blocks** (`https://ui.shadcn.com/blocks?category=dashboard`)
4. **Carbon Design System & Data Visualization** (`https://www.carbondesignsystem.com`)
5. **dashboardcn Analytics Registry** (`https://dashboardcn.com/docs`)
6. **Ant Design Dark Mode & Enterprise Principles** (`https://ant.design/docs/spec/dark/`)

All inspections were performed directly against live endpoints, repository trees, and raw stylesheets. No patterns were assumed or invented.

---

## 2. Research Evidence Matrix

| Source & URL | Artifacts & Pages Actually Inspected | Design Patterns Observed | What is Adopted & Why | What is Deliberately Excluded | Limitations / Accessibility Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AgentHarnessBuilderTools**<br>`github.com/DungTran1201/AgentHarnessBuilderTools` | `models/ux/ux.yaml`, `work-items/FEAT-004...`, `README.md`, Git tree via GitHub API | Structured workspace layout; persistent sidebar navigation; telemetry KPI cards; live stream tables; debounced multi-filters; explicit confirmation modals; responsive 360px–1920px bounds | First-class sidebar navigation with badge counts; dedicated Telemetry KPI row; real-time operational status pills; structured data tables with drill-down | Did not copy chat prompt composer or Discord bot integrations since this application is a quantitative market and data platform | GitHub web HTML is heavily bundled; verified source directly via raw files and GitHub REST API tree |
| **Binance Web Application**<br>`https://www.binance.com/en` | Production DOM, `<style id="webstudio-universal-uikit-colors">`, CSS tokens | Backgrounds: `#0B0E11` (darkest/trade), `#181A20` (basic app bg), `#202630` (cards), `#252C37` (surfaces); Yellow: `#FCD535` (primary buttons), `#F0B90B` (links/active text); Text: `#EAECEF` (primary), `#929AA5` (secondary), `#707A8A` (tertiary); Semantic moves: `#2EBD85` (green buy), `#F6465D` (red sell); Borders: `#333B47` | Exact Binance dark surface hierarchy; restrained yellow accent for active states/primary buttons; high contrast typography; semantic green/red for market returns; soft alpha pill backgrounds (`rgba(252,213,53,0.1)`) | Excluded proprietary brand logos, proprietary fonts (`BinanceNova`), promotional exchange banners, and complex spot orderbook panels | Inspected production CSS tokens directly embedded in the HTML head |
| **shadcn/ui Dashboard Blocks**<br>`https://ui.shadcn.com/blocks?category=dashboard` | `Dashboard-01` to `Dashboard-04`, Sidebar layout, Metric Cards, Data Table | 240px persistent collapsible sidebar with icon + label hierarchy; top bar with breadcrumbs and user/system status; KPI card with title, muted icon, large metric value, and delta badge below; tabular data with sticky header | Component anatomy for AppShell, Sidebar, TopBar, MetricCard, and DataTable. Strict padding scale (`0.75rem`, `1.5rem`), subtle `1px` borders (`border-border`) | Did not import heavy Tailwind runtime or npm packages to preserve zero-dependency lightweight architecture | Full React SSR tree inspected via Next.js rendered blocks |
| **Carbon Design System**<br>`carbondesignsystem.com/data-visualization` | Data visualization overview, Chart types, Status indicators, 2x Grid | Explicit chart typologies: line/area for continuous trends, bars for discrete counts/volumes, histograms for return distributions, heatmaps for correlation matrices; status pairing with text labels (never color alone); empty states with clear recovery actions | Applied matching chart forms to each analytical metric (Candles for OHLC, bars for pipeline records, heatmap for cross-asset correlations); clear units and timestamps on all charts; structured empty/loading states | Did not adopt IBM-specific Carbon carbon-charts SVG bundle; retained high-performance HTML5 Canvas renderer | High contrast dark tokens verified against WCAG AA 4.5:1 |
| **dashboardcn**<br>`https://dashboardcn.com/docs` | KPI Cards, Delta Badges, Status Badges, Distribution Bar | Compact delta badges with directional arrows; high information density without visual noise; muted secondary typography | Micro-typography styling for percentage changes (`+2.45%` in green badge, `-1.20%` in red badge); monospace numbers for tabular alignment (`tabular-nums`) | Did not install Radix/Shadcn CLI registry packages | Live site documentation inspected via HTTP fetch |
| **Ant Design Dark Mode**<br>`https://ant.design/docs/spec/dark/` | Dark theme principles, surface elevation, contrast rules | Layered brightness (darker base, incrementally lighter cards and popovers); restrained borders; accessible text opacity levels (85% primary, 45% secondary, 25% disabled) | Multi-tier elevation system: `--bg-app: #0B0E11`, `--bg-sidebar: #12161C`, `--bg-card: #181E26`, `--bg-card-hover: #1F2630`, `--bg-elevated: #262E3B` | Excluded Ant Design's blue-centric defaults in favor of Binance yellow/charcoal palette | CSS and token specs verified |

---

## 3. Design Decision Record (DDR)

### Decision 1: Yellow Usage Discipline
- **Decision**: Yellow (`#FCD535` / `#F0B90B`) is strictly reserved for **primary actions, active navigation items, and focus rings**. It is **never** used for generic card borders, standard chart gridlines, or informational table text.
- **Rationale**: In financial analytics, yellow can easily be misinterpreted as a "warning" or "caution" state. Overusing yellow on borders produces extreme visual fatigue and destroys visual hierarchy. Binance itself restricts yellow to the primary CTA buttons and active tab indicators.

### Decision 2: Surface Elevation & Contrast
- **Decision**: Define a 5-tier dark surface system:
  1. Base Application Background: `#0B0E11` (Binance Trade/Graphite dark)
  2. Sidebar & Header Surface: `#12161C` (Subtle separation)
  3. Primary Card Background: `#181E26`
  4. Card Hover / Active Container: `#1F2630`
  5. Elevated Dropdown / Modal Surface: `#262E3B`
- **Rationale**: Pure black (`#000000`) creates harsh contrast and glare on OLED/LCD screens. Charcoal and dark graphite surfaces with subtle 1px borders (`#29313D` / `#333B47`) provide crisp, eye-friendly depth.

### Decision 3: Navigation Architecture — Persistent Sidebar + Top Bar
- **Decision**: Evolve the existing top-tab bar into a **responsive persistent sidebar navigation** (matching `AgentHarnessBuilderTools` and `shadcn/ui Dashboard-01`), supplemented by a **compact TopBar** displaying active view breadcrumbs, real-time platform engine status, and global actions.
- **Rationale**: The platform now has 9 comprehensive data engineering, quality, analytics, and ML observability modules. Horizontal top tabs become crowded and unreadable on laptop screens (1280px–1440px). A vertical sidebar supports scalable categorization, badge counts, and collapsible responsive behavior.

### Decision 4: Chart Library Retention
- **Decision**: Retain and enhance the project's native HTML5 Canvas chart (`CandlestickChart.tsx`) rather than adding heavy third-party chart dependencies.
- **Rationale**: The canvas implementation delivers instant 60 FPS rendering, native high-DPI scaling, zero bundle overhead, and complete customization for candlesticks, volume bars, Bollinger Bands, SMA, EMA, and RSI. Re-styling its canvas colors to match the Binance palette ensures seamless visual cohesion.

### Decision 5: Honest Data States
- **Decision**: Missing, partial, stale, and failed data must have distinctive visual states. No metric may render as `$0.00` or `0.0%` if data is missing or uncomputed.
- **Rationale**: Data engineers and quantitative analysts rely on exact truth. Showing `$0.00` falsifies market reality. Missing data renders as `—` with an informative tooltip or status badge.
