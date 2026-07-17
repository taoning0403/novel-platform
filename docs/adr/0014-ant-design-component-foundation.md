# ADR 0014: Ant Design component foundation

- Status: accepted
- Date: 2026-07-16

## Context

The v0.5.0 Web client implements forms, navigation, feedback, confirmations, status labels, and
responsive layouts with page-local native controls and one growing global stylesheet. That keeps
the runtime small, but repeated interaction patterns have diverged and the single stylesheet now
couples unrelated pages. The v0.6.0 visual refresh must improve consistency and responsive
behavior without changing authentication, authorization, API, import, file, or Reader semantics.

## Decision

Use Ant Design 6 as the shared interaction-component foundation for the React Web client. Do not
introduce Ant Design Pro, Umi, Pro Components, MUI, shadcn/ui, or a second general-purpose
component system.

The application root owns one Chinese-localized `ConfigProvider`, project Design Tokens, and the
Ant Design `App` context. Pages use named component imports and theme-managed hooks instead of
static `message`, `notification`, or `Modal` calls. Project tokens, CSS Modules, and dedicated
layout/page styles create a warm, restrained private-reading-library visual language rather than
the default enterprise-admin appearance.

Page routes use `React.lazy` and `Suspense` so Reader, Upload, administration, and other page code
do not remain in one synchronous entry chunk. The Reader keeps its independent typography,
paper-width, and light/dark/sepia theme layer; it may use Ant Design controls selectively without
moving sanitized publication markup into generic Typography components.

## Consequences

- Shared navigation, async state, status, destructive confirmation, forms, drawers, and modals
  gain consistent accessibility, locale, focus, and responsive behavior.
- Component-level style boundaries replace the milestone-sized global stylesheet and make future
  visual changes more local.
- Ant Design adds bundle weight, theme context, CSS-in-JS runtime work, and migration cost. Route
  dynamic imports and named imports are required to keep the initial entry controlled.
- The deployment CSP must allow Ant Design's runtime-injected styles. Inline scripts remain
  prohibited; the exception applies only to `style-src`.
- Existing accessible names and v0.5.0 product/security behavior remain release contracts even
  when the rendered DOM changes.
- Reader-specific controls must be checked against all three themes and portal behavior; global
  `!important` overrides and dependencies on generated Ant Design class names are not accepted.
