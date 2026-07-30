import { PlusOutlined, StarFilled } from '@ant-design/icons'
import { Button, Input, Modal, Space, Spin, Tooltip, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { OssShortcut } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { safeRandomId } from '../../utils/id'
import { apiErrorMessage } from '../../utils/apiError'

/** Legacy browser-global shortcuts (migrated once into the signed-in account). */
const LEGACY_STORAGE_KEY = 'hmi:oss-custom-shortcuts'

function loadLegacyLocal(): OssShortcut[] {
  try {
    const raw = localStorage.getItem(LEGACY_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as OssShortcut[]
    return Array.isArray(parsed)
      ? parsed
          .filter((s) => s.label && s.prefix)
          .map((s) => ({
            id: s.id || safeRandomId(),
            label: s.label,
            prefix: s.prefix,
          }))
      : []
  } catch {
    return []
  }
}

type Preset = { label: string; prefix: string; hint?: string }

type Props = {
  presets: Preset[]
  onNavigate: (prefix: string) => void
}

export function OssShortcutBar({ presets, onNavigate }: Props) {
  const { user } = useAuth()
  const [custom, setCustom] = useState<OssShortcut[]>([])
  const [loading, setLoading] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [prefix, setPrefix] = useState('')

  const persist = useCallback(async (items: OssShortcut[]) => {
    if (!user) return
    try {
      await api.saveOssShortcuts(items)
    } catch (e) {
      message.error(apiErrorMessage(e, '保存快捷路径失败'))
      throw e
    }
  }, [user])

  useEffect(() => {
    if (!user) {
      setCustom([])
      return
    }
    let cancelled = false
    setLoading(true)
    void (async () => {
      try {
        let items = (await api.getOssShortcuts()).items
        if (!items.length) {
          const legacy = loadLegacyLocal()
          if (legacy.length) {
            const saved = await api.saveOssShortcuts(legacy)
            items = saved.items
            localStorage.removeItem(LEGACY_STORAGE_KEY)
          }
        }
        if (!cancelled) setCustom(items)
      } catch (e) {
        if (!cancelled) {
          message.error(apiErrorMessage(e, '加载快捷路径失败'))
          setCustom([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [user?.id])

  const addShortcut = useCallback(async () => {
    const l = label.trim()
    let p = prefix.trim().replace(/^\/+/, '')
    if (!l || !p) {
      message.warning('请填写名称与路径')
      return
    }
    if (!p.endsWith('/')) p += '/'
    if (p.includes('..')) {
      message.error('路径非法')
      return
    }
    const next: OssShortcut[] = [...custom, { id: safeRandomId(), label: l, prefix: p }]
    try {
      await persist(next)
      setCustom(next)
      setLabel('')
      setPrefix('')
      setAddOpen(false)
      message.success('已添加快捷路径')
    } catch {
      /* persist showed error */
    }
  }, [custom, label, persist, prefix])

  const removeCustom = async (id: string) => {
    const next = custom.filter((s) => s.id !== id)
    try {
      await persist(next)
      setCustom(next)
    } catch {
      /* persist showed error */
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        快捷访问：预设路径全局共用；自定义路径保存在当前登录账号下（换账号或换设备登录后各自独立）
      </Typography.Text>
      {loading ? (
        <Spin size="small" />
      ) : (
        <Space wrap>
          {presets.map((z) => (
            <Tooltip key={z.prefix} title={z.hint ?? z.prefix}>
              <Button onClick={() => onNavigate(z.prefix)}>
                {z.label}
                <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                  {z.prefix}
                </Typography.Text>
              </Button>
            </Tooltip>
          ))}
          {custom.map((s) => (
            <Button key={s.id} onClick={() => onNavigate(s.prefix)}>
              <StarFilled style={{ color: '#faad14', marginRight: 4 }} />
              {s.label}
              <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                {s.prefix}
              </Typography.Text>
              <Typography.Text
                type="secondary"
                role="button"
                tabIndex={0}
                style={{ marginLeft: 8, fontSize: 11 }}
                onClick={(e) => {
                  e.stopPropagation()
                  void removeCustom(s.id)
                }}
              >
                移除
              </Typography.Text>
            </Button>
          ))}
          <Button icon={<PlusOutlined />} onClick={() => setAddOpen(true)} disabled={!user}>
            自定义路径
          </Button>
        </Space>
      )}

      <Modal
        title="添加快捷访问路径"
        open={addOpen}
        onOk={() => void addShortcut()}
        onCancel={() => setAddOpen(false)}
        okText="添加"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input placeholder="显示名称，如 某 clip 产物" value={label} onChange={(e) => setLabel(e.target.value)} />
          <Input
            placeholder="OSS 前缀，如 clips/sha256__xxx/runs/uuid/"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            addonBefore="/"
          />
        </Space>
      </Modal>
    </Space>
  )
}
