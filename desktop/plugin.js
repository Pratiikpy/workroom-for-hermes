import { createElement as h, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SandboxedFrame, host, useValue, Tabs, TabsList, TabsTrigger, Badge, EmptyState, STATUSBAR_AREAS, PALETTE_AREA } from '@hermes/plugin-sdk'
import { TRANSCRIPT_DIRECTIVE_AREA } from '@hermes/plugin-sdk'

const css = {
  page: { display: 'flex', flexDirection: 'column', gap: 16, padding: 20, height: '100%', overflow: 'auto', color: 'var(--ui-text-primary, inherit)', fontSize: 13, lineHeight: 1.5 },
  title: { fontSize: 18, fontWeight: 600, margin: 0 },
  sub: { color: 'var(--ui-text-tertiary, #888)', margin: '2px 0 0' },
  card: { border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 10, padding: 14, background: 'var(--ui-bg-elevated, transparent)' },
  row: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' },
  input: { flex: 1, minWidth: 220, padding: '7px 9px', borderRadius: 8, border: '1px solid var(--ui-stroke-secondary, #8886)', background: 'transparent', color: 'inherit', font: 'inherit' },
  btn: { padding: '7px 12px', borderRadius: 8, border: '1px solid var(--ui-stroke-secondary, #8886)', background: 'var(--ui-control-hover-background, #8881)', color: 'inherit', font: 'inherit', cursor: 'pointer' },
  primary: { background: 'var(--ui-accent, #3b82f6)', color: '#fff', border: '1px solid transparent' },
  disabled: { opacity: 0.45, cursor: 'not-allowed' },
  h2: { fontSize: 13, fontWeight: 600, margin: '0 0 8px', letterSpacing: 0.2 },
  muted: { color: 'var(--ui-text-tertiary, #888)' },
  chip: { display: 'inline-block', padding: '1px 8px', borderRadius: 999, fontSize: 11, border: '1px solid var(--ui-stroke-secondary, #8886)' }
}

const btn = (label, onClick, { primary = false, disabled = false, name } = {}) =>
  h('button', { type: 'button', 'aria-label': name, onClick: disabled ? undefined : onClick, disabled, style: { ...css.btn, ...(primary ? css.primary : {}), ...(disabled ? css.disabled : {}) } }, label)

const Banner = ({ kind, children }) =>
  h('div', {
    role: kind === 'error' ? 'alert' : 'status',
    style: { ...css.card, borderColor: kind === 'error' ? 'var(--ui-red, #dc2626)' : kind === 'ok' ? 'var(--ui-green, #16a34a)' : undefined }
  }, children)

function Changes({ changes }) {
  if (!changes.length) return h('div', { style: css.muted }, 'No linked number has changed since the last release.')
  return h('table', { style: { width: '100%', borderCollapse: 'collapse' } },
    h('thead', null, h('tr', null, ['Document', 'Where', 'Was', 'Becomes', 'Because'].map(t => h('th', { key: t, style: { textAlign: 'left', padding: '4px 8px', ...css.muted, fontWeight: 500 } }, t)))),
    h('tbody', null, changes.map((c, i) => h('tr', { key: i, style: { borderTop: '1px solid var(--ui-stroke-tertiary, #8883)' } },
      h('td', { style: { padding: '6px 8px' } }, c.deck),
      h('td', { style: { padding: '6px 8px' } }, c.where || `Slide ${c.slide}`),
      h('td', { style: { padding: '6px 8px', textDecoration: 'line-through', ...css.muted } }, c.old_text),
      h('td', { style: { padding: '6px 8px', fontWeight: 600 } }, c.new_text),
      h('td', { style: { padding: '6px 8px', ...css.muted } }, `${c.src}: ${c.old_value} → ${c.new_value}`)))))
}

const num = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 })

function Inbox({ inbox }) {
  if (!inbox || (!inbox.changes.length && !inbox.blocked.length)) return null
  const tag = (d) => d === 'auto' ? 'will update' : d === 'hold' ? 'held for you' : 'blocked'
  return h('div', { role: 'region', 'aria-label': 'Changes inbox', style: { marginTop: 10 } },
    inbox.changes.map(c => h('div', { key: c.src, style: { ...css.card, marginBottom: 8 } },
      c.kind === 'calculation'
        ? h('div', { style: { fontWeight: 600 } }, `Calculated figure: ${Number(c.old_value).toFixed(c.unit === '%' ? 1 : 2)}${c.unit} → ${Number(c.new_value).toFixed(c.unit === '%' ? 1 : 2)}${c.unit}`)
        : h('div', { style: { fontWeight: 600 } }, `${c.label || c.src}: ${num(c.old_value)} → ${num(c.new_value)} (${c.delta_pct.toFixed(1)}%)`),
      h('div', { style: css.muted }, c.kind === 'calculation' ? `${c.label} · ${c.counts.auto} will update, ${c.counts.hold} held for you` : `${c.src} · ${c.counts.auto} will update, ${c.counts.hold} held for you`),
      h('ul', { style: { margin: '6px 0 0', paddingLeft: 18 } }, c.elements.map(e => h('li', { key: e.tie_id },
        `${e.deck}, ${e.where || 'slide ' + e.slide}: “${(e.sentence || '').slice(0, 90)}” ${e.text_before}${e.text_after ? ' → ' + e.text_after : ''} (${tag(e.decision)}; ${e.reason})`))))),
    inbox.blocked.length ? h('div', { style: { ...css.card, marginBottom: 8 } },
      h('div', { style: { fontWeight: 600 } }, 'Linked numbers whose source is missing'),
      h('ul', { style: { margin: '6px 0 0', paddingLeft: 18 } }, inbox.blocked.map(e => h('li', { key: e.tie_id }, `${e.deck}, ${e.where || 'slide ' + e.slide}: ${e.text_before} (${e.reason})`)))) : null)
}

const MAP = { W: 940, srcX: 14, srcW: 280, elX: 500, elW: 426, srcH: 62, elH: 48, gap: 10, groupGap: 24, groupH: 24, pad: 14, cap: 80 }
const clip = (s, n) => { const t = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1) + '…' : t }
const tone = (st) => st === 'update' ? 'var(--ui-green, #16a34a)' : st === 'held' ? 'var(--ui-amber, #d97706)' : 'var(--ui-red, #dc2626)'
const stateWord = (st) => st === 'update' ? 'will update' : st === 'held' ? 'held for you' : 'source missing'

function layoutMap(map) {
  const shown = map.elements.slice(0, MAP.cap)
  const hidden = map.elements.length - shown.length
  const els = {}
  const heads = []
  let y = MAP.pad
  for (const d of map.documents) {
    const items = shown.filter(e => e.document === d.id)
    if (!items.length) continue
    heads.push({ doc: d, y, total: d.elements })
    y += MAP.groupH
    for (const e of items) { els[e.id] = { e, x: MAP.elX, y, w: MAP.elW, h: MAP.elH }; y += MAP.elH + MAP.gap }
    y += MAP.groupGap - MAP.gap
  }
  const order = map.sources.map(s => {
    const ys = shown.filter(e => e.source === s.id).map(e => els[e.id].y + MAP.elH / 2)
    return { s, want: ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Infinity }
  }).sort((a, b) => a.want - b.want)
  const srcs = {}
  let cursor = MAP.pad
  for (const o of order) {
    const top = Math.max(cursor, Number.isFinite(o.want) ? o.want - MAP.srcH / 2 : cursor)
    srcs[o.s.id] = { s: o.s, x: MAP.srcX, y: top, w: MAP.srcW, h: MAP.srcH }
    cursor = top + MAP.srcH + MAP.gap
  }
  return { W: MAP.W, H: Math.max(y, cursor) + MAP.pad, els, srcs, heads, hidden, shown }
}

function ChangeMap({ map, folder, ctx }) {
  const [sel, setSel] = useState(null)
  const [focus, setFocus] = useState(null)
  const [drawn, setDrawn] = useState(false)
  const lay = useMemo(() => layoutMap(map), [map])
  const fmap = useMemo(() => Object.fromEntries(map.findings.map(f => [f.id, f])), [map])
  const calm = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  useEffect(() => {
    setDrawn(calm)
    const id = requestAnimationFrame(() => setDrawn(true))
    return () => cancelAnimationFrame(id)
  }, [map, calm])
  useEffect(() => { setSel(null) }, [map])
  if (!map.sources.length) return h('div', { style: css.muted }, 'No linked number has changed since the last release.')
  const t = map.totals
  const goneCount = map.sources.filter(s => s.missing).length
  const changedCount = map.sources.length - goneCount
  const near = (() => {
    if (!sel) return null
    const ids = new Set([sel])
    if (sel[0] === 's') map.elements.filter(e => e.source === sel).forEach(e => ids.add(e.id))
    else { const e = map.elements.find(x => x.id === sel); if (e) ids.add(e.source) }
    return ids
  })()
  const dim = (id) => near && !near.has(id) ? 0.25 : 1
  const pick = (id) => setSel(sel === id ? null : id)
  const keys = (id) => (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(id) } else if (ev.key === 'Escape') setSel(null) }
  const sev = (e) => e.flags.length ? (e.flags.some(id => fmap[id] && fmap[id].severity === 'high') ? 'high' : 'medium') : ''
  const txt = { fill: 'var(--ui-text-primary, #1c1c1e)', fontSize: 12.5, pointerEvents: 'none' }
  const sub = { ...txt, fill: 'var(--ui-text-tertiary, #6b6b70)', fontSize: 11.5 }
  const box = (id, x, y, w, hgt, color, dashed) => h('rect', {
    x, y, width: w, height: hgt, rx: 9, style: { fill: 'var(--ui-bg-elevated, #fff)', stroke: sel === id || focus === id ? 'var(--ui-accent, #2f6feb)' : dashed ? color : 'var(--ui-stroke-secondary, #d6d6da)', strokeWidth: sel === id || focus === id ? 2.4 : 1.2, strokeDasharray: dashed ? '5 4' : undefined }
  })
  const node = (id, label, shape) => h('g', { key: id, role: 'button', tabIndex: 0, 'aria-pressed': sel === id, 'aria-label': label, onClick: () => pick(id), onKeyDown: keys(id), onFocus: () => setFocus(id), onBlur: () => setFocus(null), style: { cursor: 'pointer', outline: 'none', opacity: dim(id), transition: 'opacity 160ms' } }, ...shape)
  const sources = Object.values(lay.srcs).map(({ s, x, y, w, h: hh }) => {
    const miss = s.missing
    const lines = miss ? ['Source cell is gone', clip(`${s.file} · ${s.sheet}!${s.ref}`, 40), s.old != null ? `was ${num(s.old)}` : ''] :
      s.kind === 'calculation' ? [clip(s.label, 38), `${Number(s.old).toFixed(s.unit === '%' ? 1 : 2)}${s.unit} → ${Number(s.new).toFixed(s.unit === '%' ? 1 : 2)}${s.unit}`, 'calculated figure'] :
      [clip(s.label || s.key, 38), `${num(s.old)} → ${num(s.new)} (${s.delta_pct.toFixed(1)}%)`, clip(`${s.file} · ${s.sheet}!${s.ref}`, 40)]
    return node(s.id, miss ? `Missing source ${s.sheet} ${s.ref}` : `Source ${lines[0]}, ${lines[1]}`, [
      box(s.id, x, y, w, hh, miss ? tone('blocked') : 'var(--ui-accent, #2f6feb)', miss || s.kind === 'calculation'),
      h('rect', { x, y: y + 8, width: 4, height: hh - 16, rx: 2, style: { fill: miss ? tone('blocked') : 'var(--ui-accent, #2f6feb)' } }),
      h('text', { x: x + 14, y: y + 20, style: { ...txt, fontWeight: 600 } }, lines[0]),
      h('text', { x: x + 14, y: y + 37, style: txt }, lines[1]),
      h('text', { x: x + 14, y: y + 53, style: sub }, lines[2]),
      h('title', null, miss ? `${s.key} is no longer a number in the workbook` : `${s.key}: ${num(s.old)} → ${num(s.new)}`)])
  })
  const places = Object.values(lay.els).map(({ e, x, y, w, h: hh }) => {
    const sv = sev(e)
    const change = e.after ? `${clip(e.before, 22)} → ${clip(e.after, 22)}` : clip(e.before, 30)
    return node(e.id, `${e.deck}, ${e.where}: ${e.before}${e.after ? ' becomes ' + e.after : ''}, ${stateWord(e.state)}${sv ? ', needs your check' : ''}`, [
      box(e.id, x, y, w, hh, tone(e.state), false),
      h('rect', { x, y: y + 7, width: 4, height: hh - 14, rx: 2, style: { fill: tone(e.state) } }),
      h('text', { x: x + 14, y: y + 20, style: { ...txt, fontWeight: 600 } }, `${clip(e.where, 26)} · ${stateWord(e.state)}`),
      h('text', { x: x + 14, y: y + 37, style: sub }, `${change}${e.sentence ? '  ·  ' + clip(e.sentence, 34) : ''}`),
      sv ? h('g', null, h('circle', { cx: x + w - 18, cy: y + hh / 2, r: 10, style: { fill: sv === 'high' ? 'var(--ui-red, #dc2626)' : 'var(--ui-amber, #d97706)' } }), h('text', { x: x + w - 18, y: y + hh / 2 + 4, textAnchor: 'middle', style: { fill: '#fff', fontSize: 13, fontWeight: 700, pointerEvents: 'none' } }, '!')) : null,
      h('title', null, `${e.sentence || e.before}${e.reason ? ' (' + e.reason + ')' : ''}`)])
  })
  const edges = map.edges.filter(ed => lay.els[ed.to] && lay.srcs[ed.from]).map((ed, i) => {
    const a = lay.srcs[ed.from], b = lay.els[ed.to]
    const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2
    const lit = near && near.has(ed.from) && near.has(ed.to)
    return h('path', { key: ed.from + ed.to, d: `M${x1} ${y1} C${x1 + 110} ${y1}, ${x2 - 110} ${y2}, ${x2} ${y2}`, fill: 'none', pathLength: 1,
      style: { stroke: tone(b.e.state), strokeWidth: lit ? 3 : 1.8, opacity: near ? (lit ? 1 : 0.12) : 0.7, strokeDasharray: 1, strokeDashoffset: drawn ? 0 : 1, transition: calm ? 'none' : `stroke-dashoffset 650ms ease-out ${Math.min(i, 20) * 35}ms, opacity 160ms` } })
  })
  const heads = lay.heads.map(g => h('text', { key: g.doc.id, x: MAP.elX, y: g.y + 15, style: { ...txt, fontWeight: 600, fontSize: 12 } }, `${g.doc.name}  ·  ${g.total} place${g.total === 1 ? '' : 's'}`))
  const chosen = sel && (sel[0] === 's' ? map.sources.find(s => s.id === sel) : map.elements.find(e => e.id === sel))
  const reach = chosen && chosen.id && sel[0] === 's' ? map.elements.filter(e => e.source === sel) : []
  const dot = (c) => h('span', { 'aria-hidden': true, style: { display: 'inline-block', width: 9, height: 9, borderRadius: 3, background: c, marginRight: 5 } })
  const reveal = (deck) => {
    const os = ctx && ctx.os
    if (!folder || !os || !os.revealPath) return
    const sep = folder.includes('\\') ? '\\' : '/'
    os.revealPath(folder.replace(/[\\/]+$/, '') + sep + deck.split('/').join(sep))
  }
  return h('div', null,
    h('div', { style: { ...css.row, justifyContent: 'space-between', marginBottom: 6 } },
      h('div', { style: css.muted }, `${changedCount} changed source${changedCount === 1 ? '' : 's'}${goneCount ? ` and ${goneCount} missing` : ''} reach${changedCount + goneCount === 1 ? 'es' : ''} ${t.places} place${t.places === 1 ? '' : 's'} in ${t.documents} document${t.documents === 1 ? '' : 's'}. Select a box to follow its links.`),
      h('div', { style: { ...css.row, gap: 12, fontSize: 11.5 } },
        h('span', null, dot(tone('update')), `${t.update} will update`), t.held ? h('span', null, dot(tone('held')), `${t.held} held for you`) : null,
        t.blocked ? h('span', null, dot(tone('blocked')), `${t.blocked} source missing`) : null)),
    h('div', { style: { overflowX: 'auto', border: '1px solid var(--ui-stroke-tertiary, #8883)', borderRadius: 10 } },
      h('svg', { role: 'group', 'aria-label': 'Change map: changed source cells on the left, the places in documents they reach on the right', viewBox: `0 0 ${lay.W} ${lay.H}`, style: { width: '100%', minWidth: 680, height: 'auto', display: 'block' } },
        h('text', { x: MAP.srcX, y: 11, style: { ...sub, fontSize: 10.5, letterSpacing: 0.4 } }, 'SOURCE CELLS'),
        h('text', { x: MAP.elX, y: 11, style: { ...sub, fontSize: 10.5, letterSpacing: 0.4 } }, 'WHERE THEY APPEAR'),
        heads, edges, sources, places)),
    lay.hidden ? h('div', { style: { ...css.muted, fontSize: 11.5, marginTop: 4 } }, `${lay.hidden} more place${lay.hidden === 1 ? ' is' : 's are'} not drawn to keep the map readable; the list shows all of them.`) : null,
    map.unattached_findings.length ? h('div', { style: { marginTop: 8, fontSize: 12 } }, `${map.unattached_findings.length} finding${map.unattached_findings.length === 1 ? '' : 's'} about the documents as a whole (listed below the map).`) : null,
    h('div', { role: 'region', 'aria-live': 'polite', 'aria-label': 'Selected link', style: { ...css.card, marginTop: 8, minHeight: 58 } },
      !chosen ? h('span', { style: css.muted }, 'Nothing selected. Pick a source cell to see everything it reaches, or a place to see where it comes from and what needs checking.') :
      sel[0] === 's' ? h('div', null,
        h('div', { style: { fontWeight: 600 } }, chosen.missing ? `${chosen.sheet}!${chosen.ref} in ${chosen.file} no longer holds a number` : `${chosen.label || chosen.key}: ${num(chosen.old)} → ${num(chosen.new)} (${chosen.delta_pct.toFixed(1)}%)`),
        h('div', { style: css.muted }, chosen.kind === 'calculation' ? 'A calculated figure: it follows the cells it was calculated from.' : `${chosen.file} · sheet ${chosen.sheet} · cell ${chosen.ref}`),
        h('ul', { style: { margin: '6px 0 0', paddingLeft: 18 } }, reach.map(e => h('li', { key: e.id }, `${e.deck}, ${e.where}: ${e.before}${e.after ? ' → ' + e.after : ''} (${stateWord(e.state)})`)))) :
      h('div', null,
        h('div', { style: { fontWeight: 600 } }, `${chosen.deck}, ${chosen.where}: ${chosen.before}${chosen.after ? ' → ' + chosen.after : ''}`),
        chosen.sentence ? h('div', { style: css.muted }, `“${clip(chosen.sentence, 160)}”`) : null,
        h('div', null, `${stateWord(chosen.state)}: ${chosen.reason}`),
        chosen.flags.map(id => fmap[id] ? h('div', { key: id, style: { marginTop: 6, color: fmap[id].severity === 'high' ? 'var(--ui-red, #dc2626)' : 'var(--ui-amber, #d97706)' } },
          h('div', { style: { fontWeight: 600 } }, fmap[id].summary), (fmap[id].evidence || []).slice(0, 3).map((x, i) => h('div', { key: i, style: { fontSize: 12 } }, x)),
          fmap[id].suggestion ? h('div', { style: { fontSize: 12 } }, fmap[id].suggestion) : null) : null),
        ctx && ctx.os && ctx.os.revealPath && folder ? h('div', { style: { marginTop: 8 } }, btn('Show this file in its folder', () => reveal(chosen.deck), { name: `Show ${chosen.deck} in its folder` })) : null)))
}

function ChangeViews({ inbox, folder, ctx }) {
  const [view, setView] = useState(typeof window !== 'undefined' && window.innerWidth < 700 ? 'list' : 'map')
  if (!inbox || (!inbox.changes.length && !inbox.blocked.length)) return null
  const tab = (id, label) => h('button', { type: 'button', role: 'tab', 'aria-selected': view === id, onClick: () => setView(id), style: { ...css.btn, ...(view === id ? css.primary : {}), padding: '4px 12px' } }, label)
  return h('div', { style: { marginTop: 10 } },
    h('div', { role: 'tablist', 'aria-label': 'How to show the changes', style: { ...css.row, marginBottom: 8 } }, tab('map', 'Map'), tab('list', 'List')),
    view === 'map' && inbox.map ? h(ChangeMap, { map: inbox.map, folder, ctx }) : h(Inbox, { inbox }))
}

function groupFigures(figures) {
  const out = []
  for (const f of figures || []) {
    const hit = out.find(g => g.source === f.source && g.text === f.text)
    if (hit) hit.count += 1; else out.push({ ...f, count: 1 })
  }
  return out
}

let pluginCtx = null
let editorHandle = null
const editorTarget = { value: null, listeners: new Set() }
function openEditor(target) {
  setEditorTarget(target)
  if (!pluginCtx) return
  if (!editorHandle) {
    editorHandle = pluginCtx.register({ id: 'editor', area: 'panes', title: 'Workroom page', data: { placement: 'floating', anchor: 'top-right', width: 760, height: 560 }, render: () => h(PageEditor, { ctx: pluginCtx }) })
  } else {
    if (host.undismissPane) host.undismissPane('workroom:editor')
    if (host.revealPane) host.revealPane('workroom:editor')
  }
}
const setEditorTarget = (v) => { editorTarget.value = v; editorTarget.listeners.forEach(fn => fn(v)) }
const toDataUrl = (doc) => 'data:text/html;charset=utf-8,' + encodeURIComponent(doc)
const MAX_OPS = 500

function PageEditor({ ctx }) {
  const [target, setTarget] = useState(editorTarget.value)
  const [doc, setDoc] = useState(null)
  const [note, setNote] = useState('')
  const frameRef = useRef(null)
  const targetRef = useRef(target)
  targetRef.current = target
  useEffect(() => { editorTarget.listeners.add(setTarget); return () => editorTarget.listeners.delete(setTarget) }, [])
  useEffect(() => { ctx.rest('/scene-frame').then(d => setDoc(d.doc)).catch(e => setNote(String(e && e.message ? e.message : e))) }, [ctx])
  const send = (msg) => { const w = frameRef.current && frameRef.current.contentWindow; if (w) w.postMessage(msg, '*') }
  const call = (path, body) => ctx.rest(path, { method: 'POST', body })
  useEffect(() => {
    const onMsg = async (e) => {
      const w = frameRef.current && frameRef.current.contentWindow
      if (!w || e.source !== w) return
      const m = e.data
      const t = targetRef.current
      if (!m || typeof m !== 'object' || typeof m.op !== 'string') return
      if (m.op === 'ready') { if (t) load(t) }
      else if (!t) return
      else if (m.op === 'patch' && Array.isArray(m.ops) && m.ops.length <= MAX_OPS && Number.isInteger(m.rev)) {
        try { const r = await call('/scene-apply', { project: t.project, path: t.path, rev: m.rev, ops: m.ops }); send({ op: 'ack', rev: r.rev, scene: r.scene }) }
        catch (err) { try { const cur = await call('/scene-open', { project: t.project, path: t.path }); send({ op: 'error', message: String(err && err.message ? err.message : err), scene: cur.scene, rev: cur.rev }) } catch (e2) { send({ op: 'error', message: 'Could not reach Workroom.' }) } }
      } else if (m.op === 'save') {
        try { const r = await call('/scene-save', { project: t.project, path: t.path }); send({ op: 'say', message: 'Saved as a release. Approve it in the Workroom tab.' }); setNote('Release ' + r.release_id.slice(0, 8) + ' is waiting for your approval in the Workroom tab.') }
        catch (err) { send({ op: 'say', message: String(err && err.message ? err.message : err) }) }
      } else if (m.op === 'comment' && typeof m.text === 'string' && m.text.length <= 400) {
        const text = 'About ' + t.path + (typeof m.node === 'string' && m.node ? ', item ' + m.node.slice(0, 40) : '') + ': ' + m.text
        const put = () => Promise.resolve(host.composer.insertText(null, text, { mode: 'block' }))
        put().then((ok) => {
          if (ok) { send({ op: 'say', message: 'Added to your message box. Press Enter to send it.' }); return }
          host.newChat()
          setTimeout(() => put().then((ok2) => send({ op: 'say', message: ok2 ? 'Added to a new chat. Press Enter to send it.' : 'Could not reach a chat. Open one and try again.' })), 900)
        })
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])
  const load = async (t) => { try { const d = await call('/scene-open', { project: t.project, path: t.path }); send({ op: 'load', scene: d.scene, rev: d.rev }) } catch (err) { setNote(String(err && err.message ? err.message : err)) } }
  useEffect(() => { if (target) { setNote(''); load(target) } }, [target])
  return h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%', fontSize: 12 } },
    h('div', { style: { padding: '4px 8px', ...css.muted } }, target ? target.path : 'Choose a page in the Workroom tab'),
    doc ? h(SandboxedFrame, { ref: frameRef, src: toDataUrl(doc), title: 'Workroom page editor', style: { flex: 1, width: '100%', border: 0 } }) : h('div', { style: { padding: 8 } }, 'Loading the editor'),
    note ? h('div', { role: 'status', style: { padding: '4px 8px' } }, note) : null)
}

function PagesList({ api, pid }) {
  const [pages, setPages] = useState([])
  useEffect(() => { if (pid) api('/scenes', { project: pid }).then(setPages).catch(() => setPages([])); else setPages([]) }, [api, pid])
  if (!pages.length) return null
  return h('section', { style: css.card, 'aria-label': 'Visual pages' },
    h('h2', { style: css.h2 }, 'Visual pages'),
    pages.map(p => h('div', { key: p.path, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0' } },
      h('span', { style: { fontSize: 13 } }, p.path + (p.unsaved ? ' · unsaved edits' : '')),
      btn('Edit', () => openEditor({ project: pid, path: p.path })))))
}

function Proof({ api, pid, releaseId }) {
  const [state, setState] = useState(null)
  useEffect(() => { setState(null) }, [releaseId])
  const load = () => api('/proof', { project: pid, release_id: releaseId }).then(setState).catch(e => setState({ available: false, reason: String(e && e.message ? e.message : e), decks: [] }))
  if (!state) return h('div', { style: { margin: '6px 0' } }, btn('Show before and after', load))
  if (!state.available) return h('div', { style: { ...css.muted, margin: '6px 0' } }, state.reason)
  if (!state.decks.length) return h('div', { style: { ...css.muted, margin: '6px 0' } }, 'There are no slides to compare for this release.')
  return h('div', { role: 'region', 'aria-label': 'Before and after', style: { margin: '8px 0' } },
    state.decks.map(d => h('div', { key: d.deck }, h('div', { style: { fontWeight: 600, margin: '4px 0' } }, d.deck),
      d.slides.map(sl => h('div', { key: sl.slide, style: { display: 'flex', gap: 8, flexWrap: 'wrap', margin: '4px 0' } },
        h('figure', { style: { margin: 0, flex: '1 1 280px' } }, h('img', { alt: 'Slide ' + sl.slide + ' before', src: 'data:image/png;base64,' + sl.before, style: { width: '100%', border: '1px solid var(--ui-stroke-tertiary, #8884)' } }), h('figcaption', { style: css.muted }, 'Slide ' + sl.slide + ' now')),
        h('figure', { style: { margin: 0, flex: '1 1 280px' } }, h('img', { alt: 'Slide ' + sl.slide + ' after', src: 'data:image/png;base64,' + sl.after, style: { width: '100%', border: '1px solid var(--ui-accent, #3b82f6)' } }), h('figcaption', { style: css.muted }, 'Slide ' + sl.slide + ' after approval')))))))
}

const instrLabel = { authorised: 'authorised', pending: 'not yet authorised', changed: 'changed since you authorised it', too_large: 'too large to use' }

function Instructions({ api, pid, busy, run }) {
  const [info, setInfo] = useState(null)
  const [open, setOpen] = useState(null)
  const load = useCallback(() => pid ? api('/instructions', { project: pid }).then(setInfo).catch(() => setInfo(null)) : setInfo(null), [api, pid])
  useEffect(() => { setOpen(null); load() }, [load])
  if (!info || (!info.files.length && !info.proposals.length)) return null
  return h('section', { style: css.card, 'aria-label': 'Project instructions' },
    h('h2', { style: css.h2 }, 'Project instructions'),
    h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'The agent only sees an instruction file after you have read and authorised its exact text. Instructions are preferences: they can never change who approves, what needs approval, or the release rule.'),
    info.files.map(f => h('div', { key: f.name, style: { padding: '4px 0' } },
      h('div', { style: { ...css.row, justifyContent: 'space-between' } },
        h('span', { style: { fontSize: 13 } }, `${f.name} · ${instrLabel[f.state] || f.state}`),
        f.state === 'too_large' ? null : btn(open && open.name === f.name ? 'Hide' : 'Read', () => open && open.name === f.name ? setOpen(null) : run(async () => { setOpen(await api('/instruction-read', { project: pid, name: f.name })) })),
      ),
      open && open.name === f.name ? h('div', null,
        h('pre', { style: { whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto', fontSize: 12, margin: '6px 0' } }, open.text),
        f.state !== 'authorised' ? btn('Authorise this text', () => run(async () => { await api('/instruction-authorise', { project: pid, name: f.name, sha: open.sha }); setOpen(null); await load() }, () => `${f.name} authorised.`), { disabled: busy, primary: true }) : null) : null)),
    info.proposals.map(pr => h('div', { key: pr.proposal, style: { ...css.card, marginTop: 8 } },
      h('div', { style: { fontWeight: 600 } }, `Proposed change to ${pr.name}`),
      h('pre', { style: { whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto', fontSize: 12, margin: '6px 0' } }, pr.diff || '(no difference)'),
      pr.stale ? h('div', { style: css.muted }, 'The file changed since this was proposed. Ask for a new proposal.')
        : btn('Apply and authorise this text', () => run(async () => { await api('/instruction-apply', { project: pid, proposal: pr.proposal }); await load() }, () => 'Applied and authorised.'), { disabled: busy, primary: true }))))
}

function Room({ api, pid, busy, run }) {
  const [info, setInfo] = useState(null)
  const [kind, setKind] = useState('note')
  const [ref, setRef] = useState('')
  const [label, setLabel] = useState('')
  const load = useCallback(() => pid ? api('/room', { project: pid }).then(setInfo).catch(() => setInfo(null)) : setInfo(null), [api, pid])
  useEffect(() => { load() }, [load])
  if (!info) return null
  const when = (t) => new Date(t * 1000).toLocaleString()
  return h('section', { style: css.card, 'aria-label': 'Room' },
    h('h2', { style: css.h2 }, 'Room'),
    h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'What this project knows: the sources that belong to the job and what you have approved the agent to remember. The agent can add a source or suggest a memory; only you approve one.'),
    info.pending.length ? h('div', { style: { marginBottom: 8 } },
      h('div', { style: { fontWeight: 600, fontSize: 13 } }, `${info.pending.length} thing${info.pending.length === 1 ? '' : 's'} for you to decide`),
      info.pending.map(m => h('div', { key: m.id, style: { ...css.card, marginTop: 6 } },
        h('div', { style: { fontSize: 13 } }, m.text),
        h('div', { style: { ...css.muted, fontSize: 12 } }, `from: ${m.source}`),
        h('div', { style: { ...css.row, marginTop: 6 } },
          btn('Remember this', () => run(async () => { await api('/room-memory-decide', { project: pid, id: m.id, approve: true }); await load() }, () => 'Remembered.'), { disabled: busy, primary: true }),
          btn('Not this', () => run(async () => { await api('/room-memory-decide', { project: pid, id: m.id, approve: false }); await load() }, () => 'Rejected.'), { disabled: busy }))))) : null,
    info.memory.length ? h('div', { style: { marginBottom: 8 } }, h('div', { style: { fontWeight: 600, fontSize: 13 } }, `Remembered (${info.memory.length})`),
      info.memory.map(m => h('div', { key: m.id, style: { fontSize: 13, padding: '2px 0' } }, m.text, h('span', { style: { ...css.muted, fontSize: 12 } }, `  (${m.kind}, from: ${m.source})`)))) : null,
    h('div', { style: { fontWeight: 600, fontSize: 13 } }, `Sources (${info.sources.length})`),
    info.sources.length ? info.sources.map(sr => h('div', { key: sr.id, style: { ...css.row, justifyContent: 'space-between', padding: '3px 0' } },
      h('span', { style: { fontSize: 13 } }, `${sr.label} · ${sr.kind}${sr.present === false ? ' · missing' : ''} · added by ${sr.added_by}`),
      btn('Remove', () => run(async () => { await api('/room-source-remove', { project: pid, id: sr.id }); await load() }, () => 'Removed.'), { disabled: busy })))
      : h('div', { style: css.muted }, 'No sources yet. Add the files, links or notes this job depends on.'),
    h('div', { style: { ...css.row, marginTop: 6 } },
      h('select', { value: kind, onChange: e => setKind(e.target.value), 'aria-label': 'Source kind', style: { ...css.input, flex: 'none', minWidth: 90 } }, ['note', 'file', 'folder', 'url'].map(k => h('option', { key: k, value: k }, k))),
      h('input', { value: ref, onChange: e => setRef(e.target.value), placeholder: kind === 'note' ? 'Note text' : kind === 'url' ? 'https://' : 'Path inside the project', 'aria-label': 'Source reference', style: css.input }),
      h('input', { value: label, onChange: e => setLabel(e.target.value), placeholder: 'Label', 'aria-label': 'Source label', style: { ...css.input, flex: 'none', minWidth: 140, width: 160 } }),
      btn('Add', () => run(async () => { await api('/room-source-add', { project: pid, kind, ref, label }); setRef(''); setLabel(''); await load() }, () => 'Added.'), { disabled: busy || !ref.trim() })),
    (info.crew && info.crew.length) ? h('details', { style: { marginTop: 8 }, open: true }, h('summary', { style: css.muted }, `Helper agents (${info.crew.length})`),
      info.crew.map(c => h('div', { key: c.id, style: { fontSize: 12, margin: '4px 0' } },
        h('div', null, (c.role || 'helper') + ' · ' + c.status + (c.duration_ms ? ' · ' + Math.round(c.duration_ms / 1000) + ' s' : '')),
        c.goal ? h('div', { style: css.muted }, c.goal) : null,
        c.summary ? h('div', { style: css.muted }, c.summary) : null,
        c.files && c.files.length ? h('div', { style: css.muted }, 'Files: ' + c.files.join(', ')) : null))) : null,
    info.audit.length ? h('details', { style: { marginTop: 8 } }, h('summary', { style: css.muted }, `Recent activity (${info.audit.length})`),
      info.audit.slice().reverse().map(e => h('div', { key: e.id, style: { ...css.muted, fontSize: 12 } }, `${when(e.at)} · ${e.actor} · ${e.event.replace('_', ' ')}`))) : null)
}

function AgentChanges({ api, pid, busy, run }) {
  const [rows, setRows] = useState(null)
  const load = useCallback(() => pid ? api('/snapshots', { project: pid }).then(r => setRows(r.snapshots)).catch(() => setRows(null)) : setRows(null), [api, pid])
  useEffect(() => { load() }, [load])
  if (!rows || !rows.length) return null
  const when = (t) => new Date(t * 1000).toLocaleString()
  const word = { saved: 'changed', created: 'created', too_large: 'changed (too large to keep a copy)' }
  return h('section', { style: css.card, 'aria-label': 'Files the agent changed' },
    h('h2', { style: css.h2 }, 'Files the agent changed'),
    h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'A copy of each file is kept before the agent changes it. Restore puts it back and keeps what was there, so a restore can be undone. Changes made by commands that do not name their files are not covered.'),
    rows.slice(0, 15).map(r => h('div', { key: r.id, style: { ...css.row, justifyContent: 'space-between', padding: '3px 0' } },
      h('span', { style: { fontSize: 13 } }, `${r.path} · ${word[r.state] || r.state} · ${when(r.at)}${r.restored ? ' · restored' : ''}`),
      r.state === 'too_large' ? null : btn('Restore', () => run(async () => { await api('/snapshot-restore', { project: pid, id: r.id }); await load() }, () => 'Restored.'), { disabled: busy }))))
}

function Policy({ api, pid, busy, run }) {
  const [pol, setPol] = useState(null)
  const [text, setText] = useState('')
  const load = useCallback(() => pid ? api('/room-policy', { project: pid }).then(p => { setPol(p); setText(p.protected.join('\n')) }).catch(() => setPol(null)) : setPol(null), [api, pid])
  useEffect(() => { load() }, [load])
  if (!pol) return null
  const patterns = text.split('\n').map(x => x.trim()).filter(Boolean)
  return h('section', { style: css.card, 'aria-label': 'Protected files' },
    h('h2', { style: css.h2 }, 'Protected files'),
    h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'The agent cannot change these files (one pattern per line, inside this project, * allowed). Removing a folder, a wildcard or five or more files asks you first. These are checks on command text, not a sandbox.'),
    h('textarea', { value: text, onChange: e => setText(e.target.value), rows: 4, 'aria-label': 'Protected patterns', style: { ...css.input, width: '100%', fontFamily: 'monospace' } }),
    h('label', { style: { ...css.row, margin: '6px 0', fontSize: 13 } },
      h('input', { type: 'checkbox', checked: pol.confirm_delete, onChange: e => setPol({ ...pol, confirm_delete: e.target.checked }), 'aria-label': 'Ask before bulk removal' }), 'Ask me before the agent removes or moves many files'),
    btn('Save', () => run(async () => { await api('/room-policy-set', { project: pid, protected: patterns, confirm_delete: pol.confirm_delete }); await load() }, () => 'Saved.'), { disabled: busy, primary: true }))
}

const proofTone = { sourced: 'var(--ui-green, #16a34a)', calculated: 'var(--ui-accent, #3b82f6)', stated: '#7c3aed', candidate: 'var(--ui-amber, #d97706)', 'value only': 'var(--ui-amber, #d97706)', unsourced: 'var(--ui-red, #dc2626)' }
const proofWord = { sourced: 'supported by a source', calculated: 'calculation verified', stated: 'stated by you', candidate: 'possible source, not verified', 'value only': 'number found, not verified', unsourced: 'not verified' }

function ProofText({ text, figures, onPick }) {
  const parts = []
  let at = 0
  figures.slice().sort((a, b) => a.start - b.start).forEach((f, i) => {
    if (f.start < at || text.slice(f.start, f.end) !== f.raw) return
    parts.push(text.slice(at, f.start))
    parts.push(h('button', { key: i, onClick: () => onPick(f), title: proofWord[f.state], 'aria-label': `${f.raw}: ${proofWord[f.state]}`,
      style: { font: 'inherit', padding: '0 2px', margin: 0, border: 'none', borderBottom: `2px solid ${proofTone[f.state]}`, background: 'transparent', color: 'inherit', cursor: 'pointer' } }, f.raw))
    at = f.end
  })
  parts.push(text.slice(at))
  return h('pre', { style: { whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto', fontSize: 12, margin: '6px 0', padding: 8, border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 8 } }, parts)
}

function DeliverableView({ api, pid, item, busy, run, ctx, onChanged }) {
  const [shown, setShown] = useState(null)
  const [proof, setProof] = useState(null)
  const [picked, setPicked] = useState(null)
  useEffect(() => { setProof(null); setPicked(null); if (item.proof) api('/deliverable-proof', { project: pid, path: item.path }).then(setProof).catch(() => setProof(null)) }, [api, pid, item.path, item.proof && item.proof.at])
  const [cmp, setCmp] = useState(null)
  const [version, setVersion] = useState(0)
  const [page, setPage] = useState(1)
  useEffect(() => { setCmp(null); api('/deliverable-preview', { project: pid, path: item.path, version, page }).then(setShown).catch(e => setShown({ kind: 'none', why: String(e.message || e) })) }, [api, pid, item.path, version, page])
  const ask = () => {
    const text = `About ${item.path}${version ? ' (an earlier version)' : ''}: `
    run(async () => { const ok = await Promise.resolve(host.composer.insertText(null, text, { mode: 'block' })); if (!ok) throw new Error('Could not reach a chat. Open one and try again.') }, () => 'Added to the chat box.')
  }
  const when = (t) => new Date(t * 1000).toLocaleString()
  let body = null
  if (!shown) body = h('div', { style: css.muted }, 'Loading...')
  else if (shown.kind === 'slides') body = h('div', null,
    h('div', { style: { ...css.muted, fontSize: 12 } }, 'Drawn from where each shape sits, not typeset: fonts and line breaks are approximate. No Office program needed.' + (shown.marked ? ' Figures linked to a source are underlined in green (' + shown.marked + ').' : '')),
    shown.slides.map(sl => h('img', { key: sl.slide, alt: `Slide ${sl.slide}`, src: `data:image/svg+xml;utf8,${encodeURIComponent(sl.svg)}`, style: { width: '100%', margin: '6px 0', border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 6 } })))
  else if (shown.kind === 'blocks') body = h('div', { style: { maxHeight: 360, overflow: 'auto', margin: '6px 0' } },
    h('div', { style: { ...css.muted, fontSize: 12 } }, 'Structural view of the document: text and tables, not the page layout.'),
    shown.blocks.map((b, i) => b.type === 'table'
      ? h('table', { key: i, style: { borderCollapse: 'collapse', fontSize: 12, margin: '6px 0' } }, h('tbody', null, b.rows.map((r, ri) => h('tr', { key: ri }, r.map((c, ci) => h('td', { key: ci, style: { border: '1px solid var(--ui-stroke-secondary, #8884)', padding: '2px 6px' } }, c))))))
      : h(b.type === 'heading' ? 'h3' : 'p', { key: i, style: { margin: '6px 0', fontSize: b.type === 'heading' ? 14 : 13, fontWeight: b.type === 'heading' ? 600 : 400 } }, b.text)))
  else if (shown.kind === 'text' && !version && proof && proof.marks_align && proof.figures.length) body = h(ProofText, { text: shown.text, figures: proof.figures, onPick: setPicked })
  else if (shown.kind === 'text') body = h('pre', { style: { whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto', fontSize: 12, margin: '6px 0', padding: 8, border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 8 } }, shown.text + (shown.truncated ? '\n... (cut at 200 KB)' : ''))
  else if (shown.kind === 'image') body = h('div', null,
    h('img', { src: `data:${shown.mime};base64,${shown.data}`, alt: `${item.path}${shown.pages ? ` page ${shown.page}` : ''}`, style: { maxWidth: '100%', maxHeight: 480, border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 8 } }),
    shown.pages > 1 ? h('div', { style: { ...css.row, marginTop: 4 } }, btn('Previous page', () => setPage(Math.max(1, page - 1)), { disabled: page <= 1 }), h('span', { style: css.muted }, `page ${shown.page} of ${shown.pages}`), btn('Next page', () => setPage(Math.min(shown.pages, page + 1)), { disabled: page >= shown.pages })) : null)
  else if (shown.kind === 'grid') body = h('div', { style: { maxHeight: 320, overflow: 'auto', margin: '6px 0' } },
    h('div', { style: { ...css.muted, fontSize: 12 } }, `Sheet ${shown.sheet}${shown.sheets.length > 1 ? ` (of ${shown.sheets.length})` : ''}`),
    h('table', { style: { borderCollapse: 'collapse', fontSize: 12 } }, h('tbody', null, shown.rows.map((r, i) => h('tr', { key: i }, r.map((c, k) => h('td', { key: k, style: { border: '1px solid var(--ui-stroke-secondary, #8884)', padding: '2px 6px' } }, c)))))))
  else body = h('div', { style: css.muted }, shown.why || 'No preview.')
  return h('div', { style: { marginTop: 6 } },
    h('div', { style: css.row },
      version ? btn('Back to the file as it is now', () => { setVersion(0); setPage(1) }) : null,
      btn('Ask the agent about this', ask),
      item.exists && item.status !== 'approved' ? btn('Approve this version', () => run(async () => { await api('/deliverable-approve', { project: pid, path: item.path }); onChanged() }, () => `${item.path} approved.`), { disabled: busy, primary: true }) : null),
    proof && proof.summary ? h('div', { style: { ...css.row, fontSize: 12, marginTop: 6 } },
      ['sourced', 'calculated', 'stated', 'candidate', 'value_only', 'unsourced'].filter(k => proof.summary[k]).map(k => h('span', { key: k, style: { color: proofTone[k.replace('_', ' ')] } }, `${proof.summary[k]} ${proofWord[k.replace('_', ' ')]}`))) : null,
    picked ? h('div', { role: 'status', style: { ...css.card, marginTop: 6, borderColor: proofTone[picked.state] } },
      h('div', { style: { fontWeight: 600 } }, `${picked.raw}: ${proofWord[picked.state]}`),
      picked.ref ? h('div', { style: { ...css.muted, fontSize: 12 } }, `from ${picked.tool} ${picked.ref}`) : h('div', { style: { ...css.muted, fontSize: 12 } }, 'Not verified: nothing the agent read in that session supports this figure.'),
      picked.how ? h('div', { style: { fontSize: 12 } }, picked.how) : null,
      picked.excerpt ? h('div', { style: { fontSize: 12, fontFamily: 'monospace', marginTop: 4 } }, picked.excerpt) : null) : null,
    shown && shown.review_room ? h('div', { style: { ...css.muted, fontSize: 12, marginTop: 4 } }, 'This is the text of the document. Review the documents below draws it as Office does.') : null,
    body,
    item.versions.length ? h('div', { style: { marginTop: 6 } },
      h('div', { style: { fontWeight: 600, fontSize: 12 } }, 'Earlier versions'),
      item.versions.slice().reverse().map(v => h('div', { key: v.id, style: { ...css.row, padding: '2px 0', fontSize: 12 } },
        h('span', null, `before the ${v.tool} at ${when(v.at)}`),
        btn('See it', () => { setVersion(v.id); setPage(1) }),
        btn('Compare with now', () => run(async () => setCmp(await api('/deliverable-diff', { project: pid, path: item.path, version: v.id })))))),
      cmp ? (cmp.kind === 'text' ? h('div', null, h('div', { style: { ...css.muted, fontSize: 12 } }, cmp.same ? 'No difference in the text.' : `${cmp.added} line${cmp.added === 1 ? '' : 's'} added, ${cmp.removed} removed`),
        h('pre', { style: { whiteSpace: 'pre-wrap', maxHeight: 280, overflow: 'auto', fontSize: 12 } }, cmp.diff.split('\n').map((ln, i) => h('div', { key: i, style: { color: ln.startsWith('+') && !ln.startsWith('+++') ? 'var(--ui-green, #16a34a)' : ln.startsWith('-') && !ln.startsWith('---') ? 'var(--ui-red, #dc2626)' : 'inherit' } }, ln || ' '))))
        : h('div', { style: css.muted }, cmp.why)) : null) : null)
}

function Deliverables({ api, pid, busy, run, ctx, empty = false }) {
  const [items, setItems] = useState(null)
  const [open, setOpen] = useState(null)
  const [view, setView] = useState('list')
  const load = useCallback(() => pid ? api('/deliverables', { project: pid }).then(r => setItems(r.items)).catch(() => setItems(null)) : setItems(null), [api, pid])
  useEffect(() => { setOpen(null); load() }, [load])
  if (items && !items.length && empty) return h(EmptyState, { title: 'Nothing made yet', description: 'Files the agent makes or changes in this folder appear here, with their earlier versions and an approve button.' })
  if (!items || !items.length) return null
  const tone = { approved: 'var(--ui-green, #16a34a)', 'changed since approval': 'var(--ui-amber, #d97706)', 'not reviewed': 'var(--ui-text-tertiary, #888)', missing: 'var(--ui-red, #dc2626)' }
  const waiting = items.filter(i => i.status === 'not reviewed' || i.status === 'changed since approval').length
  const gallery = view === 'gallery'
  return h('section', { style: css.card, 'aria-label': 'Deliverables' },
    h('div', { style: { ...css.row, justifyContent: 'space-between' } },
      h('h2', { style: css.h2 }, `Deliverables${waiting ? ` · ${waiting} to review` : ''}`),
      h('div', { role: 'group', 'aria-label': 'View', style: css.row }, btn('List', () => setView('list'), { disabled: !gallery, name: 'List view' }), btn('Gallery', () => setView('gallery'), { disabled: gallery, name: 'Gallery view' }))),
    gallery ? h(DeliverableGallery, { api, pid, items, onOpen: (p) => { setView('list'); setOpen(p) } }) : null,
    gallery ? null : h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'Every file the agent made or changed in this project. Look at it, compare it with the version before, ask about it, and approve the exact version you accept.'),
    gallery ? null : items.map(it => h('div', { key: it.path, style: { borderTop: '1px solid var(--ui-stroke-secondary, #8883)', padding: '6px 0' } },
      h('div', { style: { ...css.row, justifyContent: 'space-between' } },
        h('span', { style: { fontSize: 13 } }, `${it.path} · ${it.kind}${it.versions.length ? ` · ${it.versions.length} earlier version${it.versions.length === 1 ? '' : 's'}` : ''} · `, h('span', { style: { color: tone[it.status] || 'inherit' } }, it.status),
          it.proof && it.proof.figures ? h('span', { style: { marginLeft: 8, color: it.proof.unsourced ? 'var(--ui-red, #dc2626)' : 'var(--ui-green, #16a34a)' } }, `· ${it.proof.sourced + it.proof.calculated + it.proof.stated} of ${it.proof.figures} figures supported${it.proof.stale ? ' (changed since)' : ''}`) : null),
        btn(open === it.path ? 'Hide' : 'Open', () => setOpen(open === it.path ? null : it.path))),
      open === it.path ? h(DeliverableView, { api, pid, item: it, busy, run, ctx, onChanged: load }) : null)))
}

function DeliverableGallery({ api, pid, items, onOpen }) {
  const [cards, setCards] = useState(null)
  useEffect(() => { api('/deliverable-cards', { project: pid, path: '' }).then(r => setCards(r.cards)).catch(() => setCards([])) }, [api, pid, items])
  if (!cards) return h('div', { style: css.muted }, 'Drawing the cards...')
  const tone = { approved: 'var(--ui-green, #16a34a)', 'changed since approval': 'var(--ui-amber, #d97706)', missing: 'var(--ui-red, #dc2626)' }
  return h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10, marginTop: 6 }, role: 'list', 'aria-label': 'Deliverables as cards' }, cards.map(c => h('div', { key: c.path, role: 'listitem', style: { border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 8, overflow: 'hidden', display: 'flex', flexDirection: 'column' } },
    h('div', { style: { height: 96, background: 'var(--ui-bg-secondary, #8881)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' } },
      !c.thumb ? h('span', { style: { ...css.muted, fontSize: 11 } }, c.kind)
        : c.thumb.type === 'svg' ? h('img', { alt: `First slide of ${c.path}`, src: `data:image/svg+xml;utf8,${encodeURIComponent(c.thumb.svg)}`, style: { width: '100%', height: '100%', objectFit: 'contain' } })
        : c.thumb.type === 'image' ? h('img', { alt: c.path, src: `data:${c.thumb.mime};base64,${c.thumb.data}`, style: { width: '100%', height: '100%', objectFit: 'cover' } })
        : h('pre', { style: { margin: 0, padding: 6, fontSize: 9, lineHeight: 1.3, whiteSpace: 'pre-wrap', width: '100%', alignSelf: 'flex-start', overflow: 'hidden' } }, c.thumb.text)),
    h('div', { style: { padding: 6, fontSize: 12 } }, h('div', { style: { fontWeight: 600, overflowWrap: 'anywhere' } }, c.path), h('div', { style: { color: tone[c.status] || 'inherit', fontSize: 11 } }, c.status), btn('Open', () => onOpen(c.path), { name: `Open ${c.path}` })))))
}

function NeedsYou({ api, pid, setPid, refreshKey }) {
  const [att, setAtt] = useState(null)
  useEffect(() => { api('/attention', {}).then(setAtt).catch(() => setAtt(null)) }, [api, pid, refreshKey])
  if (!att) return null
  const label = { release: ['release', 'releases'], memory: ['memory to decide', 'memories to decide'], deliverable: ['deliverable', 'deliverables'], instruction: ['instruction change', 'instruction changes'], recipe: ['recipe', 'recipes'], links: ['link question', 'link questions'], columns: ['column question', 'column questions'] }
  const parts = Object.entries(att.counts).map(([k, n]) => `${n} ${(label[k] || [k, k])[n === 1 ? 0 : 1]}`)
  return h('section', { style: { ...css.card, borderColor: att.total ? 'var(--ui-accent, #3b82f6)' : undefined }, 'aria-label': 'Needs you' },
    h('h2', { style: css.h2 }, att.total ? `Needs you · ${att.total}` : 'Nothing needs you'),
    att.total ? h('div', { style: { ...css.muted, fontSize: 12, marginBottom: 6 } }, parts.join(' · ')) : h('div', { style: { ...css.muted, fontSize: 12 } }, 'No release, memory, deliverable or question is waiting in any project.'),
    [...att.items.filter(i => i.project === pid), ...att.items.filter(i => i.project !== pid)].slice(0, 12).map((it, i) => h('div', { key: i, style: { ...css.row, justifyContent: 'space-between', padding: '3px 0', borderTop: i ? '1px solid var(--ui-stroke-secondary, #8883)' : 'none' } },
      h('span', { style: { fontSize: 13 } }, h('span', { style: css.chip }, it.name), ' ', it.title),
      it.kind === 'bypass' ? btn('I have seen this', () => api('/tripwire-dismiss', { project: it.project }).then(() => api('/attention', {}).then(setAtt)), { name: 'Dismiss the direct-change notice' })
        : it.project !== pid ? btn('Go to project', () => setPid(it.project)) : h('span', { style: { ...css.muted, fontSize: 12 } }, 'in this project, below'))),
    att.items.length > 12 ? h('div', { style: { ...css.muted, fontSize: 12 } }, `and ${att.items.length - 12} more`) : null,
    att.folders_missing && att.folders_missing.length ? h('div', { style: { ...css.muted, fontSize: 12, marginTop: 6 } }, `${att.folders_missing.length} project${att.folders_missing.length === 1 ? '' : 's'} not shown: the folder was moved or deleted.`) : null,
    att.could_not_check.length ? h('div', { role: 'alert', style: { color: 'var(--ui-amber, #d97706)', fontSize: 12, marginTop: 6 } }, `${att.could_not_check.length} part${att.could_not_check.length === 1 ? '' : 's'} could not be checked: ${att.could_not_check.map(f => `${f.part} (${f.error})`).join('; ').slice(0, 300)}`) : null)
}


const inside = (folder, cwd) => {
  if (!folder || !cwd) return false
  const norm = (p) => p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
  const f = norm(folder), c = norm(cwd)
  return c === f || c.startsWith(f + '/')
}

function useAttention(api, everyMs) {
  const [att, setAtt] = useState(null)
  const [tick, setTick] = useState(0)
  useEffect(() => { let live = true; api('/attention', {}).then(a => { if (live) setAtt(a) }).catch(() => {}); return () => { live = false } }, [api, tick])
  useEffect(() => { const t = setInterval(() => setTick(x => x + 1), everyMs); return () => clearInterval(t) }, [everyMs])
  return [att, () => setTick(x => x + 1)]
}

// The pane beside the chat: it follows the folder of the chat you are in, shows what needs you, what the agent made, and what the project knows.
function SidePane({ ctx }) {
  const api = useCallback((path, body) => ctx.rest(path, body === undefined ? undefined : { method: 'POST', body }), [ctx])
  const cwd = useValue(host.state.cwd)
  const [projects, setProjects] = useState(null)
  const [tab, setTab] = useState('needs')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [att, refresh] = useAttention(api, 30000)
  useEffect(() => { api('/projects').then(setProjects).catch(() => setProjects([])) }, [api, cwd])
  const run = useCallback(async (fn, okText) => {
    setBusy(true); setMessage(null)
    try { const out = await fn(); if (okText) setMessage({ kind: 'ok', text: okText(out) }); refresh(); return out }
    catch (err) { setMessage({ kind: 'error', text: String(err && err.message ? err.message : err) }); return null }
    finally { setBusy(false) }
  }, [refresh])
  const project = (projects || []).filter(p => inside(p.folder, cwd)).sort((a, b) => b.folder.length - a.folder.length)[0] || null
  const pid = project ? project.project : null
  const mine = att ? att.items.filter(i => i.project === pid) : []
  const openFull = () => { if (host.undismissPane) host.undismissPane('workroom:page'); if (host.revealPane) host.revealPane('workroom:page') }
  if (projects && !project) {
    return h('div', { style: { ...css.page, gap: 10 } },
      h(EmptyState, { title: 'This chat is not in a Workroom project', description: cwd ? `The chat works in ${cwd}. Add that folder as a project to keep its sources, deliverables and approvals here.` : 'Open a chat in a project folder.' }),
      cwd ? btn('Add this folder as a project', () => run(async () => { await api('/projects', { folder: cwd }); setProjects(await api('/projects')) }, () => 'Project added.'), { primary: true, disabled: busy }) : null,
      btn('Open the full Workroom page', openFull),
      att && att.total ? h('div', { style: { ...css.muted, fontSize: 12 } }, `${att.total} thing${att.total === 1 ? '' : 's'} wait for you in other projects.`) : null)
  }
  if (!project) return h('div', { style: css.page }, h('div', { style: css.muted }, 'Loading...'))
  const count = (n) => n ? h(Badge, { variant: 'secondary', style: { marginLeft: 6 } }, String(n)) : null
  return h('div', { style: { ...css.page, gap: 10, padding: 12 }, 'aria-busy': busy },
    h('div', { style: { ...css.row, justifyContent: 'space-between' } },
      h('div', null, h('div', { style: { fontWeight: 600 } }, project.folder.split(/[\\/]/).pop()), h('div', { style: { ...css.muted, fontSize: 11 } }, project.folder)),
      btn('Full page', openFull)),
    message ? h(Banner, { kind: message.kind }, message.text) : null,
    h(Tabs, { value: tab, onValueChange: setTab },
      h(TabsList, null,
        h(TabsTrigger, { value: 'needs' }, 'Needs you', count(mine.length)),
        h(TabsTrigger, { value: 'made' }, 'Made'),
        h(TabsTrigger, { value: 'room' }, 'Room'),
        h(TabsTrigger, { value: 'rules' }, 'Rules'))),
    tab === 'needs' ? (mine.length
      ? h('div', null, mine.map((it, i) => h('div', { key: i, style: { padding: '6px 0', borderTop: i ? '1px solid var(--ui-stroke-secondary, #8883)' : 'none', fontSize: 13 } }, it.title)),
          h('div', { style: { ...css.muted, fontSize: 12, marginTop: 6 } }, 'Each one is settled in its own tab here or on the full page.'))
      : h(EmptyState, { title: 'Nothing needs you in this project', description: att && att.total ? `${att.total} item${att.total === 1 ? '' : 's'} wait in other projects.` : 'No release, memory, deliverable or question is waiting.' })) : null,
    tab === 'made' ? h('div', null, h(Deliverables, { api, pid, busy, run, ctx, empty: true }), h(AgentChanges, { api, pid, busy, run })) : null,
    tab === 'room' ? h(Room, { api, pid, busy, run }) : null,
    tab === 'rules' ? h('div', null, h(Policy, { api, pid, busy, run }), h(Instructions, { api, pid, busy, run })) : null)
}

function NeedsStatus({ ctx }) {
  const api = useCallback((path, body) => ctx.rest(path, body === undefined ? undefined : { method: 'POST', body }), [ctx])
  const [att] = useAttention(api, 60000)
  if (!att) return null
  const open = () => { if (host.undismissPane) host.undismissPane('workroom:room'); if (host.revealPane) host.revealPane('workroom:room') }
  return h('button', { onClick: open, title: att.total ? Object.entries(att.counts).map(([k, n]) => `${n} ${k}`).join(', ') : 'Nothing waits for you', 'aria-label': `Workroom: ${att.total} need you`,
    style: { background: 'transparent', border: 'none', color: att.total ? 'var(--ui-accent, #3b82f6)' : 'var(--ui-text-tertiary, #888)', font: 'inherit', fontSize: 11, cursor: 'pointer', padding: '0 6px' } },
    att.total ? `Workroom · ${att.total} need you` : 'Workroom')
}

const stateLabel = { accepted: 'linked automatically', confirmed: 'linked by you', confirm: 'needs you', skipped: 'left alone', held: 'you changed it by hand' }

function Why({ info, onClose }) {
  const src = info.source
  return h('div', { role: 'region', 'aria-label': 'Where this number came from', style: { ...css.card, marginTop: 8, borderColor: 'var(--ui-accent, #3b82f6)' } },
    h('div', { style: { ...css.row, justifyContent: 'space-between' } },
      h('div', { style: { fontWeight: 600 } }, `Where "${info.text}" comes from`),
      btn('Close', onClose)),
    h('p', { style: { margin: '6px 0' } }, `${src.file}, sheet ${src.sheet}, cell ${src.cell} (${[...src.row, ...src.column].join(' · ') || 'no labels found'}).`),
    h('p', { style: { margin: '6px 0' } }, `Value now: ${src.value_now}. At the last release: ${src.value_at_last_release}.${info.source_changed_since_last_release ? ' The source has changed since then.' : ''}${src.formula ? ' The cell is calculated by a formula.' : ''}`),
    h('p', { style: { margin: '6px 0', ...css.muted } }, info.how),
    h('p', { style: { margin: '6px 0', ...css.muted } }, info.if_source_changes))
}

function Links({ ties, onConfirm, onSkip, onWhy, why, busy }) {
  const need = ties.filter(t => t.state === 'confirm' && !t.coincidence)
  const chance = ties.filter(t => t.state === 'confirm' && t.coincidence)
  const done = ties.filter(t => t.state === 'accepted' || t.state === 'confirmed')
  return h('div', { style: { marginTop: 10 } },
    need.length ? h('div', null,
      h('div', { style: { fontWeight: 600, margin: '0 0 6px' } }, `${need.length} number${need.length === 1 ? '' : 's'} need${need.length === 1 ? 's' : ''} you`),
      need.map(t => h('div', { key: t.id, style: { ...css.card, marginBottom: 6 } },
        h('div', null, `“${t.sentence || t.text}”`),
        h('div', { style: { ...css.muted, margin: '2px 0 8px' } }, `Slide ${t.slide} of ${t.deck}. Is ${t.text} the figure from ${t.source}?`),
        t.note ? h('div', { role: 'status', style: { fontSize: 12, margin: '0 0 8px', color: 'var(--ui-amber, #d97706)' } }, `Why you are asked again: ${t.note}`) : null,
        h('div', { style: css.row },
          btn('Yes, that is the source', () => onConfirm(t.id), { disabled: busy, primary: true }),
          btn('No, leave it alone', () => onSkip(t.id), { disabled: busy }),
          btn('Where could it come from?', () => onWhy(t.id), { disabled: busy }))))) : null,
    chance.length ? h('details', { style: { marginTop: 8 } },
      h('summary', { style: { cursor: 'pointer' } }, `${chance.length} short number${chance.length === 1 ? '' : 's'} equal to a cell by chance, not asked about`),
      h('div', { style: { ...css.muted, fontSize: 12, margin: '6px 0' } }, 'Nothing in the text names these cells and the numbers are short enough to match any cell. They are left unlinked unless you say otherwise.'),
      h('ul', { style: { listStyle: 'none', margin: '6px 0 0', padding: 0 } }, chance.map(t => h('li', { key: t.id, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0', borderTop: '1px solid var(--ui-stroke-tertiary, #8883)' } },
        h('span', null, h('strong', null, t.text), h('span', { style: css.muted }, `  ${t.sentence || ''} (${t.source})`)),
        h('span', { style: css.row }, btn('It is this cell', () => onConfirm(t.id), { disabled: busy, name: `Link ${t.text} to ${t.source}` }), btn('Leave it', () => onSkip(t.id), { disabled: busy })))))) : null,
    done.length ? h('details', { style: { marginTop: 8 } },
      h('summary', { style: { cursor: 'pointer' } }, `${done.length} linked number${done.length === 1 ? '' : 's'}`),
      h('ul', { style: { listStyle: 'none', margin: '6px 0 0', padding: 0 } }, done.map(t => h('li', { key: t.id, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0', borderTop: '1px solid var(--ui-stroke-tertiary, #8883)' } },
        h('span', null, h('strong', null, t.text), h('span', { style: css.muted }, `  ${t.sentence || ''}`)),
        btn('Why?', () => onWhy(t.id), { disabled: busy, name: `Why is ${t.text} linked?` }))))) : null,
    why ? h(Why, { info: why.info, onClose: why.close }) : null)
}

const SEVERITY = { high: 'Read first', medium: 'Look', info: 'Note' }

// Sentences an update has made false, and what could not be checked. Dismiss means: this is not a problem here, do not raise it again.
function Flags({ flags, coverage, onDismiss, busy, compact }) {
  const important = (flags || []).filter(f => f.severity !== 'info' && f.decision !== 'dismissed')
  const noted = (flags || []).filter(f => f.severity === 'info' && f.decision !== 'dismissed')
  const cov = coverage || {}
  return h('div', { role: 'region', 'aria-label': 'Sentences to read', style: { marginTop: 12 } },
    h('div', { style: { fontWeight: 600, marginBottom: 4 } }, important.length ? `${important.length} sentence${important.length === 1 ? '' : 's'} to read before you approve` : 'No sentence is made false by this update'),
    important.map(f => h('div', { key: f.id, style: { ...css.card, marginBottom: 6, borderColor: f.severity === 'high' ? 'var(--ui-red, #dc2626)' : 'var(--ui-amber, #d97706)' } },
      h('div', { style: css.row }, h('span', { style: { ...css.chip, borderColor: f.severity === 'high' ? 'var(--ui-red, #dc2626)' : 'var(--ui-amber, #d97706)' } }, SEVERITY[f.severity]), h('strong', null, f.summary)),
      compact ? null : h('div', { style: { margin: '4px 0', fontSize: 13 } }, h('span', { style: css.muted }, 'It will read: '), f.sentence_after),
      compact ? null : (f.evidence || []).map((e, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, e)),
      compact || !f.suggestion ? null : h('div', { style: { ...css.muted, fontSize: 12, marginTop: 2 } }, f.suggestion),
      h('div', { style: { ...css.row, marginTop: 6, justifyContent: 'space-between' } },
        h('span', { style: { ...css.muted, fontSize: 12 } }, f.where || ''),
        onDismiss ? btn('Dismiss', () => onDismiss(f.id), { disabled: busy, name: 'Dismiss: this is not a problem here' }) : null))),
    noted.length ? h('details', { style: { marginTop: 4 } }, h('summary', { style: css.muted }, `${noted.length} more note${noted.length === 1 ? '' : 's'}`),
      noted.map(f => h('div', { key: f.id, style: { ...css.muted, fontSize: 12, padding: '2px 0' } }, `${f.summary}. ${f.sentence_after}`))) : null,
    cov.sentences_checked !== undefined ? h('details', { style: { marginTop: 6 } },
      h('summary', { style: css.muted }, `Checked ${cov.sentences_checked} sentence${cov.sentences_checked === 1 ? '' : 's'}, read ${cov.claims_read} claim${cov.claims_read === 1 ? '' : 's'}${cov.not_checked_count ? `, ${cov.not_checked_count} could not be checked` : ''}`),
      h('div', { style: { ...css.muted, fontSize: 12 } }, 'Workroom reads claims of the kind "up from", "grew from X to Y", "exceeded", "record" and "grew to". It does not guess at any other wording.'),
      (cov.not_checked || []).map((n, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, n))) : null)
}

// Numbers in the documents that a calculation over linked cells reproduces. Accepting one makes it follow its sources like any other tie.
function Calculations({ api, pid, busy, run }) {
  const [info, setInfo] = useState(null)
  const find = () => run(async () => { const r = await api('/calculations', { project: pid }); setInfo(r); return r })
  const act = (route, body, okText) => run(async () => { await api(route, { project: pid, ...body }); setInfo(await api('/calculations', { project: pid })) }, () => okText)
  const certain = info ? info.candidates.filter(c => c.certainty === 'certain') : []
  return h('div', { style: { marginTop: 12 } },
    btn('Find calculated numbers', find, { disabled: busy }),
    h('span', { style: { ...css.muted, marginLeft: 8, fontSize: 12 } }, 'A percent change, a margin, a difference or a total that the sources reproduce. Nothing is written.'),
    info ? h('div', { role: 'region', 'aria-label': 'Calculated numbers', style: { marginTop: 8 } },
      info.candidates.length ? null : h('div', { style: css.muted }, 'No other number in your documents is reproduced by a calculation over the cells they are tied to.'),
      certain.length > 1 ? h('div', { style: { margin: '0 0 6px' } }, btn(`Accept the ${certain.length} that are certain`, () => act('/calculations-accept-certain', {}, `${certain.length} calculations will now follow their sources.`), { disabled: busy, primary: true })) : null,
      info.candidates.map(c => h('div', { key: c.id, style: { ...css.card, marginBottom: 6 } },
        h('div', { style: css.row }, h('strong', null, c.figure), h('span', { style: css.muted }, `${c.deck}, ${c.where}`), h('span', { style: { ...css.chip, borderColor: c.certainty === 'certain' ? 'var(--ui-green, #16a34a)' : 'var(--ui-amber, #d97706)' } }, c.certainty === 'certain' ? 'certain' : 'choose')),
        h('div', { style: { ...css.muted, fontSize: 12, margin: '2px 0' } }, c.sentence),
        c.options.map((o, i) => h('div', { key: i, style: { ...css.row, justifyContent: 'space-between', padding: '2px 0' } },
          h('span', { style: { fontSize: 12 } }, h('span', null, o.words), h('br'), h('span', { style: css.muted }, o.values)),
          btn(c.options.length > 1 ? 'Use this one' : 'Accept', () => act('/calculation-accept', { candidate: c.id, option: i }, 'That calculation will now follow its sources.'), { disabled: busy }))),
        h('div', { style: { ...css.row, justifyContent: 'space-between' } },
          h('span', { style: { ...css.muted, fontSize: 12 } }, c.reason),
          btn('Not a calculation', () => act('/calculation-dismiss', { candidate: c.id }, 'Dismissed. It will not be offered again.'), { disabled: busy })))),
      info.unexplained_count ? h('details', null, h('summary', { style: css.muted }, `${info.unexplained_count} percentage${info.unexplained_count === 1 ? '' : 's'} no calculation reproduces`),
        info.unexplained.map((u, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, `${u.figure} on slide ${u.slide} of ${u.deck}: ${u.sentence}`))) : null) : null)
}

const STATE_TEXT = {
  awaiting_approval: 'Waiting for your approval',
  published: 'Published',
  blocked: 'Blocked',
  stale: 'Not published: a file changed after this was prepared',
  expired: 'Expired',
  rolled_back: 'Rolled back',
  preparing: 'Preparing'
}

// A directive's attributes come from the model, so they are only used as ids to look up what the backend knows.
function ReleaseCard({ ctx, attrs }) {
  const valid = /^[0-9a-f]{12}$/.test(attrs.project || '') && /^[0-9a-f]{16}$/.test(attrs.release || '')
  const [view, setView] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [ack, setAck] = useState(false)
  const load = useCallback(
    () => ctx.rest('/release', { method: 'POST', body: { project: attrs.project, release_id: attrs.release } }).then(setView).catch(e => setError(String(e && e.message ? e.message : e))),
    [ctx, attrs.project, attrs.release]
  )
  useEffect(() => { if (valid) load() }, [valid, load])
  if (!valid) return null
  const approve = async () => {
    setBusy(true)
    try {
      await ctx.rest('/approve', { method: 'POST', body: { project: attrs.project, release_id: attrs.release, digest: view.digest, acknowledge: ack } })
      await load()
    } catch (e) {
      setError(String(e && e.message ? e.message : e))
    } finally {
      setBusy(false)
    }
  }
  const shown = view ? view.changes.slice(0, 5) : []
  const stateColor = view && (view.state === 'published' ? 'var(--ui-green, #16a34a)' : view.state === 'awaiting_approval' ? 'var(--ui-accent, #3b82f6)' : 'var(--ui-red, #dc2626)')
  return h('div', { role: 'group', 'aria-label': 'Workroom release', style: { ...css.card, maxWidth: 640, margin: '8px 0' } },
    h('div', { style: { ...css.row, justifyContent: 'space-between' } },
      h('strong', null, 'Workroom release'),
      view ? h('span', { style: { ...css.chip, borderColor: stateColor } }, STATE_TEXT[view.state] || view.state) : null),
    error ? h('div', { role: 'alert', style: { color: 'var(--ui-red, #dc2626)', margin: '6px 0' } }, error) : null,
    !view && !error ? h('div', { style: css.muted }, 'Loading') : null,
    view ? h('div', null,
      view.edited_page ? h('p', { style: { margin: '6px 0' } }, view.state === 'published' ? `Edits to ${view.changes[0].deck} were written.` : `Your edits to ${view.changes[0].deck} would be written. Nothing has changed yet.`)
      : view.created ? h('div', null,
        h('p', { style: { margin: '6px 0' } }, view.state === 'published'
          ? `Created ${view.changes[0].deck}. Every figure in it is linked to its source.`
          : `Workroom would create ${view.changes[0].deck}, with ${view.figures.length} figures each linked to its source cell. Nothing has been written yet.`),
        h('ul', { style: { margin: '4px 0', paddingLeft: 18 } }, groupFigures(view.figures).slice(0, 8).map((f, i) => h('li', { key: i },
          h('strong', null, f.text), h('span', { style: css.muted }, ` ${f.concept || ''} ${f.period || ''} · ${f.source}${f.count > 1 ? ` · in ${f.count} places` : ''}`)))),
        view.figures.length > 8 ? h('div', { style: css.muted }, `and ${view.figures.length - 8} more figures`) : null)
      : view.rolled ? h('p', { style: { margin: '6px 0' } }, view.state === 'published'
        ? `Rolled forward: ${view.rolled.figures} figures now show the next period and ${view.rolled.period_words} period words advanced. Restore undoes the whole roll.`
        : `Roll forward: ${view.rolled.figures} figures move to the next period and ${view.rolled.period_words} period words advance (${view.rolled.example}). Nothing has been changed yet; Restore undoes the whole roll.`)
      : h('p', { style: { margin: '6px 0' } }, view.state === 'published'
        ? `${view.changes.length} number${view.changes.length === 1 ? '' : 's'} updated. A backup of each replaced file is kept.`
        : `${view.changes.length} number${view.changes.length === 1 ? '' : 's'} would change. Nothing has been changed yet.`),
      view.created || view.edited_page ? null : shown.map((c, i) => h('div', { key: i, style: { display: 'flex', gap: 8, padding: '2px 0' } },
        h('span', { style: { ...css.muted, textDecoration: view.state === 'published' ? 'none' : 'line-through', minWidth: 70 } }, c.old_text),
        h('span', null, '\u2192'),
        h('strong', null, c.new_text),
        h('span', { style: css.muted }, `${c.deck}, ${c.where || 'slide ' + c.slide}`))),
      !view.created && !view.edited_page && view.changes.length > shown.length ? h('div', { style: css.muted }, `and ${view.changes.length - shown.length} more`) : null,
      view.held && view.held.length ? h('div', { style: { ...css.muted, marginTop: 6 } }, `${view.held.length} held for you`) : null,
      view.findings && view.findings.length ? h('ul', null, view.findings.map((f, i) => h('li', { key: i }, f))) : null,
      view.state === 'awaiting_approval' && view.flags && view.flags.length ? h(Flags, { flags: view.flags, coverage: view.coverage, busy }) : null,
      view.state === 'awaiting_approval' && view.needs_acknowledgement && view.needs_acknowledgement.length ? h('label', { style: { ...css.row, margin: '8px 0 0', fontSize: 13 } },
        h('input', { type: 'checkbox', checked: ack, onChange: e => setAck(e.target.checked), 'aria-label': 'I have read the flagged sentences' }),
        h('span', null, 'I have read the sentences above and still want to release.')) : null,
      view.state === 'awaiting_approval' ? h('div', { style: { ...css.row, marginTop: 10 } },
        btn('Approve and publish', approve, { disabled: busy || (view.needs_acknowledgement && view.needs_acknowledgement.length > 0 && !ack), primary: true }),
        h('span', { style: { ...css.muted, fontSize: 11 } }, `Applies to exactly this release (${view.digest.slice(0, 12)}).`)) : null) : null)
}

const MARKS = {
  changes: { color: '#2563eb', name: 'changes' },
  linked: { color: '#16a34a', name: 'linked' },
  protected: { color: '#d97706', name: 'your edit, protected' },
  asked: { color: '#9333ea', name: 'needs you' },
  blocked: { color: '#dc2626', name: 'blocked' }
}

function markLabel(m, side) {
  if (m.kind === 'changes') return side === 'after' ? `${m.text}, changed from ${m.old_text || 'the old figure'}` : `${m.text}, will change to ${m.new_text}`
  return `${m.text}, ${MARKS[m.kind] ? MARKS[m.kind].name : m.kind}`
}

function ReviewRoom({ api, pid }) {
  const [over, setOver] = useState(null)
  const [deck, setDeck] = useState('')
  const [side, setSide] = useState('before')
  const [pages, setPages] = useState(null)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [structural, setStructural] = useState(null)
  const [sel, setSel] = useState(null)
  const [why, setWhy] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [shown, setShown] = useState({ changes: true, linked: true, protected: true, asked: true, blocked: true })
  const failed = (err) => { setError(String(err && err.message ? err.message : err)); setBusy(false) }

  const open = () => {
    setBusy(true); setError(null)
    api('/review', { project: pid }).then(o => {
      setOver(o); setBusy(false)
      const first = o.documents.find(d => d.counts.changes) || o.documents[0]
      if (first) setDeck(first.deck)
    }).catch(failed)
  }

  useEffect(() => { setOver(null); setDeck(''); setPages(null); setData(null); setStructural(null); setSel(null); setWhy(null) }, [pid])

  useEffect(() => {
    if (!deck || !over) return
    const doc = over.documents.find(d => d.deck === deck)
    setPages(null); setData(null); setStructural(null); setSel(null); setWhy(null); setError(null)
    if (!doc) return
    setBusy(true)
    if (!doc.can_draw) { api('/review-structural', { project: pid, deck }).then(s => { setStructural(s); setBusy(false) }).catch(failed); return }
    api('/review-pages', { project: pid, deck }).then(p => {
      setPages(p)
      const first = p.pages && p.pages.length ? (p.pages.find(x => x.marks.changes) || p.pages[0]).page : 1
      setPage(first); setSide(doc.changes_in_plan ? 'after' : 'before')
      if (!p.drawn) setBusy(false)
    }).catch(failed)
  }, [deck, over])

  useEffect(() => {
    if (!pages || !pages.drawn || !deck) return
    setBusy(true); setSel(null); setWhy(null)
    api('/review-page', { project: pid, deck, side, page }).then(d => { setData(d); setBusy(false) }).catch(failed)
  }, [pages, side, page])

  const choose = (m) => {
    setSel(m); setWhy(null)
    api('/explain', { project: pid, tie_id: m.tie_id }).then(setWhy).catch(failed)
  }

  const ask = (m) => {
    const text = `Where does the figure ${m.text} on page ${m.page} of ${deck} come from? Use workroom_explain_figure on link ${m.tie_id} in project ${pid} and tell me in plain words.`
    Promise.resolve(host.composer.insertText(null, text, { mode: 'block' })).then(ok => { if (!ok) setError('Could not reach a chat. Open one and try again.') })
  }

  const doc = over && over.documents.find(d => d.deck === deck)
  const total = pages && pages.total ? pages.total : 1
  const marks = data && data.marks ? data.marks.filter(m => shown[m.kind]) : []
  const counts = {}
  ;(data && data.marks ? data.marks : []).forEach(m => { counts[m.kind] = (counts[m.kind] || 0) + 1 })
  const changedPages = pages && pages.pages ? pages.pages.filter(p => p.marks.changes) : []

  if (!over) return h('section', { style: css.card, 'aria-label': 'Review room' },
    h('h2', { style: css.h2 }, 'Review the documents'),
    h('p', { style: { ...css.muted, margin: '0 0 8px' } }, 'See your report or deck as it is drawn, with every linked figure marked on its page, before and after the release. Nothing is changed by looking.'),
    btn('Open the review room', open, { disabled: busy, primary: true }),
    error ? h('div', { role: 'alert', style: { color: 'var(--ui-red, #dc2626)', marginTop: 8 } }, error) : null)

  return h('section', { style: css.card, 'aria-label': 'Review room', 'aria-busy': busy },
    h('h2', { style: css.h2 }, 'Review the documents'),
    over.blocked && over.blocked.length ? h('div', { role: 'alert', style: { ...css.card, borderColor: 'var(--ui-red, #dc2626)', marginBottom: 8 } },
      h('div', { style: { fontWeight: 600 } }, `${over.blocked.length} figure${over.blocked.length === 1 ? '' : 's'} held back`),
      h('div', { style: { ...css.muted, fontSize: 12 } }, over.blocked[0])) : null,
    h('div', { style: { ...css.row, marginBottom: 8 } },
      h('label', { htmlFor: 'wr-review-doc', style: css.muted }, 'Document'),
      h('select', { id: 'wr-review-doc', value: deck, onChange: e => setDeck(e.target.value), style: { ...css.input, flex: 'none', minWidth: 200 } },
        over.documents.map(d => h('option', { key: d.deck, value: d.deck }, `${d.deck} (${d.counts.changes} change${d.counts.changes === 1 ? '' : 's'})`))),
      h('div', { role: 'group', 'aria-label': 'Which version of the page', style: css.row },
        ['before', 'after'].map(s => h('button', { key: s, type: 'button', 'aria-pressed': side === s, onClick: () => setSide(s), disabled: !pages || !pages.drawn,
          style: { ...css.btn, ...(side === s ? css.primary : {}) } }, s === 'before' ? 'Now' : 'After the release'))),
      busy ? h('span', { style: css.muted }, 'Drawing the pages…') : null),
    error ? h('div', { role: 'alert', style: { color: 'var(--ui-red, #dc2626)', marginBottom: 8 } }, error) : null,
    structural ? h('div', null,
      h('p', { style: { ...css.muted, margin: '0 0 6px' } }, structural.label),
      h('ul', { style: { margin: 0, paddingLeft: 18 } }, structural.rows.slice(0, 60).map(r => h('li', { key: r.tie_id },
        `“${r.sentence}” `, h('strong', null, r.text), r.new_text ? ` → ${r.new_text}` : '', h('span', { style: css.muted }, ` (${MARKS[r.kind] ? MARKS[r.kind].name : r.kind})`))))) : null,
    pages && !pages.drawn ? h('p', { style: css.muted }, 'Office could not draw this document here, so there is nothing to show.') : null,
    data && data.drawn ? h('div', { style: { display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' } },
      h('div', { style: { flex: '1 1 420px', minWidth: 300, maxWidth: 760 } },
        h('div', { style: { ...css.row, justifyContent: 'space-between', marginBottom: 6 } },
          h('div', { style: css.row },
            btn('Previous page', () => setPage(Math.max(1, page - 1)), { disabled: busy || page <= 1 }),
            h('span', { 'aria-live': 'polite' }, `Page ${data.page} of ${total}`),
            btn('Next page', () => setPage(Math.min(total, page + 1)), { disabled: busy || page >= total })),
          changedPages.length ? h('div', { style: css.row },
            h('span', { style: { ...css.muted, fontSize: 12 } }, 'Pages with changes'),
            changedPages.slice(0, 8).map(p => h('button', { key: p.page, type: 'button', onClick: () => setPage(p.page), 'aria-current': p.page === page, style: { ...css.btn, padding: '2px 8px', ...(p.page === page ? css.primary : {}) } }, String(p.page)))) : null),
        h('div', { style: { ...css.row, marginBottom: 6 } }, Object.keys(MARKS).filter(k => counts[k]).map(k => h('button', {
          key: k, type: 'button', 'aria-pressed': shown[k], onClick: () => setShown({ ...shown, [k]: !shown[k] }),
          style: { ...css.chip, background: shown[k] ? MARKS[k].color + '22' : 'transparent', borderColor: MARKS[k].color, color: 'inherit', cursor: 'pointer', opacity: shown[k] ? 1 : 0.5 } }, `${counts[k]} ${MARKS[k].name}`))),
        h('div', { style: { position: 'relative', lineHeight: 0, border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 6, overflow: 'hidden', background: '#fff' } },
          h('img', { src: 'data:image/png;base64,' + data.png, alt: `Page ${data.page} of ${deck}, drawn by ${data.drawn_by}. The marked figures are listed below the page.`, style: { width: '100%', display: 'block' } }),
          marks.map((m, i) => h('button', {
            key: i, type: 'button', 'aria-label': markLabel(m, side), onClick: () => choose(m),
            style: { position: 'absolute', left: `${m.x * 100 - 0.4}%`, top: `${m.y * 100 - 0.25}%`, width: `${m.w * 100 + 0.8}%`, height: `${m.h * 100 + 0.5}%`, padding: 0, cursor: 'pointer',
              border: `2px solid ${MARKS[m.kind].color}`, borderRadius: 3, background: (sel && sel.tie_id === m.tie_id ? MARKS[m.kind].color + '55' : MARKS[m.kind].color + '22') } }))),
        h('div', { style: { ...css.muted, fontSize: 11, marginTop: 4 } }, `Drawn by ${data.drawn_by}. Marks come from your links and are placed by matching the figures to the page text.`)),
      h('div', { style: { flex: '1 1 260px', minWidth: 240 }, role: 'region', 'aria-label': 'Selected figure' },
        sel ? h('div', { style: css.card },
          h('div', { style: { fontWeight: 600 } }, sel.kind === 'changes' ? `${sel.old_text || sel.text} → ${sel.new_text}` : sel.text),
          h('div', { style: { ...css.muted, margin: '2px 0 6px' } }, `${MARKS[sel.kind].name}${sel.label ? ' · “' + sel.label.slice(0, 90) + '”' : ''}`),
          why ? h('div', { style: { fontSize: 12 } },
            h('div', null, `Source: ${why.source.file} · ${why.source.sheet} · ${why.source.cell}`),
            h('div', { style: css.muted }, [...(why.source.row || []), ...(why.source.column || [])].join(' / ')),
            h('div', null, `Value now ${num(why.source.value_now)}; at the last release ${num(why.source.value_at_last_release)}`),
            h('p', { style: { margin: '6px 0' } }, why.how),
            h('p', { style: { ...css.muted, margin: '0 0 6px' } }, why.if_source_changes)) : h('div', { style: css.muted }, 'Reading where it came from…'),
          btn('Ask Hermes about this figure', () => ask(sel), { disabled: busy })) : h('p', { style: { ...css.muted, margin: 0 } }, 'Choose a marked figure on the page to see where it comes from.'),
        h('ul', { style: { margin: '10px 0 0', paddingLeft: 18, fontSize: 12 }, 'aria-label': 'Figures marked on this page' }, marks.slice(0, 40).map((m, i) => h('li', { key: i },
          h('button', { type: 'button', onClick: () => choose(m), style: { all: 'unset', cursor: 'pointer', textDecoration: 'underline', color: 'inherit' } }, markLabel(m, side))))))) : null)
}

function ReleaseRecord({ api, pid, releaseId }) {
  const [text, setText] = useState(null)
  const [error, setError] = useState(null)
  const [signed, setSigned] = useState(null)
  const [embeddable, setEmbeddable] = useState([])
  const [embedded, setEmbedded] = useState(null)
  const exportProof = () => api('/release-proof', { project: pid, ref: releaseId }).then(r => {
    setSigned(JSON.stringify(r, null, 1))
    setEmbeddable(((r.payload && r.payload.files) || []).filter(f => f.package_digest).map(f => f.file))
  }).catch(e => setError(String(e && e.message ? e.message : e)))
  const embedInto = (file) => api('/release-proof-embed', { project: pid, ref: releaseId, text: file }).then(r => setEmbedded('Written beside the original as ' + r.written + '. The released file itself is unchanged.')).catch(e => setError(String(e && e.message ? e.message : e)))
  const load = () => api('/release-record', { project: pid, release_id: releaseId }).then(r => setText(r.text)).catch(e => setError(String(e && e.message ? e.message : e)))
  if (error) return h('span', { role: 'alert', style: { color: 'var(--ui-red, #dc2626)', fontSize: 12 } }, error)
  if (text === null) return btn('Open the record', load, { name: 'Open the record of this release' })
  return h('details', { open: true, style: { width: '100%' } },
    h('summary', { style: css.muted }, 'The record of this release'),
    h('div', { style: { ...css.row, margin: '6px 0' } }, btn('Export a signed proof of this release', exportProof, { name: 'Export a signed proof' }),
      h('span', { style: { ...css.muted, fontSize: 12 } }, 'Shows who approved these exact files against which exact sources. It does not prove the figures are true.')),
    signed ? h('div', null, h('textarea', { readOnly: true, value: signed, rows: 8, 'aria-label': 'Signed proof', style: { ...css.input, width: '100%', fontFamily: 'monospace', fontSize: 11 } }),
      btn('Copy', () => { try { navigator.clipboard.writeText(signed) } catch (e) { /* the text is selectable */ } }),
      embeddable.length ? h('div', { style: { ...css.row, margin: '6px 0' } }, embeddable.map(f => btn('Make a copy of ' + f + ' that carries this proof', () => embedInto(f), { key: f, name: 'Embed the proof in ' + f }))) : null,
      embedded ? h('div', { role: 'status', style: { fontSize: 12, margin: '4px 0' } }, embedded) : null) : null,
    h('pre', { style: { whiteSpace: 'pre-wrap', fontSize: 12, margin: '6px 0', padding: 8, border: '1px solid var(--ui-stroke-secondary, #8884)', borderRadius: 6, maxHeight: 360, overflow: 'auto' }, tabIndex: 0, 'aria-label': 'Release record' }, text))
}

function WorkroomPage({ ctx }) {
  const api = useCallback((path, body) => ctx.rest(path, body === undefined ? undefined : { method: 'POST', body }), [ctx])
  const [projects, setProjects] = useState([])
  const [folder, setFolder] = useState('')
  const [pid, setPid] = useState(null)
  const [found, setFound] = useState(null)
  const [plan, setPlan] = useState(null)
  const [inbox, setInbox] = useState(null)
  const changesRef = useRef(null)
  const [release, setRelease] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [ties, setTies] = useState([])
  const [whyInfo, setWhyInfo] = useState(null)
  const [history, setHistory] = useState(null)
  const [past, setPast] = useState([])
  const [tracked, setTracked] = useState(false)
  const [confirmRestore, setConfirmRestore] = useState(null)
  const [ack, setAck] = useState(false)

  const run = useCallback(async (fn, okText) => {
    setBusy(true)
    setMessage(null)
    try {
      const out = await fn()
      if (okText) setMessage({ kind: 'ok', text: okText(out) })
      return out
    } catch (err) {
      setMessage({ kind: 'error', text: String(err && err.message ? err.message : err) })
      return null
    } finally {
      setBusy(false)
    }
  }, [])

  const checkHistory = useCallback((id) => id ? api('/history', { project: id }).then(setHistory).catch(() => setHistory(null)) : setHistory(null), [api])
  const loadPast = useCallback((id) => id ? api('/releases', { project: id }).then(setPast).catch(() => setPast([])) : setPast([]), [api])
  useEffect(() => { checkHistory(pid); loadPast(pid); setConfirmRestore(null); if (pid) api('/awaiting', { project: pid }).then(a => { if (a.length) setRelease(a[0]) }).catch(() => {}); if (pid) api('/settings', { project: pid }).then(s => setTracked(!!s.tracked_changes)).catch(() => {}) }, [pid, checkHistory, loadPast, api])

  useEffect(() => {
    api('/projects').then(list => { setProjects(list); if (list.length && !pid) setPid(list[0].project) }).catch(() => {})
  }, [api])

  const trySample = () => run(async () => {
    const r = await api('/sample', {})
    setProjects(await api('/projects'))
    setPid(r.project)
    if (r.state === 'awaiting_approval') setRelease(r)
    return r
  }, r => r.state === 'awaiting_approval' ? 'A sample project is ready. Review the deck Workroom wants to create, then approve it.' : 'The sample project is already here.')

  const nextQuarter = () => run(async () => {
    await api('/sample-next', { project: pid })
    setPlan(null); setInbox(null); setRelease(null)
    return {}
  }, () => 'New sample figures arrived. Press Check the sources to see what changes.')

  const addProject = () => run(async () => {
    const p = await api('/projects', { folder })
    setProjects(await api('/projects'))
    setPid(p.project)
    setFolder('')
    return p
  }, () => 'Project added. Nothing in the folder has been changed.')

  const discover = () => run(async () => {
    setRelease(null); setPlan(null)
    const d = await api('/discover', { project: pid })
    setFound(d)
    setTies(await api('/ties', { project: pid }))
    setWhyInfo(null)
    return d
  })

  const decide = (route) => (id) => run(async () => { await api(route, { project: pid, tie_id: id }); setTies(await api('/ties', { project: pid })); setPlan(null); setRelease(null) })
  const confirmTie = decide('/confirm')
  const skipTie = decide('/skip')
  const why = (id) => run(async () => { setWhyInfo(await api('/explain', { project: pid, tie_id: id })) })

  const restoreRelease = (rid) => run(async () => {
    const r = await api('/restore', { project: pid, release_id: rid })
    setConfirmRestore(null); setPlan(null); setRelease(null)
    await loadPast(pid)
    return r
  }, () => 'Restored. The files are back as they were before that release.')

  const toggleTracked = (on) => run(async () => { const s = await api('/settings', { project: pid, tracked_changes: on }); setTracked(!!s.tracked_changes); setPlan(null); setRelease(null) }, () => on ? 'Word changes will be released as tracked changes.' : 'Word changes will be written directly.')

  const acceptHistory = () => run(async () => {
    const r = await api('/accept-history', { project: pid, seen: history.counters })
    await checkHistory(pid)
    return r
  }, () => 'History accepted. You can prepare releases again.')

  const preview = () => run(async () => {
    const p = await api('/plan', { project: pid })
    setPlan(p)
    setInbox(await api('/changes', { project: pid }))
    const calm = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    setTimeout(() => { if (changesRef.current && changesRef.current.scrollIntoView) changesRef.current.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' }) }, 120)
    return p
  })

  const showRelease = async (r) => {
    setAck(false)
    setRelease(r.state === 'blocked' ? r : await api('/release', { project: pid, release_id: r.release_id }))
    return r
  }

  const stage = () => run(async () => showRelease(await api('/stage', { project: pid })), r => r.state === 'blocked' ? 'This release is blocked.' : 'Release prepared. Review it, then approve.')

  const rollForward = () => run(async () => showRelease(await api('/stage-rollforward', { project: pid, periods: 1 })), r => r.state === 'blocked' ? 'This release is blocked.' : 'The roll is prepared. Review it, then approve. Restore undoes the whole roll.')

  const dismissFinding = (id) => run(async () => { await api('/finding-decision', { project: pid, finding: id, decision: 'dismissed' }); setInbox(await api('/changes', { project: pid })) })

  const approve = () => run(async () => {
    const r = await api('/approve', { project: pid, release_id: release.release_id, digest: release.digest, acknowledge: ack })
    setRelease(null); setPlan(null)
    await loadPast(pid)
    return r
  }, () => release && release.created ? 'Published. The new file now exists in your folder. Restore removes it again, unless you have edited it since.' : 'Published. A backup of every replaced file is kept so you can restore it.')


  const current = projects.find(p => p.project === pid)

  return h('div', { style: css.page, 'aria-busy': busy },
    h('div', null, h('h1', { style: css.title }, 'Workroom'), h('p', { style: css.sub }, 'Keeps your reports and decks in step with the numbers behind them. It changes only what must change, and only after you approve.')),
    h(NeedsYou, { api, pid, setPid, refreshKey: past.length + (busy ? 1 : 0) }),
    h('section', { style: css.card, 'aria-label': 'Project' },
      h('h2', { style: css.h2 }, 'Project'),
      projects.length ? h('div', { style: { ...css.row, marginBottom: 8 } },
        h('label', { htmlFor: 'wr-project', style: css.muted }, 'Folder'),
        h('select', { id: 'wr-project', value: pid || '', onChange: e => { setPid(e.target.value); setFound(null); setPlan(null); setRelease(null) }, style: css.input },
          projects.map(p => h('option', { key: p.project, value: p.project }, p.folder)))) : null,
      h('div', { style: css.row },
        h('input', { style: css.input, placeholder: 'Folder with your workbook and deck, for example C:\\Reports\\Monthly', value: folder, onChange: e => setFolder(e.target.value), 'aria-label': 'Folder path' }),
        btn('Add project', addProject, { disabled: busy || !folder.trim() }))),
    history && history.state === 'recovery' ? h('section', { role: 'alert', style: { ...css.card, borderColor: 'var(--ui-amber, #d97706)' }, 'aria-label': 'Saved history needs your review' },
      h('h2', { style: css.h2 }, 'Saved history needs your review'),
      h('p', { style: { margin: '0 0 8px', fontSize: 13 } }, history.counters
        ? 'Workroom keeps three records of how many releases were published for this project, and they do not agree. This can happen if a backup was restored, the folder was copied from another computer, or the history file was deleted or edited. Until you review it, nothing will be released.'
        : 'Workroom cannot trust the saved history file in this folder: ' + history.reason + '. Until you review it, nothing will be released.'),
      history.counters ? h('table', { style: { fontSize: 12, margin: '0 0 8px' } }, h('tbody', null,
        [['History file in the folder', history.counters.manifest], ['Counter kept by Workroom', history.counters.anchor], ['Release journal on this computer', history.counters.journal]].map(([name, n]) => h('tr', { key: name }, h('td', { style: { paddingRight: 16 } }, name), h('td', null, n))))) : null,
      h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'If you accept, the release journal on this computer is treated as correct, and your decision is written to the history together with what was seen. Nothing in your documents changes.'),
      btn('Accept the history on this computer and continue', acceptHistory, { disabled: busy, primary: true })) : null,
    message ? h(Banner, { kind: message.kind }, message.text) : null,
    pid ? h('section', { style: css.card, 'aria-label': 'Links' },
      h('h2', { style: css.h2 }, '1. Find the links'),
      h('p', { style: { ...css.muted, margin: '0 0 8px' } }, 'Workroom reads your documents and links each number to the cell it came from. Nothing is written to your files.'),
      btn('Find links', discover, { disabled: busy, primary: !found }),
      found ? h('div', { style: { marginTop: 10 } },
        h('div', { style: css.row },
          h('span', { style: css.chip }, `${found.numbers_found} numbers found`),
          h('span', { style: { ...css.chip, borderColor: 'var(--ui-green, #16a34a)' } }, `${ties.filter(t => t.state === 'accepted' || t.state === 'confirmed').length} linked`),
          h('span', { style: css.chip }, `${ties.filter(t => t.state === 'confirm' && !t.coincidence).length} need you`),
          h('span', { style: css.chip }, `${found.no_source} have no source`)),
        found.unreadable && found.unreadable.length ? h('p', { role: 'alert', style: { ...css.muted, margin: '6px 0 0', fontSize: 12, color: 'var(--ui-amber, #d97706)' } }, `${found.unreadable.length} file${found.unreadable.length === 1 ? '' : 's'} could not be read and ${found.unreadable.length === 1 ? 'was' : 'were'} left alone: ${found.unreadable.slice(0, 3).join(', ')}${found.unreadable.length > 3 ? ' and more' : ''}.`) : null,
        found.uncalculated && found.uncalculated.length ? h('p', { role: 'alert', style: { ...css.muted, margin: '6px 0 0', fontSize: 12, color: 'var(--ui-amber, #d97706)' } }, `${found.uncalculated.map(u => `${u.file} has ${u.formulas} formula${u.formulas === 1 ? '' : 's'} with no saved value`).slice(0, 2).join('; ')}. A program wrote that file without calculating it: open it in Excel and save it, then find links again.`) : null,
        found.missing && found.missing.length ? h('p', { role: 'alert', style: { ...css.muted, margin: '6px 0 0', fontSize: 12, color: 'var(--ui-amber, #d97706)' } }, `${found.missing.length === 1 ? 'A document is' : found.missing.length + ' documents are'} missing from the folder: ${found.missing.slice(0, 3).join(', ')}. Its links and your decisions about them are kept and resume when it is back.`) : null,
        h(Links, { ties, onConfirm: confirmTie, onSkip: skipTie, onWhy: why, why: whyInfo ? { info: whyInfo, close: () => setWhyInfo(null) } : null, busy }),
        h(Calculations, { api, pid, busy, run })) : null) : null,
    pid && found ? h('section', { ref: changesRef, style: css.card, 'aria-label': 'Changes' },
      h('h2', { style: css.h2 }, '2. See what would change'),
      btn('Check the sources', preview, { disabled: busy }),
      plan ? h('div', { style: { marginTop: 10 } },
        h(ChangeViews, { inbox, folder: current && current.folder, ctx: pluginCtx }),
        inbox && inbox.changes.length && !release ? h(Flags, { flags: inbox.flags, coverage: inbox.coverage, onDismiss: dismissFinding, busy, compact: true }) : null,
        inbox && inbox.changes.length ? null : h(Changes, { changes: plan.changes }),
        plan.held.length ? h('div', { style: { marginTop: 10 } },
          h('div', { style: { fontWeight: 600 } }, 'Held for you'),
          h('ul', { style: { margin: '4px 0 0', paddingLeft: 18 } }, plan.held.map((t, i) => h('li', { key: i }, t)))) : null,
        plan.changes.length ? h('div', { style: { marginTop: 10 } },
          h('label', { style: { ...css.row, margin: '0 0 8px', fontSize: 13 } },
            h('input', { type: 'checkbox', checked: tracked, disabled: busy, onChange: e => toggleTracked(e.target.checked), 'aria-label': 'Release Word changes as tracked changes' }),
            h('span', null, 'Release Word changes as tracked changes, so a reviewer can accept or reject each one')),
          btn('Prepare release', stage, { disabled: busy, primary: true })) : null,
        h('details', { style: { marginTop: 12 } },
          h('summary', { style: { ...css.muted, cursor: 'pointer' } }, 'Moving to the next period?'),
          h('p', { style: { ...css.muted, margin: '6px 0 8px' } }, 'When the workbook has the next period, Workroom can move every linked number to it and advance the period words beside them (Q3 2026 becomes Q4 2026). You approve it once, and Restore undoes the whole move. It refuses, naming each number, if any has no value for the next period.'),
          btn('Roll forward one period', rollForward, { disabled: busy }))) : null) : null,
    pid && found ? h(ReviewRoom, { key: 'room-' + past.length, api, pid }) : null,
    release ? h('section', { style: { ...css.card, borderColor: 'var(--ui-accent, #3b82f6)' }, 'aria-label': 'Release' },
      h('h2', { style: css.h2 }, '3. Approve the release'),
      release.state === 'blocked'
        ? h('div', null, h('div', { style: { fontWeight: 600 } }, 'Blocked'), h('ul', null, (release.findings || []).map((f, i) => h('li', { key: i }, f))))
        : h('div', null,
            release.edited_page ? h('p', { style: { margin: '0 0 8px' } }, `Your edits to ${release.changes[0].deck} will be written (${release.changes[0].new_text}). Tied numbers keep their links to their sources.`)
            : release.created ? h('div', null,
              h('p', { style: { margin: '0 0 6px' } }, `Workroom will create ${release.changes[0].deck}. Every figure in it is linked to its source cell. Nothing else in your folder is touched.`),
              h('ul', { style: { margin: '0 0 8px', paddingLeft: 18 } }, groupFigures(release.figures).slice(0, 12).map((f, i) => h('li', { key: i },
                h('strong', null, f.text), h('span', { style: css.muted }, ` ${f.concept || ''} ${f.period || ''} · ${f.source}${f.count > 1 ? ` · in ${f.count} places` : ''}`)))))
            : release.rolled ? h('p', { style: { margin: '0 0 8px' } }, `Workroom will roll your documents forward: ${release.rolled.figures} figures move to the next period and ${release.rolled.period_words} period words advance (${release.rolled.example}). Restore undoes the whole roll.`)
            : h('p', { style: { margin: '0 0 8px' } }, `${release.changes.length} number${release.changes.length === 1 ? '' : 's'} will change in your documents. Everything else stays exactly as it is, and a backup of each replaced file is kept.`),
            release.changes && release.rolled ? h('ul', { style: { margin: '0 0 8px', paddingLeft: 18 } }, release.changes.slice(0, 8).map((c, i) => h('li', { key: i }, h('span', { style: css.muted }, `${c.old_text} `), '\u2192 ', h('strong', null, c.new_text), h('span', { style: css.muted }, `  ${c.deck}, ${c.where || 'slide ' + c.slide}`)))) : null,
            release.held && release.held.length ? h('details', { style: { margin: '0 0 8px' } }, h('summary', { style: css.muted }, `${release.held.length} left for you`), release.held.map((t, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, t))) : null,
            release.restated && release.restated.length ? h('details', { style: { margin: '0 0 8px' } }, h('summary', { style: css.muted }, `${release.restated.length} figure${release.restated.length === 1 ? '' : 's'} for a period the report already showed ${release.restated.length === 1 ? 'is' : 'are'} now different`), release.restated.map((t, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, t))) : null,
            release.nil_cells && release.nil_cells.length ? h('details', { style: { margin: '0 0 8px' } }, h('summary', { style: css.muted }, `${release.nil_cells.length} dash${release.nil_cells.length === 1 ? '' : 'es'} may now hold a figure (not changed)`), release.nil_cells.map((t, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, t))) : null,
            release.notes && release.notes.length ? h('details', { style: { margin: '0 0 8px' } }, h('summary', { style: css.muted }, `${release.notes.length} change${release.notes.length === 1 ? '' : 's'} in your workbook were followed`), release.notes.map((t, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, t))) : null,
            (release.flags && release.flags.length) || (release.coverage && release.coverage.sentences_checked) ? h(Flags, { flags: release.flags, coverage: release.coverage, busy }) : null,
            release.needs_acknowledgement && release.needs_acknowledgement.length ? h('label', { style: { ...css.row, margin: '8px 0', fontSize: 13 } },
              h('input', { type: 'checkbox', checked: ack, onChange: e => setAck(e.target.checked), 'aria-label': 'I have read the flagged sentences' }),
              h('span', null, 'I have read the sentences above and still want to release.')) : null,
            h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, `Release fingerprint ${release.digest.slice(0, 12)}. Your approval applies to exactly this release and nothing else.`),
            release.created || release.edited_page ? null : h(Proof, { api, pid, releaseId: release.release_id }),
            btn('Approve and publish', approve, { disabled: busy || (release.needs_acknowledgement && release.needs_acknowledgement.length > 0 && !ack), primary: true }))) : null,
    !projects.length ? h('section', { style: { ...css.card, borderColor: 'var(--ui-accent, #3b82f6)' }, 'aria-label': 'Try the sample' },
      h('h2', { style: css.h2 }, 'New here? Try the sample'),
      h('p', { style: { margin: '0 0 8px' } }, 'Workroom makes a small sample project in its own storage (a results workbook and a board deck whose every figure is tied to a cell). Your own files are not touched. You approve the deck, then pretend a new quarter arrived and watch only the changed numbers update.'),
      btn('Make the sample project', trySample, { disabled: busy, primary: true })) : null,
    current && current.folder.replace(/[\\/]+$/, '').endsWith('sample-quarterly') ? h('section', { style: css.card, 'aria-label': 'Sample controls' },
      h('div', { style: { ...css.row, justifyContent: 'space-between' } },
        h('span', { style: { fontSize: 13 } }, 'This is the sample project.'),
        btn('Pretend a new quarter arrived', nextQuarter, { disabled: busy }))) : null,
    pid ? h(PagesList, { api, pid }) : null,
    pid ? h(Instructions, { api, pid, busy, run }) : null,
    pid ? h(Deliverables, { api, pid, busy, run, ctx }) : null,
    pid ? h(Room, { api, pid, busy, run }) : null,
    pid ? h(AgentChanges, { api, pid, busy, run }) : null,
    pid ? h(Policy, { api, pid, busy, run }) : null,
    pid && past.length ? h('section', { style: css.card, 'aria-label': 'Past releases' },
      h('h2', { style: css.h2 }, 'Past releases'),
      h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'Restoring puts the files of that release back as they were before it. It is refused if you have worked in those files since, so nothing you did later is overwritten.'),
      past.map(r => h('div', { key: r.release_id, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0' } },
        h('span', { style: { fontSize: 13 } }, `${new Date(r.published_at * 1000).toLocaleString()} · ${r.created ? 'created ' + r.changes[0].deck : r.changes.length + ' number' + (r.changes.length === 1 ? '' : 's')}${r.restored ? ' · restored' : ''}`),
        h(ReleaseRecord, { api, pid, releaseId: r.release_id }),
        r.restored ? null : confirmRestore === r.release_id
          ? h('span', { style: css.row }, btn(r.created ? 'Yes, remove this file' : 'Yes, restore these files', () => restoreRelease(r.release_id), { disabled: busy, primary: true }), btn('Cancel', () => setConfirmRestore(null), { disabled: busy }))
          : btn('Restore', () => setConfirmRestore(r.release_id), { disabled: busy })))) : null,
    current ? h('div', { style: { ...css.muted, fontSize: 11 } }, `Working on ${current.folder}`) : null)
}

export default {
  id: 'workroom',
  name: 'Workroom',
  register(ctx) {
    ctx.register({
      id: 'page',
      area: 'panes',
      title: 'workroom',
      data: { placement: 'main' },
      render: () => h(WorkroomPage, { ctx })
    })
    pluginCtx = ctx
    ctx.register({
      id: 'room',
      area: 'panes',
      title: 'Workroom',
      data: { placement: 'right', width: '400px' },
      render: () => h(SidePane, { ctx })
    })
    ctx.register({ id: 'needs-status', area: STATUSBAR_AREAS.right, order: 130, render: () => h(NeedsStatus, { ctx }) })
    const reveal = (id) => () => { if (host.undismissPane) host.undismissPane(id); if (host.revealPane) host.revealPane(id) }
    ctx.register({ id: 'palette-open', area: PALETTE_AREA, data: { id: 'workroom.open', label: 'Workroom: open the project pane', keywords: ['workroom', 'deliverables', 'room', 'approve'], run: reveal('workroom:room') } })
    ctx.register({ id: 'palette-full', area: PALETTE_AREA, data: { id: 'workroom.full', label: 'Workroom: open the full page', keywords: ['workroom', 'documents', 'links', 'release'], run: reveal('workroom:page') } })
    ctx.register({
      id: 'release-card',
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: { name: 'workroom-release', render: ({ attrs }) => h(ReleaseCard, { ctx, attrs: attrs || {} }) }
    })
  }
}
