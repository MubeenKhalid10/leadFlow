# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

External SaaS customers: people at other companies who sign up and clean their own lead files before an email campaign. They are strangers to the team that builds LeadFlow, are not assumed to be technical, and must be able to get a correct result without anyone walking them through it.

Two roles exist inside the product:

- **User**: uploads a raw lead file, reviews the column mapping, picks which saved lists to suppress against, runs the clean, and downloads campaign files.
- **Admin**: everything a user does, plus maintaining the saved lists on the Lead Database page and promoting or demoting people on the Users & Access page.

## Product Purpose

LeadFlow turns a messy raw lead file into clean, campaign-ready contacts. It standardises the file, removes unusable and unwanted rows, suppresses anyone already held in the saved lists, and exports the result.

A run succeeds when all four of these hold (confirmed as equally important):

1. **Nobody wrong gets emailed.** No contact slips through who is already in Master, has bounced, has unsubscribed, or is an MQL.
2. **Huge files just work.** Files of hundreds of thousands to millions of rows process and export without stalling or crashing.
3. **No training is needed.** A first-time, non-technical user uploads, cleans and downloads correctly without asking anyone.
4. **The numbers can be defended.** Every run states how many rows each step removed and why, and the removed rows can be downloaded.

## Positioning

Suppression data is kept, not re-uploaded. Master, MQL, Bounce and Unsub lists live in PostgreSQL as named lists, so every new file is checked against the customer's whole contact history server-side, and a finished run can be pushed back into Master so those contacts are suppressed next time. Downloading a split (by country or by field) removes those leads from the campaign file, so nobody receives the same campaign twice.

## Operating Context

- The workflow is four steps, in this order and with these names: **Upload → Review → Clean → Download**.
- Input is a CSV or Excel lead file. Only the **Email** column is required; other columns (Company, Location, Industry, Job Title, and so on) are matched automatically and confirmed by the user at Review.
- At Review the user ticks which saved lists to compare against: **Master File, Bounce, MQL, Unsub**.
- Clean removes, in sequence: rows with no email, India-based contacts, rows with garbled characters, duplicates, and anyone on the ticked lists. A step-by-step report follows.
- Download offers the full campaign file (CSV or XLSX), a split by country, a split by field with searchable groups, the removed-rows files, and removal of emails overlapping a second uploaded file.
- Admins work on the **Lead Database** page: four categories (Master File, MQL, Bounce, Unsub), live counts, a storage panel, upload history, and per-upload undo.
- Deployed as a Docker container on AWS (ECS behind an ALB, RDS PostgreSQL); authentication and the role table are in Supabase.

## Capabilities and Constraints

**Confirmed**

- Three pages: Clean Leads (`app.py`), Lead Database (`pages/1_Database.py`, admin), Users & Access (`pages/2_Manage_Users.py`, admin).
- Master uploads merge: only new emails are appended, nothing is replaced.
- Uploads up to 1000 MB are accepted; large-file performance is a product requirement, not an optimisation.
- Sessions persist across refreshes and page changes until the Supabase session expires.
- **Removing India-based contacts is a core, fixed rule of the product** for every customer (detected from the Location column and from `.in` email domains). The user can choose which of the two detection methods apply; the step itself is permanent. Every removed contact is listed and downloadable.
- Terminology in use: *Master File*, *MQL*, *Bounce* / *Bounced*, *Unsub* / *Unsubscribed*, *saved lists*, *campaign file*, *split*.

**Open decisions (not yet made; do not assume an answer)**

- **Multi-tenancy.** Today every signed-in user shares one Master/MQL/Bounce/Unsub database. Per-company separation is planned but not designed. Until it exists, nothing in the interface may imply that a customer's lists are private to their company.
- **Framework.** Whether the UI must remain a Streamlit app (Python with CSS in `theme.py`) or may be rebuilt was asked twice and left unanswered.
- **Device scope.** Whether phone and tablet layouts matter is undecided.
- **Dark mode.** A light theme is currently pinned in `.streamlit/config.toml` to fix white-on-white text in dark-mode browsers; whether light-only is a deliberate product choice is undecided.

## Brand Commitments

- The product name is **LeadFlow**.
- Tagline in the README: "Turn messy lead data into clean, campaign-ready contacts."
- Whether the current indigo (`#4f46e5`) light theme is a binding brand commitment or only the present default is undecided.

## Evidence on Hand

- A working product with real workflows and copy: `app.py`, `pages/`, `theme.py` (including the "How LeadFlow works" dialog text).
- `README.md` and `AWS_DEPLOYMENT.md` describe features and deployment.
- `data/countries.json` is the country and city reference behind the location split.

Absent, and not to be fabricated: customer names or logos, testimonials, case studies, pricing or plans, benchmark figures (rows per second, file-size records), deliverability or accuracy statistics, and compliance or certification claims.

## Product Principles

1. **Suppression is a promise.** A contact that should have been removed and was not is the worst failure the product has. Anything that affects what gets suppressed must be explicit, visible and confirmed by the user, never implied.
2. **Show the arithmetic.** Every removal has a count, a reason and a downloadable list. The user should be able to account for every row between the file they uploaded and the file they downloaded.
3. **A stranger can finish the job.** The product is used by people nobody will train. Each step says what it needs and what it will do in plain language, and the next action is never ambiguous.
4. **Big files are the normal case.** Million-row uploads are routine work. Long operations report progress honestly and never leave the user guessing whether the run is alive.
5. **Do not overstate what is true.** State only what the product does today: shared lists are shared, and claims about privacy, scale or results wait until they are real.
