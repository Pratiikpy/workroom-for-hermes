import { createElement as h, useCallback, useEffect, useRef, useState } from 'react'
import { SandboxedFrame, host } from '@hermes/plugin-sdk'
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
  if (!changes.length) return h('div', { style: css.muted }, 'No tied number has changed since the last release.')
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
  const need = ties.filter(t => t.state === 'confirm')
  const done = ties.filter(t => t.state === 'accepted' || t.state === 'confirmed')
  return h('div', { style: { marginTop: 10 } },
    need.length ? h('div', null,
      h('div', { style: { fontWeight: 600, margin: '0 0 6px' } }, `${need.length} number${need.length === 1 ? '' : 's'} need${need.length === 1 ? 's' : ''} you`),
      need.map(t => h('div', { key: t.id, style: { ...css.card, marginBottom: 6 } },
        h('div', null, `“${t.sentence || t.text}”`),
        h('div', { style: { ...css.muted, margin: '2px 0 8px' } }, `Slide ${t.slide} of ${t.deck}. Is ${t.text} the figure from ${t.source}?`),
        h('div', { style: css.row },
          btn('Yes, that is the source', () => onConfirm(t.id), { disabled: busy, primary: true }),
          btn('No, leave it alone', () => onSkip(t.id), { disabled: busy }),
          btn('Where could it come from?', () => onWhy(t.id), { disabled: busy }))))) : null,
    done.length ? h('details', { style: { marginTop: 8 } },
      h('summary', { style: { cursor: 'pointer' } }, `${done.length} linked number${done.length === 1 ? '' : 's'}`),
      h('ul', { style: { listStyle: 'none', margin: '6px 0 0', padding: 0 } }, done.map(t => h('li', { key: t.id, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0', borderTop: '1px solid var(--ui-stroke-tertiary, #8883)' } },
        h('span', null, h('strong', null, t.text), h('span', { style: css.muted }, `  ${t.sentence || ''}`)),
        btn('Why?', () => onWhy(t.id), { disabled: busy, name: `Why is ${t.text} linked?` }))))) : null,
    why ? h(Why, { info: why.info, onClose: why.close }) : null)
}

const SEVERITY = { high: 'Check', medium: 'Look', info: 'Note' }

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
        onDismiss ? btn('This is not a problem here', () => onDismiss(f.id), { disabled: busy }) : null))),
    noted.length ? h('details', { style: { marginTop: 4 } }, h('summary', { style: css.muted }, `${noted.length} more note${noted.length === 1 ? '' : 's'}`),
      noted.map(f => h('div', { key: f.id, style: { ...css.muted, fontSize: 12, padding: '2px 0' } }, `${f.summary}. ${f.sentence_after}`))) : null,
    cov.sentences_checked !== undefined ? h('details', { style: { marginTop: 6 } },
      h('summary', { style: css.muted }, `Checked ${cov.sentences_checked} sentence${cov.sentences_checked === 1 ? '' : 's'}, read ${cov.claims_read} claim${cov.claims_read === 1 ? '' : 's'}${cov.not_checked_count ? `, ${cov.not_checked_count} could not be checked` : ''}`),
      h('div', { style: { ...css.muted, fontSize: 12 } }, 'Workroom reads claims of the kind "up from", "grew from X to Y", "exceeded", "record" and "grew to". It does not guess at any other wording.'),
      (cov.not_checked || []).map((n, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, n))) : null)
}

// Numbers in the documents that a calculation over tied cells reproduces. Accepting one makes it follow its sources like any other tie.
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
          ? `Created ${view.changes[0].deck}. Every figure in it is tied to its source.`
          : `Workroom would create ${view.changes[0].deck}, with ${view.figures.length} figures each tied to its source cell. Nothing has been written yet.`),
        h('ul', { style: { margin: '4px 0', paddingLeft: 18 } }, groupFigures(view.figures).slice(0, 8).map((f, i) => h('li', { key: i },
          h('strong', null, f.text), h('span', { style: css.muted }, ` ${f.concept || ''} ${f.period || ''} · ${f.source}${f.count > 1 ? ` · in ${f.count} places` : ''}`)))),
        view.figures.length > 8 ? h('div', { style: css.muted }, `and ${view.figures.length - 8} more figures`) : null)
      : view.rolled ? h('p', { style: { margin: '6px 0' } }, view.state === 'published'
        ? `Rolled forward: ${view.rolled.figures} figures now show the next period and ${view.rolled.period_words} period words advanced. Restore undoes the whole roll.`
        : `Roll forward: ${view.rolled.figures} figures move to the next period and ${view.rolled.period_words} period words advance (${view.rolled.from.join(', ')} to ${view.rolled.to.join(', ')}). Nothing has been changed yet; Restore undoes the whole roll.`)
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

function WorkroomPage({ ctx }) {
  const api = useCallback((path, body) => ctx.rest(path, body === undefined ? undefined : { method: 'POST', body }), [ctx])
  const [projects, setProjects] = useState([])
  const [folder, setFolder] = useState('')
  const [pid, setPid] = useState(null)
  const [found, setFound] = useState(null)
  const [plan, setPlan] = useState(null)
  const [inbox, setInbox] = useState(null)
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
    h('div', null, h('h1', { style: css.title }, 'Workroom'), h('p', { style: css.sub }, 'Keeps your decks in step with their source numbers. It only changes what must change, and only after you approve.')),
    h('section', { style: css.card, 'aria-label': 'Project' },
      h('h2', { style: css.h2 }, 'Project'),
      projects.length ? h('div', { style: { ...css.row, marginBottom: 8 } },
        h('label', { htmlFor: 'wr-project', style: css.muted }, 'Folder'),
        h('select', { id: 'wr-project', value: pid || '', onChange: e => { setPid(e.target.value); setFound(null); setPlan(null); setRelease(null) }, style: css.input },
          projects.map(p => h('option', { key: p.project, value: p.project }, p.folder)))) : null,
      pid ? h('label', { style: { ...css.row, margin: '0 0 8px', fontSize: 13 } },
        h('input', { type: 'checkbox', checked: tracked, disabled: busy, onChange: e => toggleTracked(e.target.checked), 'aria-label': 'Release Word changes as tracked changes' }),
        h('span', null, 'Release Word changes as tracked changes (the old number is struck through and the new one inserted, so a reviewer can accept or reject it)')) : null,
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
      h('p', { style: { ...css.muted, margin: '0 0 8px' } }, 'Workroom reads your documents and links each number to the cell it came from. It writes nothing to your files.'),
      btn('Find links', discover, { disabled: busy, primary: !found }),
      found ? h('div', { style: { marginTop: 10 } },
        h('div', { style: css.row },
          h('span', { style: css.chip }, `${found.numbers_found} numbers found`),
          h('span', { style: { ...css.chip, borderColor: 'var(--ui-green, #16a34a)' } }, `${ties.filter(t => t.state === 'accepted' || t.state === 'confirmed').length} linked`),
          h('span', { style: css.chip }, `${ties.filter(t => t.state === 'confirm').length} need you`),
          h('span', { style: css.chip }, `${found.no_source} have no source`)),
        found.unreadable && found.unreadable.length ? h('p', { role: 'alert', style: { ...css.muted, margin: '6px 0 0', fontSize: 12, color: 'var(--ui-amber, #d97706)' } }, `${found.unreadable.length} file${found.unreadable.length === 1 ? '' : 's'} could not be read and ${found.unreadable.length === 1 ? 'was' : 'were'} left alone: ${found.unreadable.slice(0, 3).join(', ')}${found.unreadable.length > 3 ? ' and more' : ''}.`) : null,
        h(Links, { ties, onConfirm: confirmTie, onSkip: skipTie, onWhy: why, why: whyInfo ? { info: whyInfo, close: () => setWhyInfo(null) } : null, busy }),
        h(Calculations, { api, pid, busy, run })) : null) : null,
    pid && found ? h('section', { style: css.card, 'aria-label': 'Changes' },
      h('h2', { style: css.h2 }, '2. See what would change'),
      btn('Check the sources', preview, { disabled: busy }),
      plan ? h('div', { style: { marginTop: 10 } },
        h(Inbox, { inbox }),
        inbox && inbox.changes.length ? h(Flags, { flags: inbox.flags, coverage: inbox.coverage, onDismiss: dismissFinding, busy, compact: true }) : null,
        inbox && inbox.changes.length ? null : h(Changes, { changes: plan.changes }),
        plan.held.length ? h('div', { style: { marginTop: 10 } },
          h('div', { style: { fontWeight: 600 } }, 'Held for you'),
          h('ul', { style: { margin: '4px 0 0', paddingLeft: 18 } }, plan.held.map((t, i) => h('li', { key: i }, t)))) : null,
        plan.changes.length ? h('div', { style: { marginTop: 10 } }, btn('Prepare release', stage, { disabled: busy, primary: true })) : null) : null) : null,
    release ? h('section', { style: { ...css.card, borderColor: 'var(--ui-accent, #3b82f6)' }, 'aria-label': 'Release' },
      h('h2', { style: css.h2 }, '3. Approve the release'),
      release.state === 'blocked'
        ? h('div', null, h('div', { style: { fontWeight: 600 } }, 'Blocked'), h('ul', null, (release.findings || []).map((f, i) => h('li', { key: i }, f))))
        : h('div', null,
            release.edited_page ? h('p', { style: { margin: '0 0 8px' } }, `Your edits to ${release.changes[0].deck} will be written (${release.changes[0].new_text}). Tied numbers keep their links to their sources.`)
            : release.created ? h('div', null,
              h('p', { style: { margin: '0 0 6px' } }, `Workroom will create ${release.changes[0].deck}. Every figure in it is tied to its source cell. Nothing else in your folder is touched.`),
              h('ul', { style: { margin: '0 0 8px', paddingLeft: 18 } }, groupFigures(release.figures).slice(0, 12).map((f, i) => h('li', { key: i },
                h('strong', null, f.text), h('span', { style: css.muted }, ` ${f.concept || ''} ${f.period || ''} · ${f.source}${f.count > 1 ? ` · in ${f.count} places` : ''}`)))))
            : release.rolled ? h('p', { style: { margin: '0 0 8px' } }, `Workroom will roll your documents forward: ${release.rolled.figures} figures move to the next period and ${release.rolled.period_words} period words advance (${release.rolled.from.join(', ')} to ${release.rolled.to.join(', ')}). Restore undoes the whole roll.`)
            : h('p', { style: { margin: '0 0 8px' } }, `${release.changes.length} number${release.changes.length === 1 ? '' : 's'} will change in your documents. Everything else stays exactly as it is, and a backup of each replaced file is kept.`),
            release.changes && release.rolled ? h('ul', { style: { margin: '0 0 8px', paddingLeft: 18 } }, release.changes.slice(0, 8).map((c, i) => h('li', { key: i }, h('span', { style: css.muted }, `${c.old_text} `), '\u2192 ', h('strong', null, c.new_text), h('span', { style: css.muted }, `  ${c.deck}, ${c.where || 'slide ' + c.slide}`)))) : null,
            release.held && release.held.length ? h('details', { style: { margin: '0 0 8px' } }, h('summary', { style: css.muted }, `${release.held.length} left for you`), release.held.map((t, i) => h('div', { key: i, style: { ...css.muted, fontSize: 12 } }, t))) : null,
            (release.flags && release.flags.length) || (release.coverage && release.coverage.sentences_checked) ? h(Flags, { flags: release.flags, coverage: release.coverage, busy }) : null,
            release.needs_acknowledgement && release.needs_acknowledgement.length ? h('label', { style: { ...css.row, margin: '8px 0', fontSize: 13 } },
              h('input', { type: 'checkbox', checked: ack, onChange: e => setAck(e.target.checked), 'aria-label': 'I have read the flagged sentences' }),
              h('span', null, 'I have read the sentences above and still want to release.')) : null,
            h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, `Release fingerprint ${release.digest.slice(0, 12)}. Your approval applies to exactly this release and nothing else.`),
            release.created || release.edited_page ? null : h(Proof, { api, pid, releaseId: release.release_id }),
            btn('Approve and publish', approve, { disabled: busy || (release.needs_acknowledgement && release.needs_acknowledgement.length > 0 && !ack), primary: true }))) : null,
    pid && found ? h('section', { style: css.card, 'aria-label': 'Next period' },
      h('h2', { style: css.h2 }, 'Next period'),
      h('p', { style: { ...css.muted, margin: '0 0 8px' } }, 'When the workbook has the next period, Workroom can move every tied figure to it and advance the period words beside them (Q3 2026 becomes Q4 2026). It is one release you approve, and Restore undoes the whole roll. It refuses, naming each figure, if any figure has no value for the next period.'),
      btn('Roll forward one period', rollForward, { disabled: busy })) : null,
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
    pid && past.length ? h('section', { style: css.card, 'aria-label': 'Past releases' },
      h('h2', { style: css.h2 }, 'Past releases'),
      h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'Restoring puts the files of that release back as they were before it. It is refused if you have worked in those files since, so nothing you did later is overwritten.'),
      past.map(r => h('div', { key: r.release_id, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0' } },
        h('span', { style: { fontSize: 13 } }, `${new Date(r.published_at * 1000).toLocaleString()} · ${r.created ? 'created ' + r.changes[0].deck : r.changes.length + ' number' + (r.changes.length === 1 ? '' : 's')}${r.restored ? ' · restored' : ''}`),
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
      id: 'release-card',
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: { name: 'workroom-release', render: ({ attrs }) => h(ReleaseCard, { ctx, attrs: attrs || {} }) }
    })
  }
}
