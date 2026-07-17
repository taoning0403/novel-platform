import type { ThemeConfig } from "antd";

import { uiPalette, uiTokens } from "./tokens";

export const appTheme: ThemeConfig = {
  cssVar: {
    prefix: "novel",
  },
  hashed: true,
  token: {
    ...uiTokens,
    boxShadow: "0 12px 32px rgb(31 42 68 / 10%)",
    boxShadowSecondary: "0 18px 50px rgb(31 42 68 / 16%)",
    lineWidth: 1,
    motionDurationFast: "0.12s",
    motionDurationMid: "0.18s",
    motionDurationSlow: "0.24s",
  },
  components: {
    Alert: {
      borderRadiusLG: 12,
      withDescriptionIconSize: 18,
    },
    Button: {
      borderRadius: 10,
      controlHeight: 44,
      controlHeightLG: 48,
      fontWeight: 650,
      primaryShadow: "none",
    },
    Card: {
      bodyPadding: 24,
      headerBg: "transparent",
    },
    Drawer: {
      colorBgElevated: uiTokens.colorBgContainer,
      paddingLG: 24,
    },
    Input: {
      activeShadow: "0 0 0 3px rgb(49 94 244 / 12%)",
      hoverBorderColor: uiPalette.indexBlue,
      paddingBlock: 10,
    },
    InputNumber: {
      activeShadow: "0 0 0 3px rgb(49 94 244 / 12%)",
    },
    Menu: {
      itemBg: "transparent",
      itemBorderRadius: 10,
      itemSelectedBg: uiPalette.indexBlueSoft,
      itemSelectedColor: uiPalette.indexBlue,
    },
    Modal: {
      borderRadiusLG: 16,
      contentBg: uiPalette.paper,
      headerBg: uiPalette.paper,
    },
    Select: {
      activeBorderColor: uiPalette.indexBlue,
      activeOutlineColor: "rgb(49 94 244 / 12%)",
      optionSelectedBg: uiPalette.indexBlueSoft,
    },
    Table: {
      headerBg: uiPalette.surfaceMuted,
      headerColor: uiPalette.graphiteSoft,
      rowHoverBg: uiPalette.surfaceSubtle,
    },
    Tabs: {
      inkBarColor: uiPalette.indexBlue,
      itemActiveColor: uiPalette.indexBlue,
      itemSelectedColor: uiPalette.graphite,
    },
    Tag: {
      defaultBg: uiPalette.surfaceMuted,
      defaultColor: uiPalette.graphiteSoft,
    },
  },
};
