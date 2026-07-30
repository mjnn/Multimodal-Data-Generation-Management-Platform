import { MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { useThemeMode } from '../context/ThemeContext'

export function ThemeToggle() {
  const { mode, toggleMode } = useThemeMode()
  const isDark = mode === 'dark'
  return (
    <Tooltip title={isDark ? '切换为浅色模式' : '切换为深色模式'}>
      <Button
        type="text"
        aria-label={isDark ? '浅色模式' : '深色模式'}
        icon={isDark ? <SunOutlined /> : <MoonOutlined />}
        onClick={toggleMode}
      />
    </Tooltip>
  )
}
