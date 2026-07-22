---
name: novel-platform-design-system
description: Apply the approved 漫读 Quiet Trace design system to novel-platform Web UI work. Use for React page, AppShell, navigation, shared component, CSS Module, Ant Design theme, responsive layout, accessibility, or Reader-chrome changes in this repository.
---

# 漫读 design system

Implement a restrained modern private-reading workspace. Preserve the application contracts while
making reading and curation tasks easier to scan and complete.

## Start safely

1. Use `repo-context` before inspecting or changing the repository.
2. Locate the responsible route, CSS Module, tests, and acceptance path through
   `docs/MODULE_MAP.md`.
3. Preserve authentication, authorization, API, import/file, one-time credential, Reader
   projection, progress synchronization, and accessible-name behavior.
4. Keep Ant Design 6, one app-level provider, CSS Modules, lazy routes, and the Reader's dedicated
   publication layer. Do not add another general-purpose component system.

## Use the Quiet Trace language

- Name the product **漫读** in product-owned fallback copy. Continue to render an explicitly
  configured site name where the public-site contract requires it.
- Use Graphite `#121826`, Cool Canvas `#F5F7FA`, Paper `#FFFFFF`, Index Blue `#315EF4`, border
  `#DDE3EC`, and muted text `#687386` as the dominant palette.
- Reserve Coral `#FF6B57` for irreversible consequences or real progress markers and Reading Teal
  `#0E8F7C` for success/readable state. Do not use either as general decoration.
- Use SF Pro/PingFang/system sans-serif for interface display and body text. Use Songti/Noto Serif
  only for book titles and publication content. Use SF Mono/Menlo only for credentials, identifiers,
  and positions.
- Use 10 px control and 14 px working-surface radii. Build hierarchy with spacing and borders;
  reserve shadows for overlays and the active reading sheet.
- Use the three slim vertical reading-trace marks only for the brand, active navigation, actual
  book progress, and the Reader viewport progress. Do not repeat them as decoration.
- Motion stays minimal and uses the shared tokens in `ui/tokens.ts`: `--ease-out` /
  `--ease-in-out` curves and `--motion-press` (140 ms press/hover), `--motion-fast` (180 ms small
  entrances), `--motion-overlay` (220 ms overlays). Keep UI motion under 300 ms, ease-out for
  entrances, explicit property lists (never `transition: all`), hover motion gated behind
  `@media (hover: hover) and (pointer: fine)`, and respect reduced motion.

## Compose each surface around one job

- **Login:** center one compact login panel; keep privacy, non-commercial status, and real filing
  information as quiet supporting content. Say `进入书库`; hide implementation terminology.
- **Library:** lead with a compact continue-reading surface, keep search visible, move filters into
  a drawer, show active filters as removable chips, and use a cover-led responsive grid.
- **Administration:** prefer master-detail or task-group layouts over stacked cards and permanent
  forms. Keep dangerous operations in consequence-aware menus and confirmations.
- **App shell:** use grouped desktop sidebar navigation; on mobile use a compact top bar, frequent
  bottom destinations, and a full-navigation `更多` drawer.
- **Reader:** keep publication content central and untouched by generic typography components.
  Use a real edge progress trace, quiet auto-hiding chrome, a TOC rail/drawer, a settings drawer,
  and thumb-reachable previous/next controls.

## Write and verify

- Use direct task labels and describe outcomes, not implementation. Empty and error states must
  name the next useful action.
- Keep visible keyboard focus, 44 px desktop controls, at least 46 px touch targets, 320 px minimum
  layout support, and reduced-motion behavior.
- Avoid generated Ant Design selectors, global `!important`, decorative statistics, nested cards,
  ubiquitous pills, and page-sized promotional headings.
- Run focused tests during implementation, then `pnpm lint`, `pnpm test`, and `pnpm build`.
- For a milestone-level UI change, run the current browser acceptance gate and compare the v0.7
  visual baselines at desktop and mobile widths.
