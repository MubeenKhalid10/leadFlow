---
version: 1
slug: "app-py"
primary_target: "app.py"
related_targets: ["theme.py","Auth.py","pages/1_Database.py","pages/2_Manage_Users.py"]
---

# LeadFlow app surfaces

Scope: the whole signed-in app (Clean Leads, Lead Database, Users & Access) plus the sign-in and access-denied screens. Mode: Operate.

Audience and job: non-technical people at customer companies cleaning a lead file before a campaign; admins maintaining saved lists. They work at a desk on a laptop in office daylight, repeating the same four steps. Success is a correct file and numbers they can defend.

Constraints: Streamlit app; all styling lives in `theme.py` (plus the self-contained sign-in CSS in `Auth.py`) and `.streamlit/config.toml`. Behaviour, copy and workflow are unchanged. The user rejected the previous indigo/purple gradient look as "AI generated" and asked for premium; chose the familiar end of the range on purpose.

## Direction contract

THESIS: LeadFlow reads like a statement from a private bank: nothing decorative, every figure ruled and aligned, confidence carried by restraint. It refuses the category default of floating rounded cards on a tinted ground with a gradient sidebar and a rainbow of coloured buttons.

OWN-WORLD: White page, cool mist (#f2f4f6) as the only second surface, hairline rules (#d5dae0), navy ink (#0c1b33) for type, the sidebar and primary actions, a slightly lighter navy (#1d4e89) for links, focus and the current step. Flat fills only: no gradients, glows, blur or coloured shadows. Corners 4px. Sections are separated by rules, not boxed. Totals close under a double rule. Green, amber and red appear only as meaning (success, caution, removal or delete). Libre Franklin throughout, weight 600 for headings, tabular numerals.

STORY: The visitor sees where they are in four steps, does the one action each step asks for, and leaves with a file and a breakdown they trust.

FIRST VIEWPORT: Flat navy rail on the left, 300px: white LeadFlow mark and name at top, three plain text links, account and sign out at the bottom. Right: white page. Page title in navy at 1.75rem with one sentence under it. Beneath, the four steps as a single ruled row, the current one in navy with a filled marker. Then step 1 under a hairline: its title, the file drop area in mist with a dashed rule, and one navy Upload button, the only filled control in view.

FORM: Private-banking client portal; chosen by the user from the safer re-roll hand (grounded candidate 4 of 7). Seed key 3510e64c.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Signature interaction: the results statement. After cleaning, rows in, each deduction with its reason and share, and rows out are set as one ruled statement that closes under a double rule; the figures align on one right edge.

Unresolved: framework, device scope, dark mode and tenancy remain open in PRODUCT.md.
