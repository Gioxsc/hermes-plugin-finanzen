/**
 * Finanzen — BWA-Dashboard (nulleins) als Tab in der Hermes Desktop App.
 * UI folgt 1:1 dem nulleins BwaSection-Layout: links die KER-Erfassungsgruppen
 * (editierbar), rechts Live-Ergebnis + Kostenarten-Donut. Speichern schreibt
 * über das Plugin-Backend direkt in data/bwa.db (dieselbe Tabelle wie nulleins).
 *
 * Excel/Drucken öffnen nulleins im Browser.
 */

import { cn, host, PALETTE_AREA, ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'
import { useEffect, useMemo, useRef, useState } from 'react'

// nulleins Dev-Server (npm run dev, Port 4100) — Excel/Drucken leiten dorthin weiter.
const NULLEINS_BASE = 'http://localhost:4100'

const eur = (cents) =>
  (Number(cents) / 100).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const pct = (n) => Number(n).toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']
const label = (m) => { const [y, mo] = m.split('-'); return `${MONATE[Number(mo) - 1]} ${y}` }

const GROUPS = ['Ertrag', 'Einsatz', 'Kostenarten', 'Neutral', 'Steuern']

// Live-Berechnung (Port von lib/bwa.ts computeBwa) — identisch zum Backend.
const KOSTEN_KEYS = ['personal', 'raum', 'betrSteuern', 'versicherungen', 'besondereKosten', 'fahrzeug', 'werbungReise', 'kostenWarenabgabe', 'abschreibungen', 'reparatur', 'sonstigeKosten']
const KOSTENARTEN_LABELS = [['material', 'Material-/Wareneinkauf'], ['personal', 'Personalkosten'], ['raum', 'Raumkosten'], ['betrSteuern', 'Betriebliche Steuern'], ['versicherungen', 'Versicherungen/Beiträge'], ['besondereKosten', 'Besondere Kosten'], ['fahrzeug', 'Fahrzeugkosten (ohne Steuer)'], ['werbungReise', 'Werbe-/Reisekosten'], ['kostenWarenabgabe', 'Kosten Warenabgabe'], ['abschreibungen', 'Abschreibungen'], ['reparatur', 'Reparatur/Instandhaltung'], ['sonstigeKosten', 'Sonstige Kosten']]

function parseGermanNumber(raw) {
  const t = String(raw ?? '').trim().replace(/€|\s/g, '')
  if (!t) return null
  let n
  if (/,\d{1,2}$/.test(t)) n = Number(t.replace(/\./g, '').replace(',', '.'))
  else if (/\.\d{1,2}$/.test(t)) n = Number(t.replace(/,/g, ''))
  else n = Number(t.replace(/[.,]/g, ''))
  return Number.isFinite(n) ? Math.round(n * 100) : null
}

function computeBwa(cents) {
  const g = (k) => (Number.isFinite(cents[k]) ? cents[k] : 0)
  const gesamtleistung = g('umsatz') + g('bestandsveraenderung') + g('aktivierteEigenleistungen')
  const material = g('material')
  const rohertrag = gesamtleistung - material
  const betrieblicherRohertrag = rohertrag + g('sonstBetrErloese')
  const gesamtkosten = KOSTEN_KEYS.reduce((s, k) => s + g(k), 0)
  const betriebsergebnis = betrieblicherRohertrag - gesamtkosten
  const neutralerAufwand = g('zinsaufwand') + g('sonstNeutralAufwand')
  const neutralerErtrag = g('zinsertraege') + g('sonstNeutralErtrag') + g('verrechneteKalkKosten')
  const ergebnisVorSteuern = betriebsergebnis - neutralerAufwand + neutralerErtrag
  const vorlaeufigesErgebnis = ergebnisVorSteuern - g('steuernEinkommenErtrag')
  const p = (part, whole) => (whole === 0 ? 0 : (part / whole) * 100)
  return {
    gesamtleistung, rohertrag, betrieblicherRohertrag, gesamtkosten, betriebsergebnis,
    neutralerAufwand, neutralerErtrag, ergebnisVorSteuern, vorlaeufigesErgebnis,
    pctMaterialGesLeistung: p(material, gesamtleistung),
    pctPersonalGesKosten: p(g('personal'), gesamtkosten),
  }
}

function bwaCostCategories(cents) {
  return KOSTENARTEN_LABELS
    .map(([key, category]) => ({ category, total: cents[key] || 0 }))
    .filter((c) => c.total !== 0)
    .sort((a, b) => b.total - a.total)
}

// Donut-Palette: Akzent + Grauabstufungen, auf jede Theme-Variante lesbar.
const DONUT_COLORS = ['var(--ui-accent)', 'rgba(128,128,128,0.85)', 'rgba(128,128,128,0.6)', 'rgba(128,128,128,0.45)', 'rgba(128,128,128,0.32)', 'rgba(128,128,128,0.22)', 'rgba(128,128,128,0.14)', 'rgba(128,128,128,0.09)']

function colorFor(i) {
  return DONUT_COLORS[i % DONUT_COLORS.length]
}

let _rest = null
let _os = null

function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}


// Eigener Button-Stil: Pill-Buttons mit echten Hover-/Active-Transitions.
function StyleOnce() {
  return jsx('style', { children: `
.fz-btn{display:inline-flex;align-items:center;gap:6px;padding:6px 13px;border-radius:8px;
  font:600 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.02em;cursor:pointer;
  border:1px solid var(--ui-stroke-secondary);background:transparent;color:inherit;
  transition:background .15s ease,border-color .15s ease,box-shadow .15s ease,transform .06s ease;}
.fz-btn:hover{background:var(--chrome-action-hover);border-color:var(--ui-text-quaternary,var(--ui-stroke-secondary));}
.fz-btn:active{transform:translateY(1px);}
.fz-btn:disabled{opacity:.45;cursor:default;transform:none;}
.fz-btn--primary{color:var(--ui-accent);border-color:color-mix(in srgb,var(--ui-accent) 55%,transparent);
  background:color-mix(in srgb,var(--ui-accent) 10%,transparent);
  box-shadow:0 0 0 0 color-mix(in srgb,var(--ui-accent) 25%,transparent);}
.fz-btn--primary:hover{background:color-mix(in srgb,var(--ui-accent) 18%,transparent);
  border-color:var(--ui-accent);box-shadow:0 1px 6px color-mix(in srgb,var(--ui-accent) 25%,transparent);}
.fz-btn--danger:hover{border-color:#e5484d;color:#e5484d;background:color-mix(in srgb,#e5484d 10%,transparent);}
.fz-chip{display:inline-flex;align-items:center;gap:5px;padding:4px 11px;border-radius:999px;
  font:500 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;cursor:pointer;
  border:1px solid var(--ui-stroke-secondary);background:transparent;color:inherit;opacity:.75;
  transition:background .15s ease,border-color .15s ease,color .15s ease,opacity .15s ease;}
.fz-chip:hover{opacity:1;background:var(--chrome-action-hover);}
.fz-chip--active{opacity:1;border-color:var(--ui-accent);color:var(--ui-accent);
  background:color-mix(in srgb,var(--ui-accent) 12%,transparent);font-weight:600;}
` })
}

function GroupBlock(title, fields, values, setValue) {
  if (!fields.length) return null
  return jsxs('div', {
    className: 'mb-3',
    children: [
      jsx('div', {
        className: 'mb-1.5 font-mono text-[10px] uppercase tracking-[0.1em] opacity-50',
        children: title,
      }),
      jsx('div', {
        className: 'grid grid-cols-2 gap-x-3 gap-y-1.5',
        children: fields.map((f) => jsxs('label', {
          className: 'flex items-center justify-between gap-2',
          children: [
            jsx('span', { className: 'min-w-0 truncate text-[12px] opacity-70', children: f.label }),
            jsx('input', {
              value: values[f.key] ?? '',
              onChange: (e) => setValue(f.key, e.target.value),
              placeholder: '0,00',
              inputMode: 'decimal',
              'aria-label': f.label,
              className: 'w-28 shrink-0 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-right font-mono text-[12px]',
            }),
          ],
        }, f.key)),
      }),
    ],
  })
}

/** SVG-Donut: Segmente als stroke-dasharray-Kreise, Zentrum = Monatssumme. */
function Donut(items, centerLabel, sizePx) {
  const size = sizePx ?? 150
  const total = items.reduce((s, c) => s + c.total, 0)
  const r = size / 2 - 12
  const c = 2 * Math.PI * r
  let offset = 0
  const segs = items.map((it, i) => {
    const frac = total > 0 ? it.total / total : 0
    const len = frac * c
    const seg = jsx('circle', {
      cx: size / 2, cy: size / 2, r,
      fill: 'none',
      stroke: colorFor(i),
      strokeWidth: 16,
      strokeDasharray: `${len} ${c - len}`,
      strokeDashoffset: -offset,
      transform: `rotate(-90 ${size / 2} ${size / 2})`,
    }, it.category)
    offset += len
    return seg
  })
  return jsxs('div', {
    className: 'flex items-center gap-4',
    children: [
      jsxs('svg', { width: size, height: size, role: 'img', 'aria-label': 'Kostenarten des Monats', children: [
        jsx('circle', { cx: size / 2, cy: size / 2, r, fill: 'none', stroke: 'var(--ui-stroke-secondary)', strokeWidth: 16 }),
        ...segs,
        jsx('text', { x: '50%', y: '47%', textAnchor: 'middle', className: 'fill-current font-mono', fontSize: 11, children: eur(total) }),
        jsx('text', { x: '50%', y: '58%', textAnchor: 'middle', className: 'fill-current opacity-50', fontSize: 9, children: centerLabel }),
      ] }),
      jsx('div', { className: 'flex min-w-0 flex-1 flex-col gap-1', children: items.map((it, i) => jsxs('div', {
        className: 'flex items-baseline justify-between gap-2 font-mono text-[10px]',
        children: [
          jsxs('span', { className: 'flex min-w-0 items-baseline gap-1.5', children: [
            jsx('span', { className: 'inline-block h-2 w-2 shrink-0 rounded-full', style: { background: colorFor(i) } }),
            jsx('span', { className: 'truncate uppercase tracking-[0.06em] opacity-70', children: it.category }),
          ] }),
          jsxs('span', { children: [
            eur(it.total),
            jsxs('span', { className: 'opacity-50', children: [' · ', pct((it.total / Math.max(1, total)) * 100), ' %'] }),
          ] }),
        ],
      }, it.category)) }),
    ],
  })
}

function Card(title, badge, children) {
  return jsxs('div', {
    className: 'rounded-lg border border-(--ui-stroke-secondary) p-4',
    children: [
      jsxs('div', { className: 'mb-3 flex items-center justify-between gap-2', children: [
        jsx('div', { className: 'font-mono text-[10px] uppercase tracking-[0.1em] opacity-50', children: title }),
        badge ? jsx('span', { className: 'rounded border border-(--ui-stroke-secondary) px-2 py-0.5 font-mono text-[11px]', children: badge }) : null,
      ] }),
      children,
    ],
  })
}

// --- Untertab Rechnungen (Aufbau wie Beleg-Manager-Screenshot) --------------

const SOURCE_DE = { email: 'E-Mail', telegram: 'Telegram', upload: 'Upload' }
const SOURCE_COLORS = {
  email: 'rgba(128,128,128,0.55)',
  telegram: 'var(--ui-accent)',
  upload: 'rgba(128,128,128,0.25)',
}

function SourceBadge(source, label) {
  return jsxs('span', {
    className: 'inline-flex items-center gap-1.5 rounded-full border border-(--ui-stroke-secondary) px-2 py-0.5 font-mono text-[10px] whitespace-nowrap',
    children: [
      jsx('span', { className: 'inline-block h-1.5 w-1.5 rounded-full', style: { background: SOURCE_COLORS[source] ?? 'rgba(128,128,128,0.5)' } }),
      label,
    ],
  })
}

function KVRow(labelText, valueNode) {
  return jsxs('div', { className: 'flex justify-between gap-3 py-0.5', children: [
    jsx('span', { className: 'shrink-0 text-[11px] opacity-60', children: labelText }),
    jsx('span', { className: 'min-w-0 truncate text-right font-mono text-[11px]', title: typeof valueNode === 'string' ? valueNode : undefined, children: valueNode }),
  ] })
}

function RechnungenTab({ reloadKey }) {
  const [source, setSource] = useState('')
  const [sortAsc, setSortAsc] = useState(false)
  const [query, setQuery] = useState('')
  const [list, setList] = useState(null)
  const [counts, setCounts] = useState(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [err, setErr] = useState(null)
  const [editMode, setEditMode] = useState(null) // null | 'meta' | 'payment'
  const [form, setForm] = useState({})
  const fileRef = useRef(null)

  const load = (src, q) => {
    const params = new URLSearchParams()
    if (src) params.set('source', src)
    if (q) params.set('q', q)
    _rest(`/invoices?${params.toString()}`, { timeoutMs: 8000 })
      .then((d) => { setList(d.invoices); setCounts(d.counts); setErr(null) })
      .catch((e) => setErr(String(e?.message ?? e)))
  }

  useEffect(() => { load(source, query) }, [source, query, reloadKey])

  function openDetail(id) {
    setSelected(id)
    setDetail(null)
    _rest(`/invoices/${encodeURIComponent(id)}?pdf=true`, { timeoutMs: 15000 })
      .then((d) => setDetail(d))
      .catch((e) => setErr(String(e?.message ?? e)))
  }

  async function onUploadFile(file) {
    if (!file) return
    setUploading(true)
    setErr(null)
    try {
      const buf = await file.arrayBuffer()
      let binary = ''
      const bytes = new Uint8Array(buf)
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
      const dataBase64 = btoa(binary)
      const res = await _rest('/invoices/upload', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          dataBase64,
          source: 'upload',
          date: new Date(file.lastModified || Date.now()).toISOString().slice(0, 10),
        }),
        timeoutMs: 20000,
      })
      load(source, query)
      if (res?.invoice?.id) openDetail(res.invoice.id)
    } catch (e) {
      setErr(`Upload fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
    setUploading(false)
  }

  async function removeInvoice(id) {
    try {
      await _rest(`/invoices/${encodeURIComponent(id)}`, { method: 'DELETE', timeoutMs: 10000 })
      setSelected(null)
      setDetail(null)
      load(source, query)
    } catch (e) {
      setErr(`Entfernen fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
  }

  function revealPdf() {
    if (!detail?.filename) return
    // Backend liefert den absoluten Pfad (plattformunabhängig); Fallback: alter Pfad.
    const p = detail.filePath || `/Users/dwfb/nullaufeins/data/invoice-files/${detail.filename}`
    void _os.revealPath(p)
  }

  async function saveMeta() {
    try {
      const body = {
        vendor: form.vendor,
        subject: form.subject,
        date: form.date,
        category: form.category,
        source: form.source ?? detail.source,
      }
      const parsed = parseGermanNumber(form.amount)
      if (parsed != null) body.amountCents = parsed
      const res = await _rest(`/invoices/${encodeURIComponent(detail.id)}`, { method: 'PATCH', body: JSON.stringify(body), timeoutMs: 10000 })
      setDetail((d) => ({ ...d, ...res.invoice }))
      setEditMode(null)
      load(source, query)
      host.notify({ kind: 'info', message: 'Rechnung gespeichert' })
    } catch (e) {
      setErr(`Ändern fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
  }

  async function savePayment(assign) {
    try {
      const body = { payment: assign ? { payment_date: form.payDate ?? '', payment_description: form.payDesc ?? '' } : null }
      const res = await _rest(`/invoices/${encodeURIComponent(detail.id)}`, { method: 'PATCH', body: JSON.stringify(body), timeoutMs: 10000 })
      setDetail((d) => ({ ...d, ...res.invoice }))
      setEditMode(null)
      load(source, query)
    } catch (e) {
      setErr(`Korrigieren fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
  }

  const rows = useMemo(() => {
    const arr = (list ?? []).slice()
    arr.sort((a, b) => (sortAsc ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date)))
    return arr
  }, [list, sortAsc])

  const sum = useMemo(() => (rows ?? []).reduce((s, i) => s + Number(i.amountCents || 0), 0), [rows])
  const chipCls = (active) => ('fz-chip' + (active ? ' fz-chip--active' : ''))
  const btnCls = 'fz-btn'
  const btnPrimary = 'fz-btn fz-btn--primary'

  const filterChips = counts ? [
    { key: '', label: `Alle · ${Object.values(counts).reduce((a, b) => a + b, 0)}` },
    { key: 'email', label: `E-Mail · ${counts.email ?? 0}` },
    { key: 'telegram', label: `Telegram · ${counts.telegram ?? 0}` },
    { key: 'upload', label: `Upload · ${counts.upload ?? 0}` },
  ].map((f) => jsx('button', { type: 'button', className: chipCls(source === f.key), onClick: () => setSource(f.key), children: f.label }, f.key || 'all')) : null

  return jsxs('div', { className: 'flex flex-col gap-4', children: [
    // Toolbar oben: Upload · Filter · Sortierung · Suche
    jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
      jsx('button', { type: 'button', className: btnPrimary, disabled: uploading, onClick: () => fileRef.current?.click(),
        children: jsxs('span', { className: 'inline-flex items-center gap-1.5', children: [
          jsx('svg', { width: 14, height: 14, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor',
            strokeWidth: 1.4, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, children: [
            jsx('path', { d: 'M9.5 2 H4.8 C4.25 2 3.8 2.45 3.8 3 V13 C3.8 13.55 4.25 14 4.8 14 H11.2 C11.75 14 12.2 13.55 12.2 13 V4.7 Z' }),
            jsx('path', { d: 'M9.5 2 V4.7 H12.2' }),
            jsx('path', { d: 'M8 11.5 V7.2' }),
            jsx('path', { d: 'M6.4 8.8 L8 7.2 L9.6 8.8' }),
          ] }),
          uploading ? 'Lade hoch…' : 'Rechnung hochladen',
        ] }) }),
      jsx('input', { ref: fileRef, type: 'file', accept: 'application/pdf,image/*', hidden: true,
        onChange: (e) => { onUploadFile(e.target.files?.[0]); e.target.value = '' } }),
      jsxs('div', { className: 'flex flex-wrap items-center gap-1.5', children: filterChips }),
      jsx('button', { type: 'button', className: chipCls(false), onClick: () => setSortAsc((s) => !s),
        children: sortAsc ? 'Datum ↑' : 'Datum ↓' }),
      jsx('div', { className: 'ml-auto' }),
      jsx('input', { value: query, onChange: (e) => setQuery(e.target.value), placeholder: 'Suchen …',
        className: 'w-48 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-[12px]',
        'aria-label': 'Rechnungen durchsuchen' }),
    ] }),

    err ? jsx('div', { className: 'font-mono text-[11px]', style: { color: '#e5484d' }, children: err }) : null,

    jsxs('div', { style: { display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '1rem', alignItems: 'start' }, children: [
      // Dokumentenliste
      Card('Belege', null,
        !list
          ? jsx('div', { className: 'text-[12px] opacity-60', children: 'Lade Rechnungen …' })
          : jsxs('div', { className: 'flex flex-col', children: [
              jsx('table', { className: 'w-full text-[11px]', children: [
                jsx('thead', { children: jsxs('tr', { className: 'text-left font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: [
                  jsx('th', { className: 'py-1 pr-2 font-normal', children: 'Dokument' }),
                  jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'Betrag' }),
                  jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'Quelle' }),
                  jsx('th', { className: 'py-1 text-right font-normal', children: 'Zahlung' }),
                ] }) }),
                jsx('tbody', { children: rows.map((inv) => jsxs('tr', {
                  className: cn('cursor-pointer border-t border-(--ui-stroke-secondary) transition-colors hover:bg-(--chrome-action-hover)', selected === inv.id && 'bg-(--chrome-action-hover)'),
                  onClick: () => openDetail(inv.id),
                  children: [
                    jsxs('td', { className: 'py-1.5 pr-2', children: [
                      jsx('div', { className: 'max-w-56 truncate font-medium', children: inv.subject }),
                      jsx('div', { className: 'font-mono text-[10px] opacity-60', children: `${inv.date} · ${inv.vendor}` }),
                    ] }),
                    jsx('td', { className: 'py-1.5 pr-2 text-right font-mono whitespace-nowrap', children: `-${eur(inv.amountCents)}` }),
                    jsx('td', { className: 'py-1.5 pr-2 text-right', children: SourceBadge(inv.source, inv.sourceLabel) }),
                    jsxs('td', { className: 'py-1.5 text-right', children: [
                      inv.paymentMatch
                        ? jsxs('span', { className: 'inline-flex items-center gap-1 font-mono text-[10px]', style: { color: '#3fb950' }, children: ['✓', 'Beglichen'] })
                        : jsx('span', { className: 'font-mono text-[10px] opacity-60', children: 'Offen' }),
                    ] }),
                  ],
                }, inv.id)) }),
              ] }),
              jsxs('div', { className: 'mt-2 flex justify-between border-t border-(--ui-stroke-secondary) pt-2 font-mono text-[10px] opacity-60', children: [
                jsx('span', { children: `${rows.length} Dokumente` }),
                jsx('span', { children: `Summe -${eur(sum)}` }),
              ] }),
            ] }),
      ),

      // Detail rechts
      Card('Beleg', null,
        !selected
          ? jsx('div', { className: 'text-[12px] opacity-60', children: 'Rechnung in der Tabelle auswählen' })
          : !detail
            ? jsx('div', { className: 'text-[12px] opacity-60', children: 'Lade Detail …' })
            : jsxs('div', { className: 'flex flex-col gap-3', children: [
                // Kopf: Ablage + Schließen
                jsxs('div', { className: 'flex items-center justify-between gap-2', children: [
                  jsx('div', { className: 'font-medium', children: detail.vendor }),
                  jsxs('div', { className: 'flex items-center gap-1', children: [
                    jsx('button', { type: 'button', className: btnCls, title: 'PDF im Finder zeigen', onClick: () => revealPdf(), children: 'Ablage' }),
                    jsx('button', { type: 'button', className: btnCls, onClick: () => { setSelected(null); setDetail(null); setEditMode(null) }, children: '✕' }),
                  ] }),
                ] }),
                // Vorschau
                detail.pdfBase64
                  ? (detail.mimeType ?? 'application/pdf') === 'application/pdf'
                    ? jsx('iframe', { title: detail.filename ?? 'Beleg', src: `data:${detail.mimeType};base64,${detail.pdfBase64}`,
                        className: 'h-80 w-full rounded border border-(--ui-stroke-secondary)' })
                    : jsx('img', { alt: detail.filename ?? 'Beleg', src: `data:${detail.mimeType};base64,${detail.pdfBase64}`,
                        style: { maxWidth: '100%', maxHeight: 320, objectFit: 'contain' },
                        className: 'rounded border border-(--ui-stroke-secondary)' })
                  : jsx('div', { className: 'flex h-24 items-center justify-center rounded border border-(--ui-stroke-secondary) text-[11px] opacity-60', children: 'Keine Vorschau hinterlegt' }),
                jsx('div', { className: 'text-center font-mono text-[10px] opacity-50', children: '< 1/1 >' }),

                // Metadaten (oder Ändern-Formular)
                editMode === 'meta'
                  ? jsxs('div', { className: 'flex flex-col gap-2 rounded border border-(--ui-stroke-secondary) p-3', children: [
                      jsx('div', { className: 'font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: 'Metadaten ändern' }),
                      ...[['vendor', 'Lieferant'], ['subject', 'Beschreibung'], ['date', 'Belegdatum (JJJJ-MM-TT)'], ['amount', 'Betrag (z. B. 29,42)'], ['category', 'Kategorie']].map(([key, lbl]) => jsxs('label', {
                        className: 'flex items-center justify-between gap-2', children: [
                          jsx('span', { className: 'text-[11px] opacity-60', children: lbl }),
                          jsx('input', { value: form[key] ?? '', onChange: (e) => setForm((f) => ({ ...f, [key]: e.target.value })),
                            className: 'w-40 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-right font-mono text-[11px]' }),
                        ], }, key)),
                      jsxs('label', { className: 'flex items-center justify-between gap-2', children: [
                        jsx('span', { className: 'text-[11px] opacity-60', children: 'Quelle' }),
                        jsx('select', { value: form.source ?? detail.source, onChange: (e) => setForm((f) => ({ ...f, source: e.target.value })),
                          className: 'rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[11px]', children: [
                            jsx('option', { value: 'email', children: 'E-Mail' }),
                            jsx('option', { value: 'telegram', children: 'Telegram' }),
                            jsx('option', { value: 'upload', children: 'Upload' }),
                          ] }),
                      ] }),
                      jsxs('div', { className: 'flex gap-2', children: [
                        jsx('button', { type: 'button', className: btnCls, onClick: () => void saveMeta(), children: 'Speichern' }),
                        jsx('button', { type: 'button', className: btnCls, onClick: () => setEditMode(null), children: 'Abbrechen' }),
                      ] }),
                    ] })
                  : jsxs('div', { className: 'rounded border border-(--ui-stroke-secondary) p-3', children: [
                      KVRow('Beschreibung', detail.subject),
                      KVRow('Belegdatum', detail.date),
                      KVRow('Betrag', `-${eur(detail.amountCents)}`),
                      KVRow('Kategorie', detail.category),
                      jsxs('div', { className: 'flex items-center justify-between gap-3 py-0.5', children: [
                        jsx('span', { className: 'text-[11px] opacity-60', children: 'Quelle' }),
                        SourceBadge(detail.source, detail.sourceLabel),
                      ] }),
                    ] }),

                // Zahlung (oder Korrigieren-Formular)
                editMode === 'payment'
                  ? jsxs('div', { className: 'flex flex-col gap-2 rounded border border-(--ui-stroke-secondary) p-3', children: [
                      jsx('div', { className: 'font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: 'Zahlungszuordnung korrigieren' }),
                      jsxs('label', { className: 'flex items-center justify-between gap-2', children: [
                        jsx('span', { className: 'text-[11px] opacity-60', children: 'Zahlungsdatum' }),
                        jsx('input', { value: form.payDate ?? detail.payment?.payment_date ?? '', onChange: (e) => setForm((f) => ({ ...f, payDate: e.target.value })),
                          placeholder: 'JJJJ-MM-TT', className: 'w-40 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-right font-mono text-[11px]' }),
                      ] }),
                      jsxs('label', { className: 'flex items-center justify-between gap-2', children: [
                        jsx('span', { className: 'text-[11px] opacity-60', children: 'Verwendung' }),
                        jsx('input', { value: form.payDesc ?? detail.payment?.payment_description ?? '', onChange: (e) => setForm((f) => ({ ...f, payDesc: e.target.value })),
                          className: 'w-40 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-right font-mono text-[11px]' }),
                      ] }),
                      jsxs('div', { className: 'flex flex-wrap gap-2', children: [
                        jsx('button', { type: 'button', className: btnCls, onClick: () => void savePayment(true), children: 'Zuordnen' }),
                        detail.payment ? jsx('button', { type: 'button', className: btnCls, onClick: () => void savePayment(false), children: 'Zuordnung entfernen' }) : null,
                        jsx('button', { type: 'button', className: btnCls, onClick: () => setEditMode(null), children: 'Abbrechen' }),
                      ] }),
                    ] })
                  : jsxs('div', { className: 'rounded border border-(--ui-stroke-secondary) p-3', children: [
                      detail.payment
                        ? jsxs('div', { className: 'flex flex-col gap-0.5', children: [
                            jsxs('div', { className: 'flex items-center gap-1.5 font-mono text-[10px]', style: { color: '#3fb950' }, children: ['✓', detail.payment.confidence === 'manual' ? 'Manuell zugeordnet' : 'Automatisch zugeordnet'] }),
                            KVRow('Verwendung', detail.payment.payment_description),
                            KVRow('Datum', detail.payment.payment_date),
                          ] })
                        : jsx('div', { className: 'font-mono text-[10px] opacity-60', children: 'Keine Zahlung zugeordnet' }),
                    ] }),

                // Aktionen: Ändern · Korrigieren · Entfernen
                jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
                  jsx('button', { type: 'button', className: btnCls, onClick: () => { setForm({ vendor: detail.vendor, subject: detail.subject, date: detail.date, amount: (detail.amountCents / 100).toLocaleString('de-DE', { minimumFractionDigits: 2 }), category: detail.category, source: detail.source }); setEditMode('meta') }, children: 'Ändern…' }),
                  jsx('button', { type: 'button', className: btnCls, onClick: () => { setEditMode('payment') }, children: 'Korrigieren…' }),
                  jsx('button', { type: 'button', className: btnCls + ' fz-btn--danger', onClick: () => { if (window.confirm('Rechnung wirklich entfernen?')) void removeInvoice(detail.id) }, children: 'Entfernen…' }),
                ] }),
              ] }),
      ),
      ],
    }),
  ] })
}

// --- Untertab Tagebuch (täglich Einnahmen/Ausgaben erfassen) -----------------

function thisDay() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function shiftDay(date, days) {
  const [y, m, d] = date.split('-').map(Number)
  const dt = new Date(y, m - 1, d + days)
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
}

function shiftMonth(month, delta) {
  const [y, m] = month.split('-').map(Number)
  const dt = new Date(y, m - 1 + delta, 1)
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`
}

function DayChart(days, today) {
  // Balken je Tag: oben Einnahmen, unten Ausgaben (Spiegelsäulen um Nulllinie).
  if (!days.length) return jsx('div', { className: 'text-[12px] opacity-60', children: 'Noch keine Einträge in diesem Monat' })
  const max = Math.max(1, ...days.map((d) => Math.max(d.incomeCents, d.expenseCents)))
  const H = 70
  const dayRows = days.slice().sort((a, b) => a.date.localeCompare(b.date))
  return jsxs('div', { className: 'flex items-end gap-[3px] overflow-x-auto pb-1', role: 'img', 'aria-label': 'Täglich Einnahmen und Ausgaben', children: dayRows.map((d) => {
    const isToday = d.date === today
    const hIn = Math.max(1, Math.round((d.incomeCents / max) * (H / 2)))
    const hOut = Math.max(1, Math.round((d.expenseCents / max) * (H / 2)))
    return jsxs('div', {
      title: `${d.date} · +${eur(d.incomeCents)} / -${eur(d.expenseCents)}`,
      className: 'flex w-4 shrink-0 flex-col items-center gap-[2px]',
      children: [
        jsx('div', { style: { height: hIn, width: '100%', background: 'var(--ui-accent)', borderRadius: 2, opacity: isToday ? 1 : 0.55 } }),
        jsx('div', { className: 'font-mono text-[8px] opacity-50', children: d.date.slice(8) }),
        jsx('div', { style: { height: hOut, width: '100%', background: 'rgba(128,128,128,0.7)', borderRadius: 2, opacity: isToday ? 1 : 0.55 } }),
      ],
    }, d.date)
  }) })
}

function BigStat(labelText, cents, accent) {
  return jsxs('div', { className: 'flex flex-col gap-1 rounded-lg border border-(--ui-stroke-secondary) p-3', children: [
    jsx('div', { className: 'font-mono text-[10px] uppercase tracking-[0.1em] opacity-50', children: labelText }),
    jsx('div', { className: 'font-mono text-[18px] font-semibold', style: accent ? { color: 'var(--ui-accent)' } : undefined, children: eur(cents) }),
  ] })
}

function TagebuchTab() {
  const [day, setDay] = useState(thisDay())
  const month = day.slice(0, 7)
  const [kind, setKind] = useState('expense')
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [receipt, setReceipt] = useState(null) // {name, base64}
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [err, setErr] = useState(null)
  const [preview, setPreview] = useState(null) // {mimeType, base64}
  const fileRef = useRef(null)

  const load = (m) => {
    _rest(`/daily?month=${encodeURIComponent(m)}`, { timeoutMs: 8000 })
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(String(e?.message ?? e)))
  }
  useEffect(() => { load(month) }, [month])

  async function addItem() {
    if (String(amount).trim() === '') {
      setErr('Bitte einen Betrag angeben.')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const body = { date: day, kind, amount, label: label.trim() || (kind === 'income' ? 'Einnahme' : 'Ausgabe') }
      if (receipt) { body.receiptBase64 = receipt.base64; body.receiptName = receipt.name }
      await _rest('/daily/item', { method: 'POST', body: JSON.stringify(body), timeoutMs: 20000 })
      setMsg(`Buchung für ${day} gespeichert`)
      setLabel('')
      setAmount('')
      setReceipt(null)
      load(month)
    } catch (e) {
      setErr(`Speichern fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
    setBusy(false)
  }

  async function removeItem(it) {
    if (!window.confirm(`„${it.label || (it.kind === 'income' ? 'Einnahme' : 'Ausgabe')}" (${eur(it.amountCents)}) entfernen?`)) return
    try {
      await _rest(`/daily/item/${it.id}`, { method: 'DELETE', timeoutMs: 10000 })
      load(month)
    } catch (e) {
      setErr(`Entfernen fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
  }

  async function openReceipt(it) {
    setPreview(null)
    try {
      const d = await _rest(`/daily/item/${it.id}/receipt`, { timeoutMs: 10000 })
      setPreview(d)
    } catch (e) {
      setErr(`Bon laden fehlgeschlagen: ${String(e?.message ?? e)}`)
    }
  }

  function onReceiptFile(file) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setReceipt({ name: file.name, base64: String(reader.result).split(',')[1] ?? '' })
    reader.readAsDataURL(file)
  }

  const btnCls = 'fz-btn'
  const btnPrimary = 'fz-btn fz-btn--primary'
  const chip = (active) => 'fz-chip' + (active ? ' fz-chip--active' : '')
  const isToday = day === thisDay()
  const mtd = data?.monthToDate ?? { incomeCents: 0, expenseCents: 0, netCents: 0 }
  const dayAgg = (data?.days ?? []).find((d) => d.date === day) ?? { incomeCents: 0, expenseCents: 0, items: [] }

  const itemRow = (it, withDate) => jsxs('div', { className: 'flex items-center justify-between gap-2 border-t border-(--ui-stroke-secondary) py-1.5 first:border-t-0', children: [
    jsxs('div', { className: 'flex min-w-0 items-baseline gap-2', children: [
      withDate ? jsx('span', { className: 'shrink-0 font-mono text-[10px] opacity-50', children: it.date }) : null,
      jsx('span', { className: cn('truncate text-[12px]', it.kind === 'income' && 'font-medium'), children: it.label || (it.kind === 'income' ? 'Einnahme' : 'Ausgabe') }),
      it.hasReceipt
        ? jsx('button', { type: 'button', className: chip(false), onClick: () => void openReceipt(it), children: 'Bon' })
        : null,
    ] }),
    jsxs('div', { className: 'flex shrink-0 items-center gap-2 font-mono text-[11px] whitespace-nowrap', children: [
      it.kind === 'income'
        ? jsx('span', { children: `+${eur(it.amountCents)}` })
        : jsx('span', { style: { opacity: 0.75 }, children: `-${eur(it.amountCents)}` }),
      jsx('button', { type: 'button', className: btnCls + ' fz-btn--danger', onClick: () => void removeItem(it), children: '✕' }),
    ] }),
  ] }, `${it.id}-${withDate ? it.date : ''}`)

  return jsxs('div', { className: 'flex flex-col gap-4', children: [
    // Tages-Navigation: Tag wählbar/rückdatierbar, Monat wechselt automatisch mit
    jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
      jsx('button', { type: 'button', className: btnCls, onClick: () => setDay(shiftDay(day, -1)), children: '← Tag zurück' }),
      jsx('button', { type: 'button', className: btnCls, disabled: day >= thisDay(), onClick: () => setDay(shiftDay(day, 1)), children: 'Tag vor →' }),
      jsx('input', { type: 'date', value: day, onChange: (e) => e.target.value && setDay(e.target.value),
        className: 'rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[12px]', 'aria-label': 'Tag wählen' }),
      !isToday ? jsx('button', { type: 'button', className: btnCls, onClick: () => setDay(thisDay()), children: 'Heute' }) : null,
      jsx('button', { type: 'button', className: btnCls, onClick: () => setDay(shiftMonth(month, -1) + '-01'), children: '← Monat zurück' }),
      jsx('button', { type: 'button', className: btnCls, disabled: month >= thisDay().slice(0, 7), onClick: () => setDay(shiftMonth(month, 1) + '-01'), children: 'Monat vor →' }),
      jsx('span', { className: 'font-medium', children: data ? data.monthLabel : month }),
    ] }),

    err ? jsx('div', { className: 'font-mono text-[11px]', style: { color: '#e5484d' }, children: err }) : null,

    // Dashboard: Einnahmen/Ausgaben des gesamten Monats bis heute
    jsxs(Fragment, { children: [
      jsxs('div', { className: 'font-mono text-[10px] uppercase tracking-[0.1em] opacity-50',
        children: isToday && month === thisDay().slice(0, 7) ? 'Monat bis heute' : data ? data.monthLabel : month }),
      jsx('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }, children: [
        BigStat('Verdient', mtd.incomeCents, true),
        BigStat('Ausgegeben', mtd.expenseCents),
        BigStat('Saldo', mtd.netCents),
      ] }),
    ] }),

    // Buchung erfassen + Einträge des Tages (volle Breite)
    Card(`Einträge · ${day}`, isToday ? 'Heute' : null,
        jsxs('div', { className: 'flex flex-col gap-2', children: [
          jsxs('div', { className: 'flex flex-wrap items-center gap-1.5', children: [
            jsx('button', { type: 'button', className: chip(kind === 'expense'), onClick: () => setKind('expense'), children: 'Ausgabe' }),
            jsx('button', { type: 'button', className: chip(kind === 'income'), onClick: () => setKind('income'), children: 'Einnahme' }),
          ] }),
          jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
            jsx('input', { value: label, onChange: (e) => setLabel(e.target.value), placeholder: kind === 'income' ? 'Wofür? (z. B. Rechnung Kunde X)' : 'Wofür? (z. B. Bäckerei)',
              className: 'min-w-40 flex-1 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-[12px]',
              'aria-label': 'Bezeichnung' }),
            jsx('input', { value: amount, onChange: (e) => setAmount(e.target.value), placeholder: '0,00', inputMode: 'decimal',
              className: 'w-28 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-right font-mono text-[12px]',
              'aria-label': 'Betrag', onKeyDown: (e) => { if (e.key === 'Enter') void addItem() } }),
          ] }),
          jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
            jsx('button', { type: 'button', className: btnPrimary, disabled: busy, onClick: () => void addItem(),
              children: busy ? 'Speichere…' : 'Hinzufügen' }),
            jsx('button', { type: 'button', className: btnCls, onClick: () => fileRef.current?.click(),
              children: receipt ? `Bon: ${receipt.name.length > 18 ? receipt.name.slice(0, 16) + '…' : receipt.name}` : 'Bon/Kassenbon anhängen' }),
            receipt ? jsx('button', { type: 'button', className: btnCls, onClick: () => setReceipt(null), children: '✕' }) : null,
            jsx('input', { ref: fileRef, type: 'file', accept: 'application/pdf,image/*', hidden: true,
              onChange: (e) => { onReceiptFile(e.target.files?.[0]); e.target.value = '' } }),
            msg ? jsx('span', { className: 'font-mono text-[10px] opacity-50', children: msg }) : null,
          ] }),

          jsxs('div', { className: 'mt-1 border-t border-(--ui-stroke-secondary) pt-2', children: [
            jsx('div', { className: 'mb-1 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: [
              jsx('span', { children: `Buchungen dieses Tags · ${dayAgg.items.length}` }),
              dayAgg.items.length ? jsx('span', { children: `+${eur(dayAgg.incomeCents)} / -${eur(dayAgg.expenseCents)}` }) : null,
            ] }),
            dayAgg.items.length
              ? jsx('div', { className: 'flex flex-col', children: dayAgg.items.map((it) => itemRow(it, false)) })
              : jsx('div', { className: 'text-[12px] opacity-60', children: 'Noch keine Buchungen an diesem Tag' }),
          ] }),

          // Bon-Vorschau
          preview
            ? jsxs('div', { className: 'rounded border border-(--ui-stroke-secondary) p-2', children: [
                jsxs('div', { className: 'mb-1 flex items-center justify-between', children: [
                  jsx('span', { className: 'font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: 'Bon' }),
                  jsx('button', { type: 'button', className: btnCls, onClick: () => setPreview(null), children: '✕' }),
                ] }),
                preview.mimeType === 'application/pdf'
                  ? jsx('iframe', { title: 'Bon', src: `data:application/pdf;base64,${preview.base64}`, className: 'h-72 w-full rounded' })
                  : jsx('img', { alt: 'Bon', src: `data:${preview.mimeType};base64,${preview.base64}`, style: { maxWidth: '100%', maxHeight: 320, objectFit: 'contain' } }),
              ] })
            : null,

          jsx('div', { className: 'border-t border-(--ui-stroke-secondary) pt-2 font-mono text-[10px] opacity-50',
            children: 'Buchungen sammeln sich automatisch in der Monatsrechnung (BWA).' }),
        ] })),
  ] })
}

// --- Untertabs SuSa / OPOS / Vorjahresvergleich / Vorschläge -----------------

const eur2 = (n) => Number(n || 0).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function EditableCell({ value, onCommit, numeric, width }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  if (!editing) {
    return jsx('td', {
      className: cn('py-1 pr-2 cursor-text hover:bg-(--chrome-action-hover)', numeric && 'text-right font-mono whitespace-nowrap'),
      style: width ? { maxWidth: width } : undefined,
      title: 'Klicken zum Bearbeiten',
      onClick: () => { setDraft(String(value ?? '')); setEditing(true) },
      children: numeric ? eur2(value) : (value || ''),
    })
  }
  return jsx('td', { className: 'py-0.5 pr-2', children: jsx('input', {
    autoFocus: true,
    value: draft,
    inputMode: numeric ? 'decimal' : 'text',
    onChange: (e) => setDraft(e.target.value),
    onBlur: () => { setEditing(false); onCommit(numeric ? parseGermanNumber(draft) : draft) },
    onKeyDown: (e) => {
      if (e.key === 'Enter') { setEditing(false); onCommit(numeric ? parseGermanNumber(draft) : draft) }
      if (e.key === 'Escape') setEditing(false)
    },
    className: 'w-full rounded border border-(--ui-accent) bg-transparent px-1 py-0.5 text-right font-mono text-[11px]',
  }) })
}

function MonthPicker({ months, month, onChange, allowCurrent }) {
  const list = useMemo(() => {
    const ms = (months ?? []).slice()
    const cur = thisMonth()
    if (allowCurrent && !ms.includes(cur)) ms.push(cur)
    ms.sort()
    return ms
  }, [months, allowCurrent])
  return jsx('select', {
    value: month ?? '',
    onChange: (e) => onChange(e.target.value),
    className: 'rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[12px]',
    'aria-label': 'Monat wählen',
    children: list.map((m) => jsx('option', { value: m, children: label(m) }, m)),
  })
}

function SusaTab({ reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({})
  const [blatt, setBlatt] = useState(1)
  const [query, setQuery] = useState('')
  const [nurBelegt, setNurBelegt] = useState(true)

  const load = (m) => {
    _rest(`/report/susa${m ? `?month=${m}` : ''}`, { timeoutMs: 8000 })
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(String(e?.message ?? e)))
  }
  useEffect(() => { load(data?.month) }, [reloadKey])

  async function commit(id, field, value) {
    if (value == null || value === '' || value === 0 && field === 'beschriftung') return
    const body = field === 'konto' ? { konto: value } : field === 'beschriftung' ? { beschriftung: value }
      : field === 'eb' ? { ebWert: value } : field === 'sollM' ? { sollMonat: value }
      : field === 'habenM' ? { habenMonat: value } : field === 'sollK' ? { sollKum: value }
      : { habenKum: value }
    try {
      await _rest(`/report/susa/${id}`, { method: 'PATCH', body: JSON.stringify(body), timeoutMs: 8000 })
      load(data.month)
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  async function removeRow(id) {
    try {
      await _rest(`/report/susa/${id}`, { method: 'DELETE', timeoutMs: 8000 })
      load(data.month)
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  async function addRow() {
    try {
      await _rest('/report/susa', { method: 'POST', timeoutMs: 8000, body: JSON.stringify({
        month: data.month,
        konto: form.konto,
        beschriftung: form.beschriftung,
        ebWert: parseGermanNumber(form.eb ?? '') ?? 0,
        sollMonat: parseGermanNumber(form.sollM ?? '') ?? 0,
        habenMonat: parseGermanNumber(form.habenM ?? '') ?? 0,
        sollKum: parseGermanNumber(form.sollK ?? '') ?? 0,
        habenKum: parseGermanNumber(form.habenK ?? '') ?? 0,
      }) })
      setAdding(false); setForm({})
      load(data.month)
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  if (err && !data) return jsx('div', { className: 'text-[12px]', style: { color: '#e5484d' }, children: err })
  if (!data) return jsx('div', { className: 'text-[12px] opacity-60', children: 'Lade SuSa …' })

  const saldo = (e) => (e.eb_sh === 'S' ? e.eb_wert : -e.eb_wert) + e.soll_kum - e.haben_kum

  const BLATT_LABELS = { 1: 'Blatt 1 · Kl. 0–3', 2: 'Blatt 2 · Kl. 3–6', 3: 'Blatt 3 · Kl. 6–9', 4: 'Kreditoren' }
  const all = data.entries ?? []
  const blatts = [...new Set(all.map((e) => e.blatt))]
  const q = query.trim().toLowerCase()
  const isBelegt = (e) => ['eb_wert', 'soll_monat', 'haben_monat', 'soll_kum', 'haben_kum']
    .some((f) => Math.abs(Number(e[f] || 0)) > 0.004)
  const shown = all
    .filter((e) => e.blatt === blatt)
    .filter((e) => e.is_sum ? (!q && !nurBelegt) : (!q || `${e.konto} ${e.beschriftung}`.toLowerCase().includes(q)))
    .filter((e) => e.is_sum || !nurBelegt || isBelegt(e))
    .filter((e) => !(e.is_sum && e.beschriftung.startsWith('Summe Gruppe')) || q === '')
  // Summen der anderen Blätter gehoerten nicht in die Auswahl — nur die des aktiven Blatts am Ende:
  const rows = []
  let lastKlasse = null
  for (const e of shown) {
    if (e.is_sum) { rows.push({ type: 'sum', e }); continue }
    const k = e.is_kreditor ? 'Kreditoren' : `Klasse ${Math.min(Math.floor(Number(e.konto) / 1000), 9)}`
    if (k !== lastKlasse) { rows.push({ type: 'klasse', label: k }); lastKlasse = k }
    rows.push({ type: 'entry', e })
  }

  const chipCls = (active) => ('fz-chip' + (active ? ' fz-chip--active' : ''))
  const num = 'py-1 pr-2 text-right font-mono text-[11px] whitespace-nowrap'

  const tableHead = jsxs('tr', { className: 'text-left font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: [
    jsx('th', { className: 'py-1 pr-2 font-normal', children: 'Konto' }),
    jsx('th', { className: 'py-1 pr-2 font-normal', children: 'Beschriftung' }),
    jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'EB-Wert' }),
    jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'Soll' }),
    jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'Haben' }),
    jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'kum. Soll' }),
    jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'kum. Haben' }),
    jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'Saldo' }),
    jsx('th', { className: 'py-1 font-normal', children: '' }),
  ] })

  return jsxs('div', { className: 'flex flex-col gap-3', children: [
    jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
      jsx(MonthPicker, { months: data.months, month: data.month, onChange: (m) => load(m), allowCurrent: true }, 'mp'),
      jsx('button', { type: 'button', className: 'fz-btn', onClick: () => setAdding((a) => !a), children: adding ? 'Abbrechen' : '+ Konto' }),
      jsx('div', { className: 'ml-auto' }),
      jsx('input', { value: query, onChange: (e) => setQuery(e.target.value), placeholder: 'Konto / Text suchen …',
        className: 'w-44 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 text-[12px]',
        'aria-label': 'SuSa durchsuchen' }),
    ] }),
    jsxs('div', { className: 'flex flex-wrap items-center gap-1.5', children: [
      blatts.map((b) => jsx('button', { type: 'button', className: chipCls(blatt === b),
        onClick: () => setBlatt(b), children: BLATT_LABELS[b] ?? `Blatt ${b}` }, b)),
      jsx('button', { type: 'button', className: chipCls(nurBelegt), onClick: () => setNurBelegt((v) => !v),
        children: nurBelegt ? '✓ Nur belegte Konten' : 'Nur belegte Konten' }),
    ] }),
    err ? jsx('div', { className: 'font-mono text-[11px]', style: { color: '#e5484d' }, children: err }) : null,
    adding ? jsxs('div', { className: 'flex flex-wrap items-end gap-2 rounded border border-(--ui-stroke-secondary) p-3', children: [
      ...[['konto', 'Konto', '6850'], ['beschriftung', 'Beschriftung', 'Sonstiger Betriebsbedarf'], ['eb', 'EB-Wert', '0'], ['sollM', 'Soll (Monat)', ''], ['habenM', 'Haben (Monat)', ''], ['sollK', 'kum. Soll', ''], ['habenK', 'kum. Haben', '']].map(([key, lbl, ph]) => jsxs('label', { className: 'flex flex-col gap-1', children: [
        jsx('span', { className: 'font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: lbl }),
        jsx('input', { value: form[key] ?? '', placeholder: ph, onChange: (e) => setForm((f) => ({ ...f, [key]: e.target.value })),
          className: 'w-32 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[11px]' }),
      ] }, key)),
      jsx('button', { type: 'button', className: 'fz-btn fz-btn--primary', onClick: () => void addRow(), children: 'Hinzufügen' }),
    ] }) : null,
    jsx('div', { className: 'rounded-lg border border-(--ui-stroke-secondary) p-3', children:
      jsx('table', { className: 'w-full text-[11px]', children: [
        jsx('thead', { children: tableHead }),
        jsx('tbody', { children: rows.map((r, i) => r.type === 'klasse'
          ? jsxs('tr', { children: [
              jsx('td', { colSpan: 9, className: 'pt-3 pb-1 font-mono text-[10px] uppercase tracking-[0.1em] opacity-40', children: r.label }),
            ] }, `kl-${i}`)
          : r.type === 'sum'
            ? jsxs('tr', { className: 'border-t border-(--ui-accent) font-semibold', children: [
                jsx('td', { className: 'py-1.5 pr-2' }),
                jsx('td', { className: 'py-1.5 pr-2', children: r.e.beschriftung }),
                jsx('td', { className: num, children: eur2(r.e.eb_wert) }),
                jsx('td', { className: num, children: eur2(r.e.soll_monat) }),
                jsx('td', { className: num, children: eur2(r.e.haben_monat) }),
                jsx('td', { className: num, children: eur2(r.e.soll_kum) }),
                jsx('td', { className: num, children: eur2(r.e.haben_kum) }),
                jsx('td', { className: num }),
                jsx('td', {}),
              ] }, `sum-${i}`)
            : jsxs('tr', { className: cn('border-t border-(--ui-stroke-secondary) hover:bg-(--chrome-action-hover)', r.e.invoice_id && 'bg-(--chrome-action-hover)'), children: [
                jsx(EditableCell, { value: r.e.konto, onCommit: (v) => commit(r.e.id, 'konto', v), width: 60 }, `k${r.e.id}`),
                jsx(EditableCell, { value: r.e.beschriftung, onCommit: (v) => commit(r.e.id, 'beschriftung', v) }, `b${r.e.id}`),
                jsx(EditableCell, { value: r.e.eb_wert, numeric: true, onCommit: (v) => commit(r.e.id, 'eb', v) }, `eb${r.e.id}`),
                jsx(EditableCell, { value: r.e.soll_monat, numeric: true, onCommit: (v) => commit(r.e.id, 'sollM', v) }, `sm${r.e.id}`),
                jsx(EditableCell, { value: r.e.haben_monat, numeric: true, onCommit: (v) => commit(r.e.id, 'habenM', v) }, `hm${r.e.id}`),
                jsx(EditableCell, { value: r.e.soll_kum, numeric: true, onCommit: (v) => commit(r.e.id, 'sollK', v) }, `sk${r.e.id}`),
                jsx(EditableCell, { value: r.e.haben_kum, numeric: true, onCommit: (v) => commit(r.e.id, 'habenK', v) }, `hk${r.e.id}`),
                jsx('td', { className: num, children: eur2(saldo(r.e)) }),
                jsx('td', { className: 'py-1 text-right', children:
                  jsx('button', { type: 'button', className: 'fz-btn fz-btn--danger px-1.5 py-0.5', title: 'Zeile löschen',
                    onClick: () => void removeRow(r.e.id), children: '✕' }) }),
              ] }, r.e.id)) }),
      ] }) }),
    jsx('div', { className: 'font-mono text-[10px] opacity-50', children: 'Zellen anklicken zum Bearbeiten · Enter bestätigt, Esc bricht ab · Summen werden automatisch berechnet' }),
  ] })
}

function OposTab({ reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({})

  const load = (m) => {
    _rest(`/report/opos${m ? `?month=${m}` : ''}`, { timeoutMs: 8000 })
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(String(e?.message ?? e)))
  }
  useEffect(() => { load(data?.month) }, [reloadKey])

  async function commit(id, key, value) {
    if (value == null) return
    const body = key === 'betrag' ? { betrag: value } : { [key]: value }
    try {
      await _rest(`/report/opos/${id}`, { method: 'PATCH', body: JSON.stringify(body), timeoutMs: 8000 })
      load(data.month)
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  async function addRow() {
    try {
      await _rest('/report/opos', { method: 'POST', timeoutMs: 8000, body: JSON.stringify({
        month: data.month, konto: form.konto ?? '', beschriftung: form.beschriftung ?? '',
        rechnungsNr: form.rechnungsNr ?? '', datum: form.datum ?? '',
        faelligkeit: form.faelligkeit ?? '', betrag: parseGermanNumber(form.betrag ?? '') ?? 0,
        buchungstext: form.buchungstext ?? '',
      }) })
      setAdding(false); setForm({})
      load(data.month)
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  if (err && !data) return jsx('div', { className: 'text-[12px]', style: { color: '#e5484d' }, children: err })
  if (!data) return jsx('div', { className: 'text-[12px] opacity-60', children: 'Lade OPOS-Liste …' })

  const total = (data.entries ?? []).reduce((s, e) => s + Number(e.betrag || 0), 0)
  const cols = [['konto', 'Konto', false], ['beschriftung', 'Beschriftung', false], ['rechnungs_nr', 'Rechnungs-Nr.', false],
    ['datum', 'Datum', false], ['faelligkeit', 'Fälligkeit', false], ['betrag', 'Betrag', true], ['buchungstext', 'Buchungstext', false]]

  return jsxs('div', { className: 'flex flex-col gap-3', children: [
    jsxs('div', { className: 'flex flex-wrap items-center gap-2', children: [
      jsx(MonthPicker, { months: data.months, month: data.month, onChange: (m) => load(m), allowCurrent: true }, 'mp'),
      jsx('button', { type: 'button', className: 'fz-btn', onClick: () => setAdding((a) => !a), children: adding ? 'Abbrechen' : '+ Posten' }),
    ] }),
    err ? jsx('div', { className: 'font-mono text-[11px]', style: { color: '#e5484d' }, children: err }) : null,
    adding ? jsxs('div', { className: 'flex flex-wrap items-end gap-2 rounded border border-(--ui-stroke-secondary) p-3', children: [
      ...[['konto', 'Konto'], ['beschriftung', 'Beschriftung'], ['rechnungsNr', 'Rechnungs-Nr.'], ['datum', 'Datum (JJJJ-MM-TT)'], ['faelligkeit', 'Fälligkeit'], ['betrag', 'Betrag'], ['buchungstext', 'Buchungstext']].map(([key, lbl]) => jsxs('label', { className: 'flex flex-col gap-1', children: [
        jsx('span', { className: 'font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: lbl }),
        jsx('input', { value: form[key] ?? '', onChange: (e) => setForm((f) => ({ ...f, [key]: e.target.value })),
          className: 'w-32 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[11px]' }),
      ] }, key)),
      jsx('button', { type: 'button', className: 'fz-btn fz-btn--primary', onClick: () => void addRow(), children: 'Hinzufügen' }),
    ] }) : null,
    Card(`Offene Posten · ${data.month ? label(data.month) : ''}`, `${eur2(total)} € offen`,
      !(data.entries ?? []).length
        ? jsx('div', { className: 'text-[12px] opacity-60', children: 'Keine Posten vorhanden — die Liste ist leer.' })
        : jsx('table', { className: 'w-full text-[11px]', children: [
            jsx('thead', { children: jsxs('tr', { className: 'text-left font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: [
              ...cols.map(([key, lbl]) => jsx('th', { className: 'py-1 pr-2 font-normal', children: lbl }, key)),
              jsx('th', {}),
            ] }) }),
            jsx('tbody', { children: data.entries.map((e) => jsxs('tr', { className: 'border-t border-(--ui-stroke-secondary)', children: [
              ...cols.map(([key,, numeric]) => jsx(EditableCell, { value: e[key], numeric, onCommit: (v) => commit(e.id, key === 'rechnungs_nr' ? 'rechnungsNr' : key, v) }, `${key}-${e.id}`)),
              jsx('td', { className: 'py-1 text-right', children:
                jsx('button', { type: 'button', className: 'fz-btn fz-btn--danger px-1.5 py-0.5', title: 'Posten löschen',
                  onClick: () => void _rest(`/report/opos/${e.id}`, { method: 'DELETE', timeoutMs: 8000 }).then(() => load(data.month)).catch((er) => setErr(String(er?.message ?? er))), children: '✕' }) }),
            ] }, e.id)) }),
          ] })),
  ] })
}

function VvTab({ reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    _rest(`/report/vv?month=${thisMonth()}`, { timeoutMs: 8000 })
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(String(e?.message ?? e)))
  }, [reloadKey])
  if (err) return jsx('div', { className: 'text-[12px]', style: { color: '#e5484d' }, children: err })
  if (!data) return jsx('div', { className: 'text-[12px] opacity-60', children: 'Lade Vorjahresvergleich …' })
  const fmtPct = (p) => (p == null ? '—' : `${pct(p)} %`)
  return Card(`Vorjahresvergleich · ${label(data.month)} vs. ${label(data.prevMonth)}`, null,
    jsx('table', { className: 'w-full text-[11px]', children: [
      jsx('thead', { children: jsxs('tr', { className: 'text-left font-mono text-[10px] uppercase tracking-[0.08em] opacity-50', children: [
        jsx('th', { className: 'py-1 pr-2 font-normal', children: 'Bezeichnung' }),
        jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: label(data.month) }),
        jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: label(data.prevMonth) }),
        jsx('th', { className: 'py-1 pr-2 text-right font-normal', children: 'Veränderung' }),
        jsx('th', { className: 'py-1 text-right font-normal', children: 'in %' }),
      ] }) }),
      jsx('tbody', { children: data.lines.map((l) => jsxs('tr', { className: 'border-t border-(--ui-stroke-secondary)', children: [
        jsx('td', { className: 'py-1 pr-2', style: { paddingLeft: l.label.startsWith('  ') ? 12 : 0 }, children: l.label.trim() }),
        jsx('td', { className: 'py-1 pr-2 text-right font-mono', children: eur2(l.current) }),
        jsx('td', { className: 'py-1 pr-2 text-right font-mono opacity-70', children: eur2(l.prev) }),
        jsx('td', { className: 'py-1 pr-2 text-right font-mono', style: { color: l.delta < 0 ? '#e5484d' : '#3fb950' }, children: eur2(l.delta) }),
        jsx('td', { className: 'py-1 text-right font-mono', children: fmtPct(l.pct) }),
      ] }, l.key)) }),
    ] }))
}

function VorschlaegeTab({ reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [bookForm, setBookForm] = useState(null) // {invoiceId, konto, month, opos}

  const load = () => {
    _rest('/report/proposals', { timeoutMs: 8000 })
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(String(e?.message ?? e)))
  }
  useEffect(() => { load() }, [reloadKey])

  async function confirmBook() {
    try {
      await _rest('/report/book', { method: 'POST', timeoutMs: 10000, body: JSON.stringify({
        invoiceId: bookForm.invoiceId, konto: bookForm.konto, month: bookForm.month, opos: !!bookForm.opos,
      }) })
      setBookForm(null)
      host.notify({ kind: 'info', message: 'Rechnung gebucht' })
      load()
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  async function reject(id) {
    try {
      await _rest(`/invoices/${encodeURIComponent(id)}`, { method: 'DELETE', timeoutMs: 10000 })
      load()
    } catch (e) { setErr(String(e?.message ?? e)) }
  }

  if (!data) return jsx('div', { className: 'text-[12px] opacity-60', children: 'Lade Vorschläge …' })
  return jsxs('div', { className: 'flex flex-col gap-3', children: [
    err ? jsx('div', { className: 'font-mono text-[11px]', style: { color: '#e5484d' }, children: err }) : null,
    !(data.proposals ?? []).length
      ? Card('Buchungsvorschläge', null,
          jsx('div', { className: 'text-[12px] opacity-60', children: 'Keine offenen Vorschläge — neue Rechnungen aus Telegram, E-Mail oder Upload erscheinen hier automatisch.' }))
      : jsx('div', { className: 'flex flex-col gap-2', children: data.proposals.map((p) => jsxs('div', { className: 'rounded-lg border border-(--ui-stroke-secondary) p-3', children: [
          jsxs('div', { className: 'flex flex-wrap items-center justify-between gap-2', children: [
            jsxs('div', { className: 'min-w-0', children: [
              jsx('div', { className: 'truncate text-[12px] font-medium', children: p.vendor }),
              jsx('div', { className: 'font-mono text-[10px] opacity-60', children: `${p.date} · ${p.subject}` }),
            ] }),
            SourceBadge(p.source, p.sourceLabel),
          ] }),
          bookForm?.invoiceId === p.invoiceId
            ? jsxs('div', { className: 'mt-2 flex flex-wrap items-end gap-2 rounded border border-(--ui-stroke-secondary) p-2', children: [
                jsxs('label', { className: 'flex flex-col gap-1', children: [
                  jsx('span', { className: 'font-mono text-[10px] uppercase opacity-50', children: 'Konto' }),
                  jsx('input', { value: bookForm.konto, onChange: (e) => setBookForm((f) => ({ ...f, konto: e.target.value })),
                    className: 'w-24 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[11px]' }),
                ] }),
                jsxs('label', { className: 'flex flex-col gap-1', children: [
                  jsx('span', { className: 'font-mono text-[10px] uppercase opacity-50', children: 'Monat' }),
                  jsx('input', { value: bookForm.month, placeholder: 'JJJJ-MM', onChange: (e) => setBookForm((f) => ({ ...f, month: e.target.value })),
                    className: 'w-24 rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[11px]' }),
                ] }),
                jsxs('label', { className: 'flex items-center gap-1.5 text-[11px]', children: [
                  jsx('input', { type: 'checkbox', checked: !!bookForm.opos, onChange: (e) => setBookForm((f) => ({ ...f, opos: e.target.checked })) }),
                  'Als offenen Posten (OPOS) führen',
                ] }),
                jsx('button', { type: 'button', className: 'fz-btn fz-btn--primary', onClick: () => void confirmBook(), children: 'Buchen' }),
                jsx('button', { type: 'button', className: 'fz-btn', onClick: () => setBookForm(null), children: 'Abbrechen' }),
              ] })
            : jsxs('div', { className: 'mt-2 flex flex-wrap items-center gap-2', children: [
                jsx('span', { className: 'font-mono text-[11px]', children: `${eur2(p.amountCents / 100)} €` }),
                jsx('span', { className: 'rounded border border-(--ui-stroke-secondary) px-2 py-0.5 font-mono text-[10px] opacity-70', children: `Vorschlag: Konto ${p.suggestedKonto} · ${p.category}` }),
                jsx('button', { type: 'button', className: 'fz-btn fz-btn--primary', onClick: () => setBookForm({
                  invoiceId: p.invoiceId, konto: p.suggestedKonto, month: (p.date || thisMonth()).slice(0, 7), opos: false }), children: 'Buchen …' }),
                jsx('button', { type: 'button', className: 'fz-btn fz-btn--danger', onClick: () => void reject(p.invoiceId), children: 'Verwerfen' }),
              ] }),
        ] }, p.invoiceId)) }),
  ] })
}

function FinanzenPage() {
  const [tab, setTab] = useState('tagebuch')
  const [month, setMonth] = useState(null)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState(null)
  const [isFehler, setIsFehler] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    const q = month ? `?month=${month}` : ''
    _rest(`/overview${q}`, { timeoutMs: 8000 })
      .then((d) => {
        if (cancelled) return
        setData(d)
        setError(null)
        // Feldwerte als deutsche Strings vorausfüllen (wie im nulleins-Formular)
        const next = {}
        for (const f of d.fields ?? []) if (f.value != null) next[f.key] = eur(f.value)
        setValues(next)
        setStatus(null)
      })
      .catch((e) => { if (!cancelled) setError(String(e?.message ?? e)) })
    return () => { cancelled = true }
  }, [month, reloadKey])

  const setValue = (key, val) => setValues((s) => ({ ...s, [key]: val }))

  // Live-Berechnung aus den aktuellen Eingaben (wie "Ergebnis · aktuell berechnet")
  const cents = useMemo(() => {
    const out = {}
    for (const [k, raw] of Object.entries(values)) {
      if (String(raw).trim() === '') continue
      const parsed = parseGermanNumber(raw)
      if (parsed != null) out[k] = parsed
    }
    return out
  }, [values])

  const r = useMemo(() => computeBwa(cents), [cents])
  const cats = useMemo(() => bwaCostCategories(cents), [cents])

  const options = useMemo(() => {
    const months = (data?.months ?? []).slice()
    const cur = thisMonth()
    if (!months.includes(cur)) months.push(cur)
    months.sort()
    return months
  }, [data])

  if (error) {
    const empty = /Noch keine BWA-Monate/i.test(error)
    if (empty) {
      return jsx('div', { className: 'p-4 text-sm flex flex-col gap-2', children: [
        jsx('div', { className: 'font-medium', children: 'Finanzen · BWA' }),
        jsx('div', { className: 'text-[12px] opacity-60', children:
          'Noch keine BWA-Monate erfasst. Leg los: Tägliche Einnahmen und Ausgaben im Tab „Tagebuch" erfassen (rollieren automatisch in die Monats-BWA) — oder hier den ersten Monat direkt anlegen.' }),
        jsx('div', { children: jsx('button', { type: 'button', className: 'fz-btn fz-btn--primary',
          onClick: async () => {
            setBusy(true)
            try {
              await _rest('/overview', { method: 'POST', timeoutMs: 10000,
                body: JSON.stringify({ month: thisMonth(), entries: { umsatz: '0' } }) })
              setMonth(thisMonth())
              setReloadKey((k) => k + 1)
            } catch (e) { setError(String(e?.message ?? e)) }
            setBusy(false)
          }, children: busy ? 'Lege an …' : `Monat ${label(thisMonth())} anlegen` }) }),
      ] })
    }
    return jsx('div', {
      className: 'p-4 text-sm',
      children: jsxs('div', { className: 'flex flex-col gap-2', children: [
        jsx('div', { className: 'font-medium', children: 'Finanzen · BWA' }),
        jsx('div', { className: 'text-[12px] opacity-60', children: `Backend nicht erreichbar: ${error}` }),
        jsx('div', { className: 'text-[12px] opacity-60', children: 'Plugin in Capabilities → Plugins aktiv und plugins.enabled in der config.yaml an?' }),
      ] }),
    })
  }

  if (!data) {
    return jsx('div', { className: 'p-4 text-sm opacity-60', children: 'Lade BWA …' })
  }

  async function save() {
    setBusy(true)
    try {
      const res = await _rest('/overview', { method: 'POST', body: JSON.stringify({ month: data.month, entries: values }), timeoutMs: 10000 })
      setData((d) => ({ ...d, months: res.months ?? d.months }))
      setStatus(`Monat ${label(data.month)} gespeichert`)
      setIsFehler(false)
    } catch {
      setIsFehler(true)
      setStatus('Speichern fehlgeschlagen. Bitte Eingaben prüfen.')
    }
    setBusy(false)
  }

  async function openExternal(url, what) {
    let ok = false
    try { ok = await _os.openExternal(url) } catch { ok = false }
    if (!ok) {
      setIsFehler(true)
      setStatus(`nulleins nicht erreichbar (${what}) — läuft der Dev-Server auf Port 4100?`)
    }
  }

  const btnCls = 'fz-btn'
  const btnPrimary = 'fz-btn fz-btn--primary'

  const resultRows = [
    ['Gesamtleistung', r.gesamtleistung, false],
    ['Rohertrag', r.rohertrag, false],
    ['Betrieblicher Rohertrag', r.betrieblicherRohertrag, false],
    ['Gesamtkosten', r.gesamtkosten, false],
    ['Betriebsergebnis', r.betriebsergebnis, true],
    ['Ergebnis vor Steuern', r.ergebnisVorSteuern, false],
    ['Vorläufiges Ergebnis', r.vorlaeufigesErgebnis, true],
  ]

  const groups = GROUPS.map((g) => GroupBlock(g, (data.fields ?? []).filter((f) => f.group === g), values, setValue)).filter(Boolean)

  const actionRow = jsxs('div', { className: 'mt-3 flex flex-wrap items-center gap-2', children: [
    jsx('button', { type: 'button', className: btnPrimary, disabled: busy, onClick: () => void save(), children: busy ? 'Speichere…' : 'Monat speichern' }),
    jsx('button', { type: 'button', className: btnCls, onClick: () => void openExternal(`${NULLEINS_BASE}/api/finances/bwa/excel?month=${data.month}`, 'Excel herunterladen'), children: 'Excel herunterladen' }),
    jsx('button', { type: 'button', className: btnCls, onClick: () => void openExternal(`${NULLEINS_BASE}/finanzen`, 'Drucken'), children: 'Drucken' }),
    status ? jsx('span', { className: 'font-mono text-[10px]', style: isFehler ? { color: '#e5484d' } : { opacity: 0.5 }, children: status }) : null,
  ] })

  const tabBtn = (key, label) => jsx('button', {
    type: 'button',
    className: cn('rounded border px-3 py-1 font-mono text-[11px] transition-colors',
      tab === key ? 'border-(--ui-accent) text-(--ui-accent)' : 'border-(--ui-stroke-secondary) opacity-70 hover:opacity-100'),
    onClick: () => setTab(key),
    children: label,
  }, key)

  return jsxs('div', {
    className: 'flex h-full flex-col gap-4 overflow-auto p-4 text-sm',
    children: [
      jsxs('div', { className: 'flex flex-wrap items-center gap-3', children: [
        jsx('div', { className: 'font-medium', children: 'Finanzen' }),
        tabBtn('tagebuch', 'Tagebuch'),
        tabBtn('bwa', 'BWA'),
        tabBtn('rechnungen', 'Rechnungen'),
        tabBtn('vorschlaege', 'Vorschläge'),
        tabBtn('susa', 'SuSa'),
        tabBtn('opos', 'OPOS'),
        tabBtn('vv', 'Vorjahresvergleich'),
        jsx('button', { type: 'button', className: 'fz-btn', title: 'Daten neu laden',
          onClick: () => setReloadKey((k) => k + 1), children: '↻ Neu laden' }),
      ] }),

      jsx(StyleOnce, {}),

      tab === 'rechnungen'
        ? jsx(RechnungenTab, { reloadKey }, `r${reloadKey}`)
        : tab === 'tagebuch'
          ? jsx(TagebuchTab, {}, `t${reloadKey}`)
          : tab === 'susa'
            ? jsx(SusaTab, { reloadKey }, `s${reloadKey}`)
            : tab === 'opos'
              ? jsx(OposTab, { reloadKey }, `o${reloadKey}`)
              : tab === 'vv'
                ? jsx(VvTab, { reloadKey }, `v${reloadKey}`)
                : tab === 'vorschlaege'
                  ? jsx(VorschlaegeTab, { reloadKey }, `p${reloadKey}`)
                  : jsxs(Fragment, { children: [
      jsxs('div', { className: 'flex flex-wrap items-center gap-3', children: [
        jsx('select', {
          value: data.month,
          onChange: (e) => setMonth(e.target.value),
          className: 'rounded border border-(--ui-stroke-secondary) bg-transparent px-2 py-1 font-mono text-[12px]',
          'aria-label': 'Monat und Jahr wählen',
          children: options.map((m) => jsx('option', { value: m, children: label(m) }, m)),
        }),
        jsx('div', { className: 'text-[11px] opacity-50', children: 'nulleins · data/bwa.db' }),
      ] }),

      jsxs('div', {
        style: { display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '1rem', alignItems: 'start' },
        children: [
          // Links: KER-Erfassung (editierbar) in nulleins-Gruppen
          Card('Erfassung · ' + label(data.month), null, jsxs('div', { children: [groups, actionRow] })),

          // Rechts: Live-Ergebnis + Donut
          jsxs('div', { className: 'flex flex-col gap-4', children: [
            Card('Ergebnis · aktuell berechnet', eur(r.vorlaeufigesErgebnis),
              jsxs('div', { className: 'flex flex-col gap-1.5', children: [
                ...resultRows.map(([l, val, s]) => jsxs('div', {
                  className: 'flex items-baseline justify-between gap-2 font-mono text-[11px]',
                  children: [
                    jsx('span', { className: s ? 'font-semibold' : 'opacity-70', children: l }),
                    jsx('span', { className: s ? 'font-semibold' : '', children: eur(val) }),
                  ],
                }, l)),
                jsx('div', { className: 'mt-2 border-t border-(--ui-stroke-secondary) pt-2 font-mono text-[10px] opacity-50',
                  children: `Material ${pct(r.pctMaterialGesLeistung)} % der Gesamtleistung · Personal ${pct(r.pctPersonalGesKosten)} % der Gesamtkosten` }),
              ] })),

            cats.length
              ? Card('Kostenarten · ' + label(data.month), null, Donut(cats, label(data.month), 150))
              : Card('Kostenarten · ' + label(data.month), null, jsx('div', { className: 'text-[12px] opacity-60', children: 'Keine Kosten erfasst' })),
          ] }),
        ],
      }),
        ] }, reloadKey),
    ],
  })
}

export default {
  id: 'finanzen',
  name: 'Finanzen (nulleins BWA)',
  register(ctx) {
    _rest = ctx.rest
    _os = ctx.os

    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/finanzen' },
        render: () => jsx(FinanzenPage, {}),
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: '/finanzen', label: 'Finanzen', codicon: 'graph-line' },
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'finanzen.open',
          label: 'Finanzen öffnen (BWA Dashboard)',
          keywords: ['finanzen', 'bwa', 'ker', 'nulleins'],
          run: () => host.navigate('/finanzen'),
        },
      },
    ])
  },
}
