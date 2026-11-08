import { createElement as h, useCallback, useEffect, useState } from 'react'
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

const stateLabel = { accepted: 'linked automatically', confirmed: 'linked by you', confirm: 'needs you', skipped: 'left alone' }

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
  const load = useCallback(
    () => ctx.rest('/release', { method: 'POST', body: { project: attrs.project, release_id: attrs.release } }).then(setView).catch(e => setError(String(e && e.message ? e.message : e))),
    [ctx, attrs.project, attrs.release]
  )
  useEffect(() => { if (valid) load() }, [valid, load])
  if (!valid) return null
  const approve = async () => {
    setBusy(true)
    try {
      await ctx.rest('/approve', { method: 'POST', body: { project: attrs.project, release_id: attrs.release, digest: view.digest } })
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
      h('p', { style: { margin: '6px 0' } }, view.state === 'published'
        ? `${view.changes.length} number${view.changes.length === 1 ? '' : 's'} updated. A backup of each replaced file is kept.`
        : `${view.changes.length} number${view.changes.length === 1 ? '' : 's'} would change. Nothing has been changed yet.`),
      shown.map((c, i) => h('div', { key: i, style: { display: 'flex', gap: 8, padding: '2px 0' } },
        h('span', { style: { ...css.muted, textDecoration: view.state === 'published' ? 'none' : 'line-through', minWidth: 70 } }, c.old_text),
        h('span', null, '\u2192'),
        h('strong', null, c.new_text),
        h('span', { style: css.muted }, `${c.deck}, ${c.where || 'slide ' + c.slide}`))),
      view.changes.length > shown.length ? h('div', { style: css.muted }, `and ${view.changes.length - shown.length} more`) : null,
      view.held && view.held.length ? h('div', { style: { ...css.muted, marginTop: 6 } }, `${view.held.length} held for you`) : null,
      view.findings && view.findings.length ? h('ul', null, view.findings.map((f, i) => h('li', { key: i }, f))) : null,
      view.state === 'awaiting_approval' ? h('div', { style: { ...css.row, marginTop: 10 } },
        btn('Approve and publish', approve, { disabled: busy, primary: true }),
        h('span', { style: { ...css.muted, fontSize: 11 } }, `Applies to exactly this release (${view.digest.slice(0, 12)}).`)) : null) : null)
}

function WorkroomPage({ ctx }) {
  const api = useCallback((path, body) => ctx.rest(path, body === undefined ? undefined : { method: 'POST', body }), [ctx])
  const [projects, setProjects] = useState([])
  const [folder, setFolder] = useState('')
  const [pid, setPid] = useState(null)
  const [found, setFound] = useState(null)
  const [plan, setPlan] = useState(null)
  const [release, setRelease] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [ties, setTies] = useState([])
  const [whyInfo, setWhyInfo] = useState(null)
  const [history, setHistory] = useState(null)
  const [past, setPast] = useState([])
  const [tracked, setTracked] = useState(false)
  const [confirmRestore, setConfirmRestore] = useState(null)

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
  useEffect(() => { checkHistory(pid); loadPast(pid); setConfirmRestore(null); if (pid) api('/settings', { project: pid }).then(s => setTracked(!!s.tracked_changes)).catch(() => {}) }, [pid, checkHistory, loadPast, api])

  useEffect(() => {
    api('/projects').then(list => { setProjects(list); if (list.length && !pid) setPid(list[0].project) }).catch(() => {})
  }, [api])

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
    return p
  })

  const stage = () => run(async () => {
    const r = await api('/stage', { project: pid })
    setRelease(r)
    return r
  }, r => r.state === 'blocked' ? 'This release is blocked.' : 'Release prepared. Review it, then approve.')

  const approve = () => run(async () => {
    const r = await api('/approve', { project: pid, release_id: release.release_id, digest: release.digest })
    setRelease(null); setPlan(null)
    await loadPast(pid)
    return r
  }, () => 'Published. A backup of every replaced file is kept so you can restore it.')


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
        h(Links, { ties, onConfirm: confirmTie, onSkip: skipTie, onWhy: why, why: whyInfo ? { info: whyInfo, close: () => setWhyInfo(null) } : null, busy })) : null) : null,
    pid && found ? h('section', { style: css.card, 'aria-label': 'Changes' },
      h('h2', { style: css.h2 }, '2. See what would change'),
      btn('Check the sources', preview, { disabled: busy }),
      plan ? h('div', { style: { marginTop: 10 } },
        h(Changes, { changes: plan.changes }),
        plan.held.length ? h('div', { style: { marginTop: 10 } },
          h('div', { style: { fontWeight: 600 } }, 'Held for you'),
          h('ul', { style: { margin: '4px 0 0', paddingLeft: 18 } }, plan.held.map((t, i) => h('li', { key: i }, t)))) : null,
        plan.changes.length ? h('div', { style: { marginTop: 10 } }, btn('Prepare release', stage, { disabled: busy, primary: true })) : null) : null) : null,
    release ? h('section', { style: { ...css.card, borderColor: 'var(--ui-accent, #3b82f6)' }, 'aria-label': 'Release' },
      h('h2', { style: css.h2 }, '3. Approve the release'),
      release.state === 'blocked'
        ? h('div', null, h('div', { style: { fontWeight: 600 } }, 'Blocked'), h('ul', null, (release.findings || []).map((f, i) => h('li', { key: i }, f))))
        : h('div', null,
            h('p', { style: { margin: '0 0 8px' } }, `${release.changes.length} number${release.changes.length === 1 ? '' : 's'} will change in your documents. Everything else stays exactly as it is, and a backup of each replaced file is kept.`),
            h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, `Release fingerprint ${release.digest.slice(0, 12)}. Your approval applies to exactly this release and nothing else.`),
            btn('Approve and publish', approve, { disabled: busy, primary: true }))) : null,
    pid && past.length ? h('section', { style: css.card, 'aria-label': 'Past releases' },
      h('h2', { style: css.h2 }, 'Past releases'),
      h('p', { style: { ...css.muted, margin: '0 0 8px', fontSize: 12 } }, 'Restoring puts the files of that release back as they were before it. It is refused if you have worked in those files since, so nothing you did later is overwritten.'),
      past.map(r => h('div', { key: r.release_id, style: { ...css.row, justifyContent: 'space-between', padding: '4px 0' } },
        h('span', { style: { fontSize: 13 } }, `${new Date(r.published_at * 1000).toLocaleString()} · ${r.changes.length} number${r.changes.length === 1 ? '' : 's'}${r.restored ? ' · restored' : ''}`),
        r.restored ? null : confirmRestore === r.release_id
          ? h('span', { style: css.row }, btn('Yes, restore these files', () => restoreRelease(r.release_id), { disabled: busy, primary: true }), btn('Cancel', () => setConfirmRestore(null), { disabled: busy }))
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
    ctx.register({
      id: 'release-card',
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: { name: 'workroom-release', render: ({ attrs }) => h(ReleaseCard, { ctx, attrs: attrs || {} }) }
    })
  }
}
