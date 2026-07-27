import type { ThemeConfig } from 'antd'
import { theme } from 'antd'

/** Linear-inspired dark tokens merged with ui-ux-pro-max Data-Dense Dashboard density. */
export const linearColors = {
  canvas: '#010102',
  surface1: '#0f1011',
  surface2: '#141516',
  surface3: '#18191a',
  hairline: '#23252a',
  hairlineStrong: '#34343a',
  primary: '#5e6ad2',
  primaryHover: '#828fff',
  primaryFocus: '#5e69d1',
  ink: '#f7f8f8',
  inkMuted: '#d0d6e0',
  inkSubtle: '#8a8f98',
  inkTertiary: '#62666d',
  success: '#27a644',
  warning: '#d97706',
  error: '#ef4444',
  accentStat: '#faff69',
} as const

export const linearTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: linearColors.primary,
    colorInfo: linearColors.primary,
    colorSuccess: linearColors.success,
    colorWarning: linearColors.warning,
    colorError: linearColors.error,
    colorBgBase: linearColors.canvas,
    colorBgLayout: linearColors.canvas,
    colorBgContainer: linearColors.surface1,
    colorBgElevated: linearColors.surface2,
    colorBorder: linearColors.hairline,
    colorBorderSecondary: linearColors.hairlineStrong,
    colorText: linearColors.ink,
    colorTextSecondary: linearColors.inkMuted,
    colorTextTertiary: linearColors.inkSubtle,
    colorTextQuaternary: linearColors.inkTertiary,
    borderRadius: 8,
    borderRadiusSM: 6,
    borderRadiusLG: 12,
    fontFamily:
      "'Fira Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    fontFamilyCode: "'Fira Code', ui-monospace, Menlo, Monaco, Consolas, monospace",
    fontSize: 14,
    controlHeight: 36,
    motionDurationMid: '0.2s',
    motionDurationSlow: '0.3s',
  },
  components: {
    Layout: {
      siderBg: linearColors.canvas,
      headerBg: linearColors.canvas,
      bodyBg: linearColors.canvas,
      triggerBg: linearColors.surface1,
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
      darkItemSelectedBg: linearColors.surface2,
      darkItemHoverBg: linearColors.surface1,
      itemHeight: 40,
      iconSize: 16,
    },
    Card: {
      colorBgContainer: linearColors.surface1,
      colorBorderSecondary: linearColors.hairline,
      paddingLG: 16,
    },
    Table: {
      headerBg: linearColors.surface2,
      rowHoverBg: linearColors.surface2,
      borderColor: linearColors.hairline,
      cellPaddingBlock: 10,
      cellPaddingInline: 12,
    },
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
    },
    Input: {
      colorBgContainer: linearColors.surface2,
      activeBorderColor: linearColors.primary,
      hoverBorderColor: linearColors.hairlineStrong,
    },
    Tabs: {
      inkBarColor: linearColors.primary,
      itemSelectedColor: linearColors.ink,
      itemHoverColor: linearColors.inkMuted,
    },
  },
}
