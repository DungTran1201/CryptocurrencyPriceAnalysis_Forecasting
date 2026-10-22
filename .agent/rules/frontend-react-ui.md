# Frontend / React / TypeScript / UI Rules

## Architecture
- Keep API access in a typed service layer; do not duplicate fetch logic across pages.
- Define TypeScript types that match backend request/response schemas. Do not silently coerce missing values to zero.
- Keep components focused; separate chart logic, data fetching, formatting, and page composition.
- Cancel or ignore stale async requests when symbol/timeframe selection changes; prevent out-of-order results from overwriting newer state.
- Avoid unnecessary global state and new UI libraries unless existing dependencies do not meet requirements.

## Required UI states
Every market-data page must distinguish: loading, populated, empty/not yet synced, stale data, upstream error, and API contract error. Show `last updated`/source information when appropriate. An error should have a retry action when retry can help.

## Visual direction
- Professional financial-terminal look based on the provided screenshot: dark navy/near-black base, restrained cyan/blue focus, green positive and red negative values.
- Use design tokens for colors, spacing, border radius, typography, and shadows.
- Use consistent numeric formatting; default to `en-US` formatting for English UI unless the app has an explicit locale preference. Never mix decimal and grouping conventions.
- Price cards should never display an unknown/unavailable value as `$0.00`.
- Establish hierarchy: page heading/status, key market cards, chart controls, main chart, supporting metrics/history.
- Use available viewport width well while retaining a readable max width; don't leave unexplained large blank regions or compress the chart into a small central area.
- Responsive behavior must be explicit at desktop, tablet, and mobile widths. Avoid horizontal overflow and clipped menus.
- Implement keyboard focus, accessible labels, contrast, semantic buttons, and tooltip text where icons are ambiguous.
- Charts need empty/error states, resize handling, correct timestamps, axes/units, and legend control states.
- All visible controls must have real behavior and a pending/disabled state where requests are in flight.
