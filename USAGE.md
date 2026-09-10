# resume-tailor — detailed usage & workflow

This is the working manual. For the short version see `README.md`.

---

## 1. The mental model

There are three things in play:

| Thing | File | Who edits it | When |
|---|---|---|---|
| **Profile library** | `profile/profiles/<name>/master_profile.yaml` | You, in the web UI (Profiles) or by hand | Set up once per target role, then rarely |
| **Settings** | `profile/settings.yaml` | You, by hand | Once |
| **A tailored application** | `outputs/<company>_<role>_<date>/` | The tool (you can hand-tune) | Every job |

You keep **several profiles** — one per target role / seniority (e.g. `ai-engineer`,
`data-engineer`, `senior-be`). Each is a complete resume with its own companies, dates,
education, declared **years of experience**, **role family**, and **section layout**. On a run
you pick a profile, or leave it on **Auto** and the tool reads the JD's required years + role
and routes to the profile that fits (a 5-year JD → your 6-year profile; a 7-year JD → your
senior profile). See §3a.

### What is locked vs. rewritten

For **every** entry under `experience:` in the master profile:

- **LOCKED — never changed, ever:** `client`, `employer`, `location`, `start`, `end`.
  After the AI responds, `validate.lock_invariants()` overwrites these back from the
  master profile. If the model tried to change one, you get a line in `warnings.txt`
  but the output is still correct.
- **REWRITTEN for each job:** the professional `summary`, the `skill_groups` and their
  order, each entry's `role` wording, its one-line `summary`, and all of its `bullets`.
- **COPIED verbatim from master:** `contact`, `education`, `certifications`.

So the timeline of your career — which client, in what order, for how long — is
identical on every resume you send. Everything describing *what you did* is
re-aimed at the specific requirement.

### Aggressive vs. conservative

- **Aggressive (default).** Project context is rewritten freely. Technologies the
  requirement asks for that are **not** in your master profile are woven in at
  chronologically plausible points. The `gap_report.md` "Missing" list is your
  record of exactly what was added beyond what your profile documents — read it
  every time.
- **Conservative (`--conservative`).** Only rephrases and reorders experience you
  actually listed. "Missing" skills stay missing. Use this when you want the
  resume to stay strictly within what you've documented.

---

## 2. One-time setup

```bash
cd ~/resume-tailor
./setup.sh                       # creates .venv, installs the package + deps
source .venv/bin/activate        # do this in every new shell
resume-tailor version            # sanity check
```

`setup.sh` is safe to re-run. If `python -m venv` fails on Fedora:
`sudo dnf install python3-virtualenv python3-pip` then re-run.

### Optional: better PDF

```bash
sudo dnf install libreoffice-writer
```

With LibreOffice present, PDFs are converted directly from the generated `.docx`,
so they are pixel-identical to the Word file. Without it, a built-in `fpdf2`
renderer draws the same layout — close, but not identical. The `tailor` output
tells you which was used: `pdf engine: libreoffice` or `pdf engine: fpdf2`.

### Scaffold your files

```bash
resume-tailor init
```

Writes `profile/master_profile.yaml` and `profile/settings.yaml` from templates.
Re-run with `--force` to overwrite (you'll lose your edits).

---

## 3. Filling in the master profile

Open `profile/master_profile.yaml`. This is the highest-leverage step — **the
richer and more complete it is, the better every tailored resume will be.**

### `contact:`

```yaml
contact:
  name: "Jane Q. Candidate"
  title: "Senior Software Engineer"      # your default headline; a JD can override it
  email: "jane@example.com"
  phone: "+1 (555) 123-4567"
  location: "Dallas, TX"
  linkedin: "linkedin.com/in/janeqc"
  website: ""                            # leave "" to omit
  work_authorization: "US Citizen"       # or "GC", "H1B", "GC-EAD"… leave "" to omit
```

Everything here is printed as-is on every resume and the cover letter. No AI
touches it.

### `summary:`

A 3–5 sentence default professional summary. The AI rewrites this per job, but a
good baseline helps it. Write it in "implied first person" (no "I").

### `skill_groups:`

```yaml
skill_groups:
  - category: "Languages"
    skills: ["Java", "Python", "JavaScript", "TypeScript", "SQL", "Bash"]
  - category: "Cloud & DevOps"
    skills: ["AWS", "Azure", "Docker", "Kubernetes", "Terraform", "Jenkins"]
```

**Put everything you can legitimately claim here.** The gap report matches a
requirement's skills against this list (plus each entry's `environment`). Group
them however your standard resume groups them — the categories are printed as-is.
The AI reorders skills within/against groups so requirement "must-haves" come
first.

### `experience:` — the core

```yaml
experience:
  - id: "exp1"                     # any unique string; keep it stable
    client: "Global Retail Bank"   # LOCKED — the end client
    employer: "Acme Consulting Inc." # LOCKED — your vendor / prime / W2 employer
    role: "Senior Software Engineer"  # AI may adjust wording to match JD seniority
    location: "Remote (US)"        # LOCKED
    start: "2023-02"               # LOCKED — YYYY-MM
    end: "Present"                 # LOCKED — YYYY-MM or "Present"
    environment: ["Java", "Spring Boot", "Kafka", "AWS", "Kubernetes", "PostgreSQL"]
    summary: "Payments modernization: monolith → microservices."
    bullets:
      - "Led decomposition of a payments monolith into 12 Spring Boot services…"
      - "Built an event-driven settlement pipeline on Kafka handling 4M txns/day…"
    bullet_library:
      - "Mentored 4 engineers; set the service template standard."
      - "Cut cloud spend 22% by right-sizing pods and moving batch to spot."
```

Field-by-field:

- **`id`** — stable handle used to line up the AI's output with the master. If you
  reorder entries, keep ids attached to the same job.
- **`client` / `employer`** — printed as `Client — Employer`. If you were a
  full-time employee (not a sub), set `employer` to the same as `client` or leave
  it `""`.
- **`role`** — your real title. The AI is allowed to nudge the wording
  (e.g. "Software Engineer" → "Backend Software Engineer") to mirror the JD. It
  cannot invent a seniority jump that your dates/timeline don't support.
- **`environment`** — the tech actually used on this engagement. Feeds skill
  matching and tells the AI what's plausible to emphasise here.
- **`summary`** — one line of context for the engagement. Optional.
- **`bullets`** — your real accomplishment bullets. Metric-led is best.
- **`bullet_library`** — extra bullets the AI may pull from when a requirement
  makes them relevant. Dump everything you've ever done on this engagement here;
  it won't all appear on every resume, only what fits the JD.

Add as many entries as your real history has. Order them newest-first — that's
how they're printed.

### `education:` / `certifications:`

```yaml
education:
  - degree: "Bachelor of Technology"
    field: "Computer Science"
    institution: "State University"
    location: "India"
    year: "2016"

certifications:
  - name: "AWS Certified Solutions Architect – Associate"
    issuer: "Amazon Web Services"
    year: "2022"
```

Printed verbatim. The AI is instructed **not** to claim any degree or cert that
isn't listed here.

### `extra_bullets:`

Free-floating lines the AI may use for any role (e.g. "Comfortable being the sole
engineer on a contract, from requirements to production support.").

### Validation

`resume-tailor` refuses to run if the profile is malformed. It requires:
`contact.name`, at least one `experience` entry, and every entry to have
`client`, `start`, `end`, and a unique `id`. Section keys in `layout` must be one of
`summary|skills|experience|education|certifications` or start with `custom:`.

---

## 3a. The profile library (web UI)

Open **Profiles** in the web app (`resume-tailor web` → nav bar). Each row is one profile.

**Create / clone / rename / delete.** "Create blank" scaffolds from the example. "Clone" is the
fast path — duplicate `default`, adjust, save as `senior-ai-engineer`. CLI equivalents:
`resume-tailor profile new <name> [--from <other>]`, `profile rename <old> <new>`,
`profile delete <name>`.

**Edit** opens a structured form for the whole profile — no YAML. Add/remove experience rows,
edit locked dates inline, reorder anything with the per-row `order` box, manage skill groups,
education, certifications.

**Profile metadata** (top of the edit form):

| Field | What it does |
|---|---|
| `label` | Friendly name in the picker |
| `years_experience` | **Declared** years. Drives Auto routing and the opening line of the tailored summary. Set this to the number you stand behind for this profile — it does not have to equal the dated timeline, but the gap report notes when they differ by a year or more. |
| `role_family` | Comma/line list (e.g. `data engineer, etl, pipelines`). Matched against the JD's role + domains for Auto routing. |
| `seniority` | Free text, fed to the tailor prompt. |

**Auto routing.** On the dashboard the Profile dropdown defaults to **Auto — match to JD**. The
tool extracts the JD's `min_years` and role, then picks the profile whose `role_family` best
matches and whose `years_experience` clears the bar (closest fit). If none clear it, it takes
the highest and notes the shortfall in the job log + gap report. Pick a named profile in the
dropdown to skip routing. `resume-tailor tailor -p auto` / `gap -p auto` do the same on the CLI.
Quick metadata edits without the form: `resume-tailor profile set <name> --years 7 --role-family
"ai engineer,llm" --label "Senior AI Engineer"`.

**Section layout** (bottom of the edit form). Untick a section to hide it; set its `order` to
move it; set `max` to cap items (bullets per role / skills per group / entries). Add a
**custom section**: key must be `custom:<slug>` (e.g. `custom:projects`), give it a heading and
one content line per row — it prints verbatim, it is not sent to the AI. A profile left on the
default five sections stores no `layout:` block and renders exactly as before.

---

## 4. Settings

`profile/settings.yaml`:

```yaml
engine: claude-cli        # claude-cli | api | ollama
claude_binary: claude     # path/name of the Claude Code CLI
model: sonnet             # claude-cli alias: sonnet | opus | haiku

api_model: claude-sonnet-5   # legacy — see providers: block / Settings tab
ollama_model: llama3.1
ollama_url: http://localhost:11434

llm_timeout: 240          # seconds per AI call (there are 2 calls per tailor run)

make_pdf: true
page_size: letter         # letter | a4
accent_color: "#1F4E79"   # heading / name colour in the documents
```

- **`claude-cli`** (default) shells out to `claude -p --output-format json`. Uses
  your Claude Code subscription — no separate per-token API bill. This is the
  recommended engine.
- **`api`** needs `pip install 'resume-tailor[api]'` and `ANTHROPIC_API_KEY` in
  your environment. Costs API credits.
- **`ollama`** talks to a local Ollama server. Free and offline, lower quality.

Environment overrides (take precedence over the file):

```bash
export RESUME_TAILOR_ENGINE=api
export RESUME_TAILOR_MODEL=opus
export RESUME_TAILOR_HOME=/path/to/another/project/root   # use a different profile+outputs tree
```

---

## 5. Commands reference

### `resume-tailor init [--force]`

Scaffold `profile/master_profile.yaml` and `profile/settings.yaml`. `--force`
overwrites existing files.

### `resume-tailor tailor`

The main command. Runs: extract requirement → gap analysis → tailor (resume +
cover letter in one AI call) → lock invariants → render DOCX + PDF.

| Flag | Default | Meaning |
|---|---|---|
| `--jd PATH` | — | Job description file |
| `--jd-text "…"` | — | Job description as a string |
| *(stdin)* | — | If neither `--jd` nor `--jd-text` and input is piped, stdin is the JD |
| `--profile NAME` / `-p` | `default` | Which profile to use. `-p auto` routes by the JD's years + role. |
| `--company "…"` | from JD | Override the end-client/company name (used in folder name, cover letter, `target_company`) |
| `--role "…"` | from JD | Override the target role |
| `--engine` | `claude-cli` | `claude-cli` \| `api` \| `ollama` |
| `--model` | from settings | Model alias/id for this run |
| `--bullets N` | `6` | Max bullets per experience entry |
| `--conservative` | off | Only rephrase real experience; don't weave in missing skills |
| `--review-rounds N` | from settings (`2`) | Self-critique/revise passes after the draft. `0` = classic single draft. |
| `--variants a,b` | — | Comma list of angles (`aggressive`, `conservative`, `ic`, `lead`) → one subfolder each + `comparison.md` |
| `--no-pdf` | off | Skip PDF, produce DOCX only (faster) |
| `--out NAME` | auto | Output subfolder name under `outputs/` |

Default run = **4 AI calls** (extract + draft + 2 review). `~8–12 min` on
`claude-cli`/`sonnet`; `--review-rounds 0` drops it back to 2 calls / ~3 min.
`--variants` multiplies the draft+review cost per angle. After the run the terminal
prints `match: NN/100` and the "what's weak" list; the full breakdown is in
`match.md` / `coverage.md`.

### `resume-tailor gap`

Skills-gap analysis **plus a pre-tailor match estimate**, printed to the terminal.
No documents written — use it to triage before spending a full run.

| Flag | Meaning |
|---|---|
| `--jd PATH` / `--jd-text "…"` | The JD |
| `--profile` / `-p` | Profile to score against; `-p auto` routes by the JD |
| `--no-llm` | Skip the AI; keyword heuristic (instant, rougher; still ranks + finds gates) |
| `--engine` | Engine for the extraction call |

### `resume-tailor render <tailored_profile.yaml> [--no-pdf]`

Re-render `resume.docx/pdf`, `resume.txt/md` and `cover_letter.docx/pdf` from an
edited `tailored_profile.yaml`. **No AI call** — instant. This is how you iterate
on wording by hand. (`defense.md` is a first-run artifact and is left untouched.)

### `resume-tailor web [--host H] [--port P]`

Start the local web UI (default `http://127.0.0.1:8000`). Paste a JD, pick
options, get the four files plus the gap summary in the browser. It also lists
recent runs with download links, and hosts the **Profiles** library (§3a).
`Ctrl+C` to stop.

### `resume-tailor profiles` / `resume-tailor profile …`

`profiles` lists profile names. The `profile` subcommands manage the library:
`profile show <name>` (metadata + layout + years), `profile new <name> [--from X]`,
`profile rename <old> <new>`, `profile delete <name>`, `profile set <name> [--years N]
[--role-family "a,b"] [--label …] [--seniority …]`.

### `resume-tailor version`

Print the version.

---

## 6. The per-application workflow

### Step 0 — once
Fill in `profile/master_profile.yaml` (section 3). Set `profile/settings.yaml`.

### Step 1 — capture the requirement
Save the vendor's requirement to a text file. Plain text is best; strip email
boilerplate and signatures. Keep the must-have / nice-to-have / responsibilities
structure if it's there — the extractor uses it.

```bash
mkdir -p jds
$EDITOR jds/healthpayer-backend.txt      # paste the requirement
```

### Step 2 — triage (optional, fast)
```bash
resume-tailor gap --jd jds/healthpayer-backend.txt
```
Look at:
- **Missing** count — how far the requirement is from your documented profile.
- **Experience: need ~X yrs / have ~Y yrs** — if `have` is well below `need`,
  the locked timeline can't cover it; decide whether to still apply.

If it's a hard no, stop here — you've spent 5 seconds and no AI call.

### Step 3 — generate
```bash
resume-tailor tailor \
  --jd jds/healthpayer-backend.txt \
  --company "HealthPayer Co" \
  --role "Senior Backend Engineer"
```
Add `--conservative` if you want it to stay strictly within documented
experience. Add `--bullets 5` for a tighter resume.

Output folder: `outputs/healthpayer-co_senior-backend-engineer_<date>/`.

### Step 4 — review (do this every time)
Open, in this order:

0. **`match.md`** — the 0–100 fit score, its component breakdown (coverage / years /
   domain / archetype, minus a penalty), and a concrete **"what's weak"** list. If the
   score is low for the profile you meant to use, a different profile probably fits
   better — check `resume-tailor gap -p auto` or the picker.

1. **`coverage.md`** — the honest check that the resume you're about to send actually
   carries the requirement. A table per must-have (is it in the summary / skills / a
   bullet, and which engagement), hard-gate verdicts, and — most important — every
   **stretch bullet** (a claim the review pass could not trace to your master profile).
   Cut or be ready to defend each.

2. **`gap_report.md`**
   - *Matched* — good, these are backed by your profile.
   - *Partial* — related terms found; the resume will lean on adjacent experience.
   - *Missing* — in aggressive mode these were **added** to your resume even
     though your profile doesn't document them. Read every one. Decide if you're
     comfortable standing behind each in a screening call. If not, either
     re-run with `--conservative`, or edit them out in step 5, or add the real
     backing to your master profile and re-run.
   - *Notes* — years shortfall and similar flags.

2. **`warnings.txt`** (only exists if there were any)
   - Normally empty. Lines here mean the AI tried to change a locked field
     (client/dates) or returned something incomplete and the tool corrected it.
     The output is still valid; this is just transparency.

3. **`resume.docx`** — read it end to end. Check:
   - Clients, employers, locations, date ranges match your master exactly.
   - Every bullet is something you can talk about for two minutes in an
     interview. Delete or soften any that overreach.
   - No duplicated claims across engagements; seniority reads plausibly over time.

4. **`cover_letter.docx`** (and `cover_letter.txt` for quick copy-paste) — check
   the specifics it cites are consistent with the resume.

### Step 5 — hand-tune (as needed)
Edit `outputs/<run>/tailored_profile.yaml` — fix bullet wording, drop a skill,
tweak the summary or the `cover_letter:` block. Then:

```bash
resume-tailor render outputs/healthpayer-co_senior-backend-engineer_<date>/tailored_profile.yaml
```
Instant, no AI. Repeat until it's right.

### Step 6 — send
Attach `resume.pdf` (or `.docx` if the vendor's ATS wants Word) and paste or
attach the cover letter. The `outputs/<run>/` folder is your permanent record of
what you sent for that requirement — `job.txt`, `requirements.json`, the gap
report, and the final documents all live together.

---

## 7. Tips & patterns

**Keep JDs and outputs.** `jds/` for inputs, `outputs/` for results (already
git-ignored). One folder per requirement = an audit trail of every claim on every
resume you've sent.

**Regenerate vs. re-render.** Changed the master profile or want a different
angle → `tailor` again (AI, ~2 min). Just fixing words → edit
`tailored_profile.yaml` and `render` (instant).

**Multiple resume identities.** Make one profile per target role in the Profiles UI (§3a) —
`ai-engineer`, `data-engineer`, `senior-be` — each with its own `years_experience`, `role_family`
and section layout. Leave the dashboard on **Auto** and the JD picks the profile; the tracker
records which one was used. (Separate `RESUME_TAILOR_HOME` roots are still an option if you want
fully separate output trees.)

**Model choice.** `model: sonnet` is the sweet spot. `opus` for a tougher or more
senior requirement; `haiku` for a quick draft you'll hand-edit anyway.

**Faster loop while drafting.** `--no-pdf` on `tailor`, review the `.docx`, then
do one final `render` (without `--no-pdf`) to get the PDF.

**ATS-friendliness.** The layout is single-column, standard headings, real text
(no tables/text-boxes for content), which parses cleanly in most ATS. Send
`.docx` when the portal offers a choice.

**Batch a morning of applications.**
```bash
for f in jds/*.txt; do
  resume-tailor tailor --jd "$f" --out "$(basename "${f%.txt}")"
done
```
Then review each `outputs/*/gap_report.md`.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `claude CLI not found` | Ensure `claude` is on PATH (`which claude`), or set `claude_binary` in settings, or pick another provider on the Settings tab / `--engine openai|anthropic|ollama|…`. |
| `claude CLI timed out` | Raise `llm_timeout` in settings (e.g. 360). Large JDs + `opus` are slower. |
| `Model did not return valid JSON` | Re-run (usually transient). If it persists, try `--model sonnet`, or shorten/clean the JD. |
| `Invalid master profile: …` | The message lists exactly which field is missing. Every experience needs `client`, `start`, `end`, unique `id`. |
| `pdf engine: fpdf2` and you want exact | `sudo dnf install libreoffice-writer`, re-run (or just `render`). |
| Cover letter references something wrong | Edit `cover_letter:` in `tailored_profile.yaml`, then `render`. |
| Locked field looks wrong on the resume | It's copied from `master_profile.yaml` — fix it there. The tool never invents clients/dates. |
| Want it less aggressive | `--conservative`, or move real backing into the master profile so "missing" skills become "matched". |
| `ANTHROPIC_API_KEY` errors with `--engine anthropic` | `pip install '.[api]'` then set the key (env or Settings tab). |

---

## 9. File map of an output folder

```
outputs/<company>_<role>_<date>/
├── job.txt                 # the JD you fed in (verbatim)
├── requirements.json       # extracted: ranked must-haves, ATS keywords, hard gates, archetype, domains
├── match.md / match.json   # 0-100 fit score + component breakdown + "what's weak"
├── coverage.md / coverage.json  # per must-have: in summary/skills/bullets; hard-gate verdicts; stretch bullets
├── gap_report.md           # matched / partial / missing skills + years required vs available
├── comparison.md           # only with --variants: angles side by side + a recommendation
├── defense.md              # every claim the master profile doesn't fully back: stretch bullets + real pivot material, gates, gaps, pre-submit checklist
├── tailored_profile.yaml   # structured tailored resume + cover_letter (bullets carry `source`) — EDIT, then `render`
├── warnings.txt            # only if the invariant-lock had to correct something
├── resume.docx / resume.pdf
├── resume.txt / resume.md  # same resume as ATS-safe plain text and Markdown
├── cover_letter.docx / cover_letter.pdf
├── cover_letter.txt        # plain text, for pasting into a portal/email
└── <angle>/                # only with --variants: a full set per angle (aggressive / conservative / ic / lead)
```
