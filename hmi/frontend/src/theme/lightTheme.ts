import type { ThemeConfig } from 'antd'
import { theme } from 'antd'

/** Light companion to linear dark dashboard. */
export const lightTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: '#5e6ad2',
    colorInfo: '#5e6ad2',
    colorSuccess: '#27a644',
    colorWarning: '#d97706',
    colorError: '#ef4444',
    colorBgBase: '#f4f5f7',
    colorBgLayout: '#eef0f3',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#e2e5eb',
    colorBorderSecondary: '#d8dce3',
    colorText: '#1a1d21',
    colorTextSecondary: '#4b5563',
    colorTextTertiary: '#6b7280',
    colorTextQuaternary: '#9ca3af',
    borderRadius: 8,
    fontFamily:
      "'Fira Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    fontFamilyCode: "'Fira Code', ui-monospace, Menlo, Monaco, Consolas, monospace",
  },
  components: {
    Layout: {
      siderBg: '#ffffff',
      headerBg: '#ffffff',
      bodyBg: '#eef0f3',
    },
    Menu: {
      itemBg: 'transparent',
      itemSelectedBg: '#eef0ff',
      itemHoverBg: '#f4f5f7',
    },
    Card: {
      colorBgContainer: '#ffffff',
    },
    Table: {
      headerBg: '#f4f5f7',
      rowHoverBg: '#f9fafb',
    },
  },
}
