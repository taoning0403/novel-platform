export const uiPalette = {
  graphite: "#121826",
  graphiteSoft: "#354052",
  muted: "#687386",
  canvas: "#F5F7FA",
  paper: "#FFFFFF",
  surfaceMuted: "#F2F4F8",
  surfaceSubtle: "#FAFBFC",
  line: "#DDE3EC",
  lineSoft: "#E9EDF3",
  indexBlue: "#315EF4",
  indexBlueStrong: "#2448C7",
  indexBlueSoft: "#EEF2FF",
  readingTeal: "#0E8F7C",
  warning: "#A86000",
  danger: "#C63F45",
  dangerSoft: "#FFF1F1",
  coralMarker: "#FF6B57",
} as const;

export const uiTypography = {
  interface:
    '"SF Pro Text", "SF Pro Display", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif',
  book:
    '"Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC", Georgia, serif',
  mono: '"SFMono-Regular", "SF Mono", Menlo, Monaco, Consolas, monospace',
} as const;

export const uiTokens = {
  colorPrimary: uiPalette.indexBlue,
  colorInfo: uiPalette.indexBlue,
  colorLink: uiPalette.indexBlue,
  colorSuccess: uiPalette.readingTeal,
  colorWarning: uiPalette.warning,
  colorError: uiPalette.danger,
  colorText: uiPalette.graphite,
  colorTextSecondary: uiPalette.muted,
  colorBgLayout: uiPalette.canvas,
  colorBgContainer: uiPalette.paper,
  colorBgElevated: uiPalette.paper,
  colorFillSecondary: uiPalette.surfaceMuted,
  colorBorder: uiPalette.line,
  colorBorderSecondary: uiPalette.lineSoft,
  borderRadius: 10,
  borderRadiusLG: 14,
  controlHeight: 44,
  fontSize: 14,
  fontFamily: uiTypography.interface,
} as const;

const cssVariables = {
  "--app-bg": uiPalette.canvas,
  "--surface": uiPalette.paper,
  "--surface-muted": uiPalette.surfaceMuted,
  "--surface-subtle": uiPalette.surfaceSubtle,
  "--ink": uiPalette.graphite,
  "--ink-soft": uiPalette.graphiteSoft,
  "--muted": uiPalette.muted,
  "--line": uiPalette.line,
  "--line-soft": uiPalette.lineSoft,
  "--brand": uiPalette.indexBlue,
  "--brand-strong": uiPalette.indexBlueStrong,
  "--brand-soft": uiPalette.indexBlueSoft,
  "--success": uiPalette.readingTeal,
  "--warning": uiPalette.warning,
  "--danger": uiPalette.danger,
  "--danger-soft": uiPalette.dangerSoft,
  "--coral-marker": uiPalette.coralMarker,
  "--shadow-sheet": "0 22px 58px rgb(31 42 68 / 11%)",
  "--shadow-overlay": "0 18px 50px rgb(31 42 68 / 16%)",
  "--font-interface": uiTypography.interface,
  "--font-book": uiTypography.book,
  "--font-mono": uiTypography.mono,
  "--sidebar-width": "248px",
  "--mobile-nav-height": "72px",
} as const;

export function installUiCssVariables(root: HTMLElement = document.documentElement) {
  for (const [name, value] of Object.entries(cssVariables)) {
    root.style.setProperty(name, value);
  }
}
