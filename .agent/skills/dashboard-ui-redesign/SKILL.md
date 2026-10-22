---
name: dashboard-ui-redesign
description: Upgrade dashboard visual quality while keeping data meaning, API integration, and responsive behavior correct.
---

# Dashboard UI Redesign Skill

## Goals
Improve visual hierarchy and usability without introducing fake data or a design-only demo.

## Procedure
1. Inspect the existing entry point, navigation, all main view components, styles, API client, and TypeScript types.
2. Use the user-provided screenshot as a design reference: dark financial analytics, compact top navigation, cyan active state, restrained cards, candle chart, indicators, and clear Binance connection status.
3. Fix semantic data correctness first: no-data cards must show `—`/`Unavailable` with explanation rather than a price of zero.
4. Define shared design tokens and a consistent layout grid. Establish responsive behavior at desktop/tablet/mobile breakpoints.
5. Standardize money, percentage, volume, and date formatting in one utility layer.
6. Create reusable market-stat cards, chart panel/toolbar, badge/status components, data table, loading skeleton, empty state, stale banner, and error/retry component as needed.
7. Make chart dimensions responsive and redraw on container resize. Keep legend visibility in sync with rendered indicator series.
8. Ensure tab navigation, symbol selection, timeframe selection, indicator toggles, sync controls, filters, and forecast actions actually work.
9. Check keyboard navigation, accessible labels, focus states, color contrast, reduced motion, and long labels.
10. Verify pages at typical 1440px and 1280px desktop widths, tablet width, and 375–430px mobile width where tooling permits.

## Do not
- Do not replace live API calls with hard-coded values.
- Do not use `$0.00` as a fallback for missing market data.
- Do not claim `BINANCE LIVE` unless the backend indicates fresh successful data.
- Do not add charts/metrics merely to fill whitespace if they do not convey meaningful information.
- Do not introduce a large component library without need.

## Deliverables
Working UI, typed API integration, responsive styles, meaningful empty/error states, and evidence of build/test verification.
