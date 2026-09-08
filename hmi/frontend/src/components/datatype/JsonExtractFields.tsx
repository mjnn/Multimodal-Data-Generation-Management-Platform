import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Input, Typography } from 'antd'
import type { RecipeGraphNode } from '../../api/types'

type Props = {
  node: RecipeGraphNode
  onPatch: (patch: Partial<RecipeGraphNode>) => void
}

function pathKeysOf(node: RecipeGraphNode): string[] {
  const raw = node.params?.path_keys
  if (Array.isArray(raw) && raw.length) return raw.map((x) => String(x ?? ''))
  if (typeof raw === 'string' && raw.trim()) return raw.split('.').map((p) => p.trim()).filter(Boolean)
  return ['']
}

export function JsonExtractFields({ node, onPatch }: Props) {
  const params = node.params || {}
  const keys = pathKeysOf(node)
  const compiled = keys.map((k) => k.trim()).filter(Boolean).join('.')
  const setKeys = (next: string[]) => onPatch({ params: { ...params, path_keys: next } })
  return (
    <div className="pipe-step__params" data-testid="pipe-json-extract-keys">
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        键路径（嵌套点 +）
      </Typography.Text>
      {keys.map((key, idx) => (
        <div key={`path-${idx}`} className="dag-inspector__path-row">
          <Input
            placeholder={idx === 0 ? '键名，如 a' : '嵌套键'}
            value={key}
            data-testid={`pipe-json-extract-key-${idx}`}
            onChange={(e) => {
              const next = [...keys]
              next[idx] = e.target.value
              setKeys(next)
            }}
          />
          <Button
            type="text"
            size="small"
            danger
            icon={<MinusCircleOutlined />}
            disabled={keys.length <= 1}
            data-testid={`pipe-json-extract-remove-${idx}`}
            onClick={() => setKeys(keys.filter((_, i) => i !== idx))}
          />
        </div>
      ))}
      <Button
        type="dashed"
        size="small"
        icon={<PlusOutlined />}
        data-testid="pipe-json-extract-add"
        onClick={() => setKeys([...keys, ''])}
      >
        嵌套层级
      </Button>
      {compiled ? (
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          编译路径 {compiled}
        </Typography.Text>
      ) : null}
    </div>
  )
}
