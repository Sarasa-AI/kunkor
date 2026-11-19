"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import styles from "./content.module.css";

type Kind = "chapter" | "lesson" | "section" | "topic";
type ContentRecord = {
  id: string;
  book_id?: string;
  kind?: Kind;
  parent_id?: string | null;
  title: string;
  status: string;
  number?: number | null;
  grades?: number[];
  license_active?: boolean;
  approved_by?: string | null;
  approved_at?: string | null;
  [field: string]: unknown;
};
type AuditEntry = {
  action?: string;
  actor?: string;
  actor_id?: string;
  actor_identity?: string;
  created_at?: string;
  occurred_at?: string;
  after_record?: { status?: string };
};
type Values = Record<string, string> & { kind: Kind };
const metadataFields = ["publisher", "isbn", "edition", "subject_code", "track"];
const provenanceFields = ["provenance_source", "provenance_reference", "license_id", "rights_statement", "notes"];
const numericFields = ["number", "page_start", "page_end", "exercise_start", "exercise_end", "question_count", "estimated_duration_minutes"];
const kindNames: Record<Kind, string> = { chapter: "Chapter", lesson: "Lesson", section: "Section", topic: "Topic" };
const statusNames: Record<string, string> = { draft: "Draft", pending_review: "Awaiting review", approved: "Approved", published: "Published", archived: "Archived", rejected: "Rejected" };

function valuesFor(record?: ContentRecord): Values {
  const values: Values = { title: "", kind: "chapter", provenance_source: "no_source", parent_id: "", page_count: "" };
  for (const field of [...metadataFields, ...provenanceFields, ...numericFields]) values[field] = "";
  values.provenance_source = "no_source";
  if (record) {
    for (const field of Object.keys(values)) {
      if (record[field] !== undefined && record[field] !== null) values[field] = String(record[field]);
    }
    if (record.kind) values.kind = record.kind;
  }
  return values;
}

function readableStatus(record: ContentRecord) {
  return statusNames[record.status] || record.status;
}

export default function ContentAdminPage() {
  const [credential, setCredential] = useState("");
  const [adminKey, setAdminKey] = useState("");
  const [books, setBooks] = useState<ContentRecord[]>([]);
  const [book, setBook] = useState<ContentRecord | null>(null);
  const [units, setUnits] = useState<ContentRecord[]>([]);
  const [editor, setEditor] = useState<"book" | "unit" | null>(null);
  const [editing, setEditing] = useState<ContentRecord | null>(null);
  const [values, setValues] = useState<Values>(valuesFor());
  const [grades, setGrades] = useState<number[]>([]);
  const [licenseActive, setLicenseActive] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);

  async function api<T>(path: string, method = "GET", payload?: unknown, key = adminKey): Promise<T> {
    const response = await fetch(`/api/admin/content/${path}`, {
      method,
      headers: { "X-Admin-Api-Key": key, "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      cache: "no-store",
      credentials: "omit",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Content request failed.");
    return result as T;
  }

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Content request failed."); }
    finally { setBusy(false); }
  }

  function showEditor(mode: "book" | "unit", record: ContentRecord | null) {
    setEditor(mode); setEditing(record); setValues(valuesFor(record || undefined));
    setGrades(record?.grades || []); setLicenseActive(Boolean(record?.license_active));
    setDirty(false); setAudit(null); setMessage(""); setError("");
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const catalog = await api<ContentRecord[]>("books", "GET", undefined, credential);
      setBooks(catalog); setAdminKey(credential); setCredential("");
    });
  }

  async function chooseBook(record: ContentRecord) {
    if (dirty && !window.confirm("Leave unsaved edits? Save a draft first to keep your changes.")) return;
    await run(async () => {
      const children = await api<ContentRecord[]>(`books/${record.id}/units`);
      setBook(record); setUnits(children); showEditor("book", record);
    });
  }

  function chooseUnit(record: ContentRecord | null) {
    if (dirty && !window.confirm("Leave unsaved edits? Save a draft first to keep your changes.")) return;
    showEditor("unit", record);
  }

  function newBook() {
    if (dirty && !window.confirm("Leave unsaved edits? Save a draft first to keep your changes.")) return;
    setBook(null); setUnits([]); showEditor("book", null);
  }

  function change(field: string, value: string) {
    setValues(previous => ({ ...previous, [field]: value, ...(field === "kind" ? { parent_id: "" } : {}) })); setDirty(true);
  }

  async function refresh(record: ContentRecord, mode: "book" | "unit") {
    const catalog = await api<ContentRecord[]>("books");
    setBooks(catalog);
    const parent = mode === "book" ? record : catalog.find(candidate => candidate.id === record.book_id);
    if (parent) {
      setBook(parent);
      setUnits(await api<ContentRecord[]>(`books/${parent.id}/units`));
    }
    showEditor(mode, record);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editor) return;
    const mode = editor;
    const payload: Record<string, unknown> = { title: values.title, license_active: licenseActive };
    for (const field of provenanceFields) payload[field] = values[field] || null;
    payload.provenance_source = values.provenance_source;
    if (mode === "book") {
      for (const field of metadataFields) payload[field] = values[field] || null;
      payload.grades = grades;
      payload.page_count = values.page_count === "" ? null : Number(values.page_count);
    } else {
      if (!book) return;
      if (!editing) { payload.book_id = book.id; payload.kind = values.kind; payload.parent_id = values.parent_id || null; }
      for (const field of numericFields) payload[field] = values[field] === "" ? null : Number(values[field]);
    }
    await run(async () => {
      const collection = mode === "book" ? "books" : "units";
      const record = await api<ContentRecord>(editing ? `${collection}/${editing.id}` : collection, editing ? "PATCH" : "POST", payload);
      await refresh(record, mode);
      setMessage("Draft saved. You can return later and continue editing.");
    });
  }

  async function transition(action: string) {
    if (!editing || !editor) return;
    const record = editing; const mode = editor;
    await run(async () => {
      const updated = await api<ContentRecord>(`${mode === "book" ? "books" : "units"}/${record.id}/${action}`, "POST", {});
      await refresh(updated, mode);
      setMessage(`Content is now ${readableStatus(updated).toLowerCase()}.`);
    });
  }

  async function loadAudit() {
    if (!editing || !editor) return;
    await run(async () => setAudit(await api<AuditEntry[]>(`${editor === "book" ? "books" : "units"}/${editing.id}/audit`)));
  }

  function signOut() {
    if (dirty && !window.confirm("Sign out and leave unsaved edits?")) return;
    setAdminKey(""); setCredential(""); setBooks([]); setBook(null); setUnits([]); setEditor(null);
    setEditing(null); setValues(valuesFor()); setAudit(null); setError(""); setMessage(""); setDirty(false);
  }

  function field(label: string, name: string, options: { numeric?: boolean; hint?: string; multiline?: boolean } = {}) {
    const id = `content-${name}`;
    return <label className={styles.field} htmlFor={id}>
      {label}
      {options.multiline
        ? <textarea id={id} value={values[name]} onChange={event => change(name, event.target.value)} disabled={busy} />
        : <input id={id} type={options.numeric ? "number" : "text"} min={options.numeric ? (name === "question_count" ? 0 : 1) : undefined} step={options.numeric ? 1 : undefined} value={values[name]} onChange={event => change(name, event.target.value)} disabled={busy} />}
      {options.hint && <span className={styles.hint}>{options.hint}</span>}
    </label>;
  }

  function recordButton(record: ContentRecord, selected: boolean, onClick: () => void) {
    return <button type="button" className={`${styles.button} ${styles.item} ${selected ? styles.selected : ""}`} onClick={onClick} disabled={busy} aria-pressed={selected}>
      <span className={styles.itemText}>{record.title || "Untitled draft"}{record.kind && <small>{kindNames[record.kind]}{record.number ? ` ${record.number}` : ""}</small>}</span>
      <span className={`${styles.status} ${record.status === "published" ? styles.published : ""}`}>{readableStatus(record)}</span>
    </button>;
  }

  return <main className={styles.page} dir="ltr" lang="en">
    <Link href="/">← Kunkor home</Link>
    <header className={styles.header}>
      <div><p className={styles.eyebrow}>KUNKOR · OWNER WORKSPACE</p><h1>Build your catalog, one entry at a time.</h1><p className={styles.description}>Start with a book or resource, save an unfinished draft, and add chapters or smaller units whenever you are ready.</p></div>
      {adminKey && <button className={styles.button} onClick={signOut} disabled={busy}>Sign out</button>}
    </header>
    {error && <div role="alert" className={`${styles.notice} ${styles.error}`}>{error}</div>}
    {message && <div role="status" className={styles.notice}>{message}</div>}
    {!adminKey ? <section className={`${styles.card} ${styles.login}`} aria-labelledby="sign-in-title">
      <h2 id="sign-in-title">Owner sign in</h2>
      <p className={styles.description}>Use your administrator API key. Signing out or refreshing this page clears the key from this session.</p>
      <form className={styles.stack} onSubmit={login} style={{ marginTop: 24 }}>
        <label className={styles.field} htmlFor="admin-key">Administrator API key<input id="admin-key" name="admin-key" type="password" value={credential} onChange={event => setCredential(event.target.value)} autoComplete="current-password" required disabled={busy} /></label>
        <button className={`${styles.button} ${styles.primary}`} type="submit" disabled={busy}>{busy ? "Signing in…" : "Open content workspace"}</button>
      </form>
    </section> : <div className={styles.layout} aria-busy={busy}>
      <aside className={styles.card} aria-labelledby="catalog-title">
        <div className={styles.toolbar}><h2 id="catalog-title">Resources</h2><button className={styles.button} onClick={newBook} disabled={busy}>+ New</button></div>
        {books.length === 0 ? <p className={styles.empty}>Your catalog is empty and ready. Create your first resource whenever you are ready.</p> : <ul className={styles.list}>{books.map(record => <li key={record.id}>{recordButton(record, book?.id === record.id, () => { void chooseBook(record); })}</li>)}</ul>}
        <p className={styles.hint} style={{ marginTop: 20 }}>Drafts stay private. Only reviewed, approved and published content with active usage rights is available to students and agents.</p>
      </aside>
      <div className={styles.stack}>
        {!editor ? <section className={styles.card}><h2>Ready when you are</h2><p className={styles.description}>Select a saved resource to continue editing, or create a resource. No chapters or complete curriculum are required.</p><button className={`${styles.button} ${styles.primary}`} onClick={newBook} disabled={busy} style={{ marginTop: 24 }}>Create a resource</button></section> : <section className={styles.card} aria-labelledby="editor-title">
          <div className={styles.toolbar}><h2 id="editor-title">{editing ? "Edit" : "New"} {editor === "book" ? "resource" : (editing?.kind ? kindNames[editing.kind].toLowerCase() : "content unit")}</h2><span className={styles.status}>{dirty ? "Unsaved edits" : editing ? readableStatus(editing) : "Draft"}</span></div>
          <p className={styles.hint} style={{ marginBottom: 20 }}>Save with whatever information you have. Editing a reviewed entry returns it to draft so your changes can be reviewed.</p>
          <form onSubmit={save} className={styles.stack}>
            {editor === "unit" && <div className={styles.fields}>
              <label className={styles.field} htmlFor="content-kind">Unit type<select id="content-kind" value={values.kind} onChange={event => change("kind", event.target.value)} disabled={busy || Boolean(editing)}>{Object.entries(kindNames).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select></label>
              {field("Number", "number", { numeric: true, hint: "Optional; add it later." })}
              <label className={`${styles.field} ${styles.full}`} htmlFor="content-parent">Parent unit (optional)<select id="content-parent" value={values.parent_id} onChange={event => change("parent_id", event.target.value)} disabled={busy || Boolean(editing) || values.kind === "chapter"}><option value="">Directly under this resource</option>{units.filter(unit => unit.id !== editing?.id && (values.kind === "lesson" ? unit.kind === "chapter" : ["section", "topic"].includes(values.kind) && ["chapter", "lesson"].includes(unit.kind || ""))).map(unit => <option key={unit.id} value={unit.id}>{unit.kind ? `${kindNames[unit.kind]}: ` : ""}{unit.title || "Untitled draft"}</option>)}</select><span className={styles.hint}>A smaller unit can be entered and published independently. The parent is saved when you first create the unit.</span></label>
            </div>}
            {field(editor === "book" ? "Resource title" : "Unit title", "title", { hint: "Optional for a draft; required for owner approval." })}
            {editor === "book" ? <details className={styles.details}>
              <summary>Resource metadata</summary>
              <div className={styles.fields}>{field("Publisher / resource owner", "publisher")}{field("ISBN / identifier", "isbn")}{field("Edition", "edition")}{field("Subject code", "subject_code")}{field("Track", "track")}{field("Total pages", "page_count", { numeric: true, hint: "Leave blank when unknown." })}
                <fieldset className={styles.full} style={{ border: 0, margin: 0, padding: 0 }}><legend className={styles.field}>Grades (optional)</legend><div className={styles.choices}>{[10, 11, 12].map(grade => <label className={styles.choice} key={grade}><input type="checkbox" checked={grades.includes(grade)} disabled={busy} onChange={event => { setGrades(previous => event.target.checked ? [...previous, grade] : previous.filter(value => value !== grade)); setDirty(true); }} />Grade {grade}</label>)}</div></fieldset>
              </div>
            </details> : <details className={styles.details}>
              <summary>Pages, exercises and study metadata</summary>
              <div className={styles.fields}>{field("First page", "page_start", { numeric: true })}{field("Last page", "page_end", { numeric: true })}{field("First exercise", "exercise_start", { numeric: true })}{field("Last exercise", "exercise_end", { numeric: true })}{field("Exercise count", "question_count", { numeric: true })}{field("Estimated study minutes", "estimated_duration_minutes", { numeric: true })}</div>
              <p className={styles.hint} style={{ marginTop: 12 }}>Ranges and counts can be completed later. Unknown values stay unknown.</p>
            </details>}
            <details className={styles.details}>
              <summary>Provenance and usage rights</summary>
              <p className={styles.hint} style={{ marginBottom: 16 }}>Before approval, add a source, its reference, a license identifier and a rights statement. Activate usage rights only when the license permits use.</p>
              <div className={styles.fields}>
                <label className={styles.field} htmlFor="content-source">Source<select id="content-source" value={values.provenance_source} onChange={event => change("provenance_source", event.target.value)} disabled={busy}><option value="no_source">Not entered yet</option><option value="owner_entered">Owner entered</option><option value="ai_suggestion">AI suggestion — unverified</option><option value="publisher_catalog">Publisher catalog</option><option value="official_curriculum">Official curriculum</option><option value="educator_verified">Educator verified</option></select></label>
                {field("Source reference", "provenance_reference")}{field("License identifier", "license_id")}{field("Rights statement", "rights_statement", { multiline: true })}
                <div className={styles.full}>{field("Owner notes", "notes", { multiline: true })}</div>
                <label className={`${styles.choice} ${styles.full}`}><input type="checkbox" checked={licenseActive} disabled={busy} onChange={event => { setLicenseActive(event.target.checked); setDirty(true); }} />Usage rights are active for this entry</label>
              </div>
            </details>
            <div className={styles.actions}><button className={`${styles.button} ${styles.primary}`} type="submit" disabled={busy || Boolean(editing && !dirty)}>{busy ? "Saving…" : "Save draft"}</button><span className={styles.hint}>No complete book is required.</span></div>
          </form>
          {editing && <div className={styles.review}>
            <h3 className={styles.sectionTitle}>Owner review and publication</h3>
            <p className={styles.hint} style={{ marginBottom: 16 }}>{dirty ? "Save your edits before changing the review state." : "Submit for review, approve the source and rights, then publish this entry. Publication applies to this entry individually."}</p>
            <div className={styles.actions}>
              {["draft", "rejected", "archived"].includes(editing.status) && <button className={styles.button} onClick={() => { void transition("submit"); }} disabled={busy || dirty}>{editing.status === "archived" ? "Restore and submit for review" : "Submit for review"}</button>}
              {editing.status === "pending_review" && <button className={`${styles.button} ${styles.primary}`} onClick={() => { void transition("approve"); }} disabled={busy || dirty}>Approve after review</button>}
              {editing.status === "approved" && <button className={`${styles.button} ${styles.primary}`} onClick={() => { void transition("publish"); }} disabled={busy || dirty || !licenseActive}>Publish this entry</button>}
              {["pending_review", "approved"].includes(editing.status) && <button className={styles.button} onClick={() => { void transition("reject"); }} disabled={busy || dirty}>Reject</button>}
              {editing.status !== "archived" && <button className={`${styles.button} ${styles.danger}`} onClick={() => { void transition("archive"); }} disabled={busy || dirty}>Archive</button>}
              <button className={styles.button} onClick={() => { void loadAudit(); }} disabled={busy}>View audit history</button>
            </div>
            {editing.status === "approved" && !licenseActive && <p className={styles.hint} style={{ marginTop: 12 }}>Active usage rights are required to publish. Saving a change requires a new review.</p>}
            {editing.approved_by && <p className={styles.hint} style={{ marginTop: 12 }}>Reviewed by {editing.approved_by}{editing.approved_at ? ` · ${new Date(editing.approved_at).toLocaleString()}` : ""}</p>}
            {audit && (audit.length === 0 ? <p className={styles.hint} style={{ marginTop: 12 }}>No history entries.</p> : <ol className={styles.audit}>{audit.map((event, index) => <li key={index}>{event.action === "INSERT" ? "Created" : event.action === "UPDATE" ? "Updated" : event.action || "Content updated"}{event.after_record?.status ? ` → ${statusNames[event.after_record.status] || event.after_record.status}` : ""} · {event.actor_identity || event.actor || event.actor_id || "Owner"}{event.created_at || event.occurred_at ? ` · ${new Date(event.created_at || event.occurred_at || "").toLocaleString()}` : ""}</li>)}</ol>)}
          </div>}
        </section>}
        {book && <section className={styles.card} aria-labelledby="units-title">
          <div className={styles.toolbar}><div><h2 id="units-title">Units in {book.title || "this draft"}</h2><p className={styles.hint}>Add a chapter, lesson, section or topic independently.</p></div><button className={styles.button} onClick={() => chooseUnit(null)} disabled={busy}>+ Add unit</button></div>
          {units.length === 0 ? <p className={styles.empty}>No units yet. Your resource is saved; you can add the first chapter now or return later.</p> : <ul className={styles.list}>{units.map(record => <li key={record.id}>{recordButton(record, editing?.id === record.id, () => chooseUnit(record))}</li>)}</ul>}
        </section>}
      </div>
    </div>}
  </main>;
}
