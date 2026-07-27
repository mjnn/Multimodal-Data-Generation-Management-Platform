#!/usr/bin/env python3
"""Generate standalone HTML and Markdown for OMS label taxonomy tree."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH
PROJECT_ROOT = HMI_ROOT
TAXONOMY_PATH = PROJECT_ROOT / "config" / "oms_label_taxonomy.yaml"
OUTPUT_HTML = PROJECT_ROOT / "docs" / "oms_label_taxonomy.html"
OUTPUT_MD = PROJECT_ROOT / "docs" / "oms_label_taxonomy.md"

LEVEL_COLORS = {
    "L1": "#2563eb",
    "L2": "#7c3aed",
    "L3": "#059669",
    "L4": "#d97706",
    "L5": "#dc2626",
    "L6": "#0891b2",
}

LEVEL_NAMES = {
    "L1": "环境与车辆",
    "L2": "乘员与状态",
    "L3": "行为交互",
    "L4": "意图推断",
    "L5": "决策与反馈",
    "L6": "质量与安全",
}


def _major(level_code: str) -> str:
    return level_code.split(".")[0] if level_code else "other"


def build_tree(labels: list[dict]) -> list[dict]:
    majors: dict[str, dict] = {}
    for item in labels:
        level_code = str(item.get("level_code") or "other")
        level_name = str(item.get("level_name") or level_code)
        major = _major(level_code)
        if major not in majors:
            majors[major] = {
                "id": major,
                "name": LEVEL_NAMES.get(major, major),
                "color": LEVEL_COLORS.get(major, "#64748b"),
                "children": {},
            }
        groups = majors[major]["children"]
        if level_code not in groups:
            groups[level_code] = {"id": level_code, "name": level_name, "children": []}
        groups[level_code]["children"].append(
            {
                "no": item.get("no"),
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "definition": str(item.get("definition") or ""),
                "dtype": str(item.get("dtype") or ""),
                "value_schema": item.get("value_schema") or {},
                "values_hint": str(item.get("values_hint") or ""),
                "selection_reason": str(item.get("selection_reason") or ""),
            }
        )
    tree = []
    for major in sorted(majors.keys(), key=lambda x: (len(x), x)):
        node = majors[major]
        group_map = node["children"]
        node["children"] = [group_map[k] for k in sorted(group_map.keys())]
        tree.append(node)
    return tree


def render_html(meta: dict, tree: list[dict]) -> str:
    data_json = json.dumps({"meta": meta, "tree": tree}, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>OMS 标签树 · {html.escape(meta.get('version', ''))}</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --panel: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --border: #e2e8f0;
      --accent: #2563eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(255,255,255,.92);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
    }}
    h1 {{ margin: 0 0 6px; font-size: 1.35rem; }}
    .meta {{ color: var(--muted); font-size: .9rem; }}
    .toolbar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 12px;
      align-items: center;
    }}
    input[type="search"] {{
      flex: 1;
      min-width: 220px;
      padding: 10px 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: .95rem;
    }}
    button {{
      padding: 9px 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      cursor: pointer;
    }}
    button:hover {{ border-color: var(--accent); color: var(--accent); }}
    main {{
      display: grid;
      grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.1fr);
      gap: 16px;
      padding: 16px 24px 32px;
      max-width: 1600px;
      margin: 0 auto;
    }}
    @media (max-width: 960px) {{
      main {{ grid-template-columns: 1fr; }}
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
    }}
    .panel h2 {{
      margin: 0;
      padding: 12px 16px;
      font-size: .95rem;
      border-bottom: 1px solid var(--border);
      background: #f1f5f9;
    }}
    .tree-wrap {{ max-height: calc(100vh - 180px); overflow: auto; padding: 8px 0; }}
    ul.tree {{ list-style: none; margin: 0; padding: 0 0 0 8px; }}
    .node {{
      border-left: 2px solid transparent;
      margin: 2px 0;
    }}
    .node.major > .row {{ font-weight: 600; }}
    .node.group > .row {{ font-weight: 500; color: #334155; }}
    .row {{
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 6px;
      cursor: pointer;
      user-select: none;
    }}
    .row:hover {{ background: #f1f5f9; }}
    .row.active {{ background: #dbeafe; }}
    .toggle {{
      width: 18px;
      text-align: center;
      color: var(--muted);
      flex-shrink: 0;
    }}
    .badge {{
      font-size: .72rem;
      padding: 1px 6px;
      border-radius: 999px;
      color: #fff;
      flex-shrink: 0;
    }}
    .count {{ color: var(--muted); font-size: .8rem; margin-left: auto; }}
    .leaf-id {{ font-family: Consolas, monospace; font-size: .78rem; color: var(--muted); }}
    .children {{ display: none; padding-left: 14px; }}
    .children.open {{ display: block; }}
    .detail {{
      padding: 16px 18px;
      min-height: 280px;
    }}
    .detail.empty {{ color: var(--muted); }}
    .detail h3 {{ margin: 0 0 4px; }}
    .detail .id {{ font-family: Consolas, monospace; color: var(--accent); margin-bottom: 12px; }}
    .kv {{ margin: 10px 0; }}
    .kv dt {{ font-size: .78rem; color: var(--muted); margin-bottom: 2px; }}
    .kv dd {{ margin: 0 0 8px; white-space: pre-wrap; word-break: break-word; }}
    .schema {{
      background: #0f172a;
      color: #e2e8f0;
      padding: 12px;
      border-radius: 8px;
      font-family: Consolas, monospace;
      font-size: .8rem;
      overflow: auto;
      max-height: 220px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }}
    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: .8rem;
      color: var(--muted);
    }}
    .legend i {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }}
    mark {{ background: #fef08a; padding: 0 2px; border-radius: 2px; }}
  </style>
</head>
<body>
  <header>
    <h1>OMS 标签树</h1>
    <div class="meta" id="meta"></div>
    <div class="legend" id="legend"></div>
    <div class="toolbar">
      <input type="search" id="q" placeholder="搜索 id / 名称 / 定义 / 取值…" />
      <button type="button" id="expandAll">全部展开</button>
      <button type="button" id="collapseAll">全部折叠</button>
    </div>
  </header>
  <main>
    <section class="panel">
      <h2>层级结构 <span id="matchCount" style="font-weight:400;color:#64748b"></span></h2>
      <div class="tree-wrap"><ul class="tree" id="tree"></ul></div>
    </section>
    <section class="panel">
      <h2>标签详情</h2>
      <div class="detail empty" id="detail">点击左侧叶子节点查看定义、类型与取值 schema。</div>
    </section>
  </main>
  <script>
    const DATA = {data_json};

    const metaEl = document.getElementById('meta');
    const legendEl = document.getElementById('legend');
    const treeEl = document.getElementById('tree');
    const detailEl = document.getElementById('detail');
    const qEl = document.getElementById('q');
    const matchCountEl = document.getElementById('matchCount');

    metaEl.textContent = `版本 ${{DATA.meta.version}} · 共 ${{DATA.meta.label_count}} 项 · 来源 ${{DATA.meta.source}}`;
    DATA.tree.forEach(t => {{
      const s = document.createElement('span');
      s.innerHTML = `<i style="background:${{t.color}}"></i>${{t.id}} ${{t.name}}`;
      legendEl.appendChild(s);
    }});

    function schemaText(v) {{
      try {{ return JSON.stringify(v, null, 2); }} catch {{ return String(v); }}
    }}

    function leafHaystack(leaf) {{
      return [leaf.no, leaf.id, leaf.name, leaf.definition, leaf.dtype,
        leaf.values_hint, leaf.selection_reason, schemaText(leaf.value_schema)]
        .join(' ').toLowerCase();
    }}

    function renderDetail(leaf) {{
      detailEl.classList.remove('empty');
      detailEl.innerHTML = `
        <h3>${{leaf.name}} <small style="color:#64748b">#${{leaf.no || ''}}</small></h3>
        <div class="id">${{leaf.id}}</div>
        <dl class="kv">
          <dt>定义</dt><dd>${{leaf.definition || '—'}}</dd>
          <dt>数据类型</dt><dd>${{leaf.dtype || '—'}}</dd>
          <dt>取值提示</dt><dd>${{leaf.values_hint || '—'}}</dd>
          <dt>选用理由</dt><dd>${{leaf.selection_reason || '—'}}</dd>
          <dt>value_schema</dt>
          <dd><pre class="schema">${{schemaText(leaf.value_schema)}}</pre></dd>
        </dl>`;
    }}

    function makeToggle(childrenUl) {{
      const btn = document.createElement('span');
      btn.className = 'toggle';
      btn.textContent = '▸';
      const setOpen = (open) => {{
        childrenUl.classList.toggle('open', open);
        btn.textContent = open ? '▾' : '▸';
      }};
      btn.addEventListener('click', (e) => {{
        e.stopPropagation();
        setOpen(!childrenUl.classList.contains('open'));
      }});
      return {{ btn, setOpen }};
    }}

    function buildLeaf(leaf) {{
      const li = document.createElement('li');
      li.className = 'node leaf';
      li.dataset.hay = leafHaystack(leaf);
      const row = document.createElement('div');
      row.className = 'row';
      row.innerHTML = `<span class="toggle">•</span><span>${{leaf.name}}</span><span class="leaf-id">${{leaf.id}}</span>`;
      row.addEventListener('click', () => {{
        document.querySelectorAll('.row.active').forEach(r => r.classList.remove('active'));
        row.classList.add('active');
        renderDetail(leaf);
      }});
      li.appendChild(row);
      return li;
    }}

    function buildGroup(group) {{
      const li = document.createElement('li');
      li.className = 'node group';
      const row = document.createElement('div');
      row.className = 'row';
      const childrenUl = document.createElement('ul');
      childrenUl.className = 'children';
      const {{ btn, setOpen }} = makeToggle(childrenUl);
      row.appendChild(btn);
      const title = document.createElement('span');
      title.textContent = `${{group.id}} ${{group.name}}`;
      row.appendChild(title);
      const count = document.createElement('span');
      count.className = 'count';
      count.textContent = `${{group.children.length}}`;
      row.appendChild(count);
      row.addEventListener('click', () => setOpen(!childrenUl.classList.contains('open')));
      group.children.forEach(c => childrenUl.appendChild(buildLeaf(c)));
      li.appendChild(row);
      li.appendChild(childrenUl);
      li._setOpen = setOpen;
      return li;
    }}

    function buildMajor(major) {{
      const li = document.createElement('li');
      li.className = 'node major';
      const row = document.createElement('div');
      row.className = 'row';
      const childrenUl = document.createElement('ul');
      childrenUl.className = 'children open';
      const {{ btn, setOpen }} = makeToggle(childrenUl);
      row.appendChild(btn);
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.style.background = major.color;
      badge.textContent = major.id;
      row.appendChild(badge);
      const title = document.createElement('span');
      title.textContent = major.name;
      row.appendChild(title);
      const count = document.createElement('span');
      count.className = 'count';
      const n = major.children.reduce((s, g) => s + g.children.length, 0);
      count.textContent = `${{n}} 项`;
      row.appendChild(count);
      row.addEventListener('click', () => setOpen(!childrenUl.classList.contains('open')));
      major.children.forEach(g => childrenUl.appendChild(buildGroup(g)));
      li.appendChild(row);
      li.appendChild(childrenUl);
      li._setOpen = setOpen;
      return li;
    }}

    function renderTree(filter = '') {{
      const q = filter.trim().toLowerCase();
      treeEl.innerHTML = '';
      let visible = 0;
      DATA.tree.forEach(major => {{
        const majorLi = buildMajor(major);
        let majorShow = false;
        majorLi.querySelectorAll('.node.leaf').forEach(leafLi => {{
          const hit = !q || leafLi.dataset.hay.includes(q);
          leafLi.style.display = hit ? '' : 'none';
          if (hit) {{ visible++; majorShow = true; }}
        }});
        majorLi.querySelectorAll('.node.group').forEach(groupLi => {{
          const leaves = [...groupLi.querySelectorAll('.node.leaf')];
          const any = leaves.some(l => l.style.display !== 'none');
          groupLi.style.display = any ? '' : 'none';
          if (any && groupLi._setOpen) groupLi._setOpen(true);
        }});
        majorLi.style.display = majorShow ? '' : 'none';
        if (majorShow && majorLi._setOpen) majorLi._setOpen(true);
        treeEl.appendChild(majorLi);
      }});
      matchCountEl.textContent = q ? `（匹配 ${{visible}} 项）` : '';
    }}

    document.getElementById('expandAll').onclick = () => {{
      document.querySelectorAll('.children').forEach(el => el.classList.add('open'));
      document.querySelectorAll('.toggle').forEach(el => {{
        if (el.textContent === '▸' || el.textContent === '▾') el.textContent = '▾';
      }});
    }};
    document.getElementById('collapseAll').onclick = () => {{
      document.querySelectorAll('.children').forEach(el => el.classList.remove('open'));
      document.querySelectorAll('.toggle').forEach(el => {{
        if (el.textContent === '▸' || el.textContent === '▾') el.textContent = '▸';
      }});
    }};
    qEl.addEventListener('input', () => renderTree(qEl.value));
    renderTree();
  </script>
</body>
</html>
"""


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _schema_md(schema: dict) -> str:
    if not schema:
        return "—"
    return f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```"


def render_markdown(meta: dict, tree: list[dict]) -> str:
    lines = [
        "# OMS 标签树",
        "",
        f"- **版本**：{meta.get('version', '')}",
        f"- **标签数**：{meta.get('label_count', 0)}",
        f"- **来源**：{meta.get('source', '')}",
        "",
        "## 目录",
        "",
    ]
    for major in tree:
        lines.append(f"- [{major['id']} {major['name']}](#{major['id']}-{major['name']})")
        for group in major["children"]:
            anchor = f"{group['id']}-{group['name']}"
            lines.append(f"  - [{group['id']} {group['name']}](#{anchor})")
    lines.append("")
    lines.append("---")
    lines.append("")

    for major in tree:
        n = sum(len(g["children"]) for g in major["children"])
        lines.append(f"## {major['id']} {major['name']} ({n} 项)")
        lines.append("")
        for group in major["children"]:
            lines.append(f"### {group['id']} {group['name']}")
            lines.append("")
            lines.append(
                "| # | ID | 名称 | 类型 | 取值提示 |"
            )
            lines.append("|:-:|----|------|------|----------|")
            for leaf in group["children"]:
                lines.append(
                    f"| {leaf.get('no') or ''} "
                    f"| `{leaf['id']}` "
                    f"| {leaf['name']} "
                    f"| {_md_escape(leaf['dtype'])} "
                    f"| {_md_escape(leaf['values_hint'])} |"
                )
            lines.append("")
            for leaf in group["children"]:
                lines.append(f"#### `{leaf['id']}` {leaf['name']}")
                lines.append("")
                lines.append(f"**定义**：{leaf['definition'] or '—'}")
                lines.append("")
                lines.append(f"**选用理由**：{leaf['selection_reason'] or '—'}")
                lines.append("")
                lines.append("**value_schema**：")
                lines.append("")
                lines.append(_schema_md(leaf["value_schema"]))
                lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(
        "> 由 `scripts/generate_oms_taxonomy_html.py` 从 "
        "`config/oms_label_taxonomy.yaml` 自动生成。"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not TAXONOMY_PATH.is_file():
        print(f"taxonomy not found: {TAXONOMY_PATH}", file=sys.stderr)
        return 1
    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    labels = data.get("labels") or []
    meta = {
        "version": data.get("version", ""),
        "source": data.get("source", ""),
        "label_count": data.get("label_count", len(labels)),
    }
    tree = build_tree(labels)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(render_html(meta, tree), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(meta, tree), encoding="utf-8")
    print(f"wrote {OUTPUT_HTML} ({len(labels)} labels)")
    print(f"wrote {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
