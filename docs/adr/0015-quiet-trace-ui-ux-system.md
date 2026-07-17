# ADR 0015: Quiet Trace UI/UX system

- Status: accepted
- Date: 2026-07-17

## Context

ADR 0014 established Ant Design 6, project tokens, CSS Modules, shared interaction components,
and lazy page routes without changing the accepted authentication, authorization, API, import,
file, or Reader contracts. Its warm private-library visual language and horizontal navigation
were useful as a component-foundation baseline, but they leave frequent reading and curation
tasks behind large headings, repeated cards, permanent forms, and an undifferentiated navigation
list.

The v0.7.0 design review approved **漫读** and the **Quiet Trace** direction: a restrained,
modern private-reading workspace for one curator and a few invited readers. The redesign may
change color, typography, visual hierarchy, navigation composition, and task flow. It must not
change authentication or recovery behavior, role authorization, the HTTP contract, the Upload
inspect-preview-commit state machine, one-time credential handling, Reader Projection, Edition
identity, progress conflict handling, or viewer-private state.

## Decision

Adopt Quiet Trace as the Web visual and interaction system. This ADR supersedes only ADR 0014's
requirement that project tokens and page styles create a **warm** private-reading-library visual
language. The rest of ADR 0014 remains accepted: Ant Design 6 is the sole general-purpose
interaction foundation; the application retains one Chinese-localized provider and Ant Design
`App` context, named component imports, project tokens, CSS Modules, route-level lazy loading,
the deployment CSP accommodation for runtime styles, and the Reader's dedicated publication
layer.

Quiet Trace uses the following durable rules:

- Product-owned fallback branding uses **漫读**. An explicitly configured public site name,
  purpose, privacy statement, and real ICP record remain visible according to the public-site
  contract; branding does not replace those settings.
- Graphite `#121826`, Cool Canvas `#F5F7FA`, Paper `#FFFFFF`, Index Blue `#315EF4`, border
  `#DDE3EC`, and muted text `#687386` form the primary palette. Coral `#FF6B57` is reserved for
  irreversible consequences or real progress markers, and Reading Teal `#0E8F7C` is reserved for
  success or readable state.
- Interface text uses a modern system sans-serif stack. Serif typography is limited to book
  titles and publication content; monospace is limited to credentials, identifiers, and reading
  positions.
- Three slim vertical reading-trace marks are the sole signature element. They may represent the
  product, active navigation, book progress, or Reader viewport progress, but are not repeated as
  decoration. Spacing and borders create hierarchy; shadows are limited to overlays and the
  active reading sheet.
- Non-Reader routes use a grouped desktop sidebar. Mobile uses a compact top bar, frequent bottom
  destinations, and a full-navigation `更多` Drawer. Role visibility and recovery-Session
  confinement remain presentation of server-enforced authorization, never the authorization
  control itself.
- Login centers one compact credential/Passkey task and moves public purpose, privacy, and real
  filing information into quiet supporting disclosure. Library leads with continue-reading,
  keeps search visible, moves secondary filters into a Drawer, and uses a cover-led responsive
  grid. Reader administration uses master-detail, with consequence-aware overflow actions and
  explicit confirmations.
- Reader remains a separate full-screen shell with server-sanitized publication markup,
  light/dark/sepia settings, Edition switching, and optimistic progress semantics. Quiet Trace
  adds an edge progress trace, TOC rail/Drawer, settings Drawer, thumb-reachable section controls,
  and auto-hiding chrome that remains keyboard-recoverable and respects reduced motion.
- Interactive controls retain visible focus, existing contract-level accessible names or an
  explicit compatible migration, at least 44 px desktop and 46 px touch targets, and support down
  to 320 px. Generated Ant Design selectors, global `!important` overrides, and a second
  general-purpose component system remain prohibited.

The repository-local `.agents/skills/novel-platform-design-system/SKILL.md` is the operational
guide for applying this decision. Milestone acceptance must replay all valid v0.5.0 and v0.6.0
criteria, then add task-completion paths and reviewed desktop/mobile visual-regression baselines;
capturing screenshots without comparing them is not visual regression.

## Consequences

- AppShell, Login, Library, reader administration, shared tokens/components, and Reader chrome
  may be re-composed substantially while their routes and server contracts remain stable.
- The redesign adds no API, database migration, persistent entity, deployment topology, or
  authorization change. Application rollback does not require an Alembic downgrade or data
  restore solely because of this UI milestone.
- Public-site configuration and one-time credential safety remain visible acceptance contracts
  even when their presentation moves into disclosures, Drawers, menus, or master-detail panes.
- Visual baseline changes require explicit review. Task-path acceptance must distinguish layout
  changes from regressions in login, role navigation, Upload ownership, credential handling, and
  Reader synchronization.
- The initial bundle budget and route-level splitting from ADR 0014 remain in force; visual work
  must not move heavy route code into the synchronous entry.
