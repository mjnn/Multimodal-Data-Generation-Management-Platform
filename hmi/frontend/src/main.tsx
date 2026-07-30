import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'
import { ThemeProvider, useThemeMode } from './context/ThemeContext'

function ThemedApp() {
  const { antdTheme } = useThemeMode()
  return (
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <App />
    </ConfigProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  </StrictMode>,
)
