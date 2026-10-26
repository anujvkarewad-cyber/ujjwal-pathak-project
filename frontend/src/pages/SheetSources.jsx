const CENTRE = 'https://docs.google.com/spreadsheets/d/1hMm8bGen63fMq8dLXgsPVhbV0S1lFWD_hhihctAxNYM/edit';
const SOURCES = [
  { title: 'Primary tracker & roster', status: 'Code default · schema verified', description: 'Students: authoritative membership, group and batch. Form responses 1: tracker submissions, combined with app study logs. Column order must stay unchanged.', key: 'primary' },
  { title: 'Enrollment responses', status: 'Student gateway code default', description: 'Enrollment and re-enrollment details. Do not replace the authoritative Students roster with raw intake rows.', key: 'enrollment' },
  { title: 'Notification catalog', status: 'Reference · runtime connection unverified', description: 'Catalog text is not proof of a live push schedule. Editing this workbook is not an instruction to send notifications.', key: 'notifications' },
  { title: 'Resource catalog', status: 'Reference · runtime connection unverified', description: 'Subject, type, title and link directory. No new automatic student import has been enabled.', key: 'resources' },
];
export default function SheetSources() {
  return <section className="space-y-6" data-testid="sheet-sources-page">
    <div className="rounded-2xl bg-slate-900 p-6 text-white">
      <p className="text-xs uppercase tracking-widest text-blue-200">UPM · Sheet management</p>
      <h2 className="mt-2 text-2xl font-bold">One directory. Clear source boundaries.</h2>
      <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-200">Inventory snapshot: 19 October 2026. 14 original workbooks and 80 primary tabs indexed. These are audited code defaults, not a live deployment or sync check.</p>
      <a href={CENTRE} target="_blank" rel="noopener noreferrer" className="mt-5 inline-block rounded-lg bg-white px-4 py-3 text-sm font-semibold text-slate-900">Open private Sheets Control Centre ↗</a>
      <p className="mt-2 text-xs text-slate-300">Google access is required. The complete student-tab directory stays in that private workbook, not in this app bundle.</p>
    </div>
    <aside className="rounded-xl border border-amber-300 bg-amber-50 p-5 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
      <h3 className="font-semibold">Security review required</h3>
      <p className="mt-2 text-sm leading-relaxed">At audit time, the primary workbook allowed anyone-with-link reading and contained credential-related columns and logs. Do not share its link with students. Hiding a tab does not secure it. Authenticated-reader migration and controlled credential rotation need an approved plan; permissions have not been changed.</p>
    </aside>
    <div className="grid gap-4 md:grid-cols-2">
      {SOURCES.map(item => <article key={item.key} className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
        <p className="text-xs text-blue-700 dark:text-blue-300">{item.status}</p>
        <h3 className="mt-2 text-lg font-semibold text-slate-900 dark:text-white">{item.title}</h3>
        <p className="mt-3 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{item.description}</p>
        <p className="mt-4 text-xs text-slate-500">Workbook link is available in the private Control Centre.</p>
      </article>)}
    </div>
    <div className="rounded-xl border border-slate-200 p-5 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-200">
      <h3 className="font-semibold">Before interpreting data</h3>
      <ul className="mt-3 list-disc space-y-2 pl-5">
        <li>The Sheet tabs named MCQ, Attendance and Leaderboard were header-only. They are not the complete app activity store.</li>
        <li>Group 1, Group 2 and Both remain exclusive. The inventory count of 170 is the whole roster, not the active January cohort.</li>
        <li>Attempt has mixed text/date cells; a query null must not be treated as a missing attempt without checking the typed source.</li>
        <li>No live rollout, student message, APK build or historical podium rewrite is authorized by this directory.</li>
      </ul>
    </div>
  </section>;
}
