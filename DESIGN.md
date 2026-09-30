---
name: LeadFlow
description: Lead data cleaning, set like a statement from a private bank.
colors:
  primary: "#12305a"
  primary-hover: "#0c1b33"
  primary-soft: "#e9eef5"
  link: "#1d4e89"
  title: "#0c1b33"
  body: "#36435a"
  muted: "#5a6679"
  placeholder: "#667286"
  bg: "#ffffff"
  mist: "#f2f4f6"
  border: "#d5dae0"
  border-soft: "#e6e9ed"
  input-border: "#8591a3"
  rail: "#0c1b33"
  rail-text: "#c9d3e2"
  rail-muted: "#93a1b8"
  rail-rule: "rgba(255, 255, 255, 0.14)"
  success-soft: "#e8f3ed"
  success-edge: "#b5d6c4"
  success-ink: "#12492f"
  warning: "#8a6100"
  warning-soft: "#fbf3dc"
  warning-edge: "#e2c878"
  warning-ink: "#5c4003"
  danger: "#a3271f"
  danger-hover: "#86201a"
  danger-soft: "#fbecea"
  danger-edge: "#e5b5b0"
  danger-ink: "#7d1d17"
typography:
  display:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "1.2rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "1.02rem"
    fontWeight: 600
  body:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "0.93rem"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "0.74rem"
    fontWeight: 600
    letterSpacing: "0.07em"
  figure:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "0.95rem"
    fontWeight: 600
    fontFeature: "'tnum'"
  figure-closing:
    fontFamily: "'Libre Franklin', 'Segoe UI', sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.1
    fontFeature: "'tnum'"
rounded:
  radius: "4px"
  tag: "2px"
  round: "50%"
spacing:
  control-y: "0.55rem"
  control-x: "0.85rem"
  section-top: "1.1rem"
  section-bottom: "1.75rem"
  page-max: "1140px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.bg}"
    rounded: "{rounded.radius}"
    height: "2.5rem"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.title}"
    rounded: "{rounded.radius}"
    height: "2.5rem"
  button-secondary-hover:
    backgroundColor: "{colors.mist}"
  button-tertiary:
    textColor: "{colors.link}"
    height: "2.25rem"
  button-tertiary-hover:
    textColor: "{colors.primary-hover}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.bg}"
    rounded: "{rounded.radius}"
  button-danger-hover:
    backgroundColor: "{colors.danger-hover}"
  button-disabled:
    backgroundColor: "{colors.border-soft}"
    textColor: "{colors.muted}"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.title}"
    rounded: "{rounded.radius}"
  nav-link:
    textColor: "{colors.rail-text}"
    rounded: "{rounded.radius}"
    padding: "0.55rem 0.85rem"
  nav-link-current:
    backgroundColor: "rgba(255, 255, 255, 0.13)"
    textColor: "{colors.bg}"
  subcard:
    backgroundColor: "{colors.mist}"
    rounded: "{rounded.radius}"
    padding: "0.25rem 1.2rem 1.1rem"
  status-success:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success-ink}"
    rounded: "{rounded.radius}"
    padding: "0.55rem 0.85rem"
  status-warning:
    backgroundColor: "{colors.warning-soft}"
    textColor: "{colors.warning-ink}"
    rounded: "{rounded.radius}"
    padding: "0.55rem 0.85rem"
  status-error:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger-ink}"
    rounded: "{rounded.radius}"
    padding: "0.55rem 0.85rem"
  step-marker:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.muted}"
    rounded: "{rounded.round}"
    size: "26px"
  step-marker-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.bg}"
  tag:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
    rounded: "{rounded.tag}"
    padding: "0.05rem 0.4rem"
---

# Design System: LeadFlow

## Overview

**Creative North Star: "The Private Bank Statement"**

LeadFlow reads like a statement from a private bank: nothing decorative, every figure ruled and aligned, confidence carried by restraint. The page is white. A single cool grey is the only second surface. Navy ink carries the type, the rail and the main action of each section. The product's promise is that the numbers can be defended, so the interface is set the way a reconciliation is set: rows in, each deduction with its reason, rows out, closed under a double rule.

The system is flat. There are no gradients, glows, blur or drop shadows anywhere in the build; the only `box-shadow` in the stylesheet is the keyboard focus ring and the tab underline. A section is a band of the page under a hairline, not a floating box. Colour outside navy appears only when it means something: green for a finished outcome, amber for a caution, red for a failure or a delete.

The look was chosen by the user as the familiar, premium end of the range, replacing an indigo and purple gradient look the user rejected as reading "AI generated".

**Key Characteristics:**
- White page, one cool grey second surface, hairline rules.
- Navy ink for type, the rail and primary actions; a lighter navy for links, carets and focus.
- One face, Libre Franklin, in four weights; figures in tabular numerals on a shared right edge.
- 4px corners on controls and panels; sections have no corners because they have no box.
- Totals close under a double rule.
- State is never carried by colour alone: every state also changes weight, shape, an icon or the words.

## Colors

A navy-on-white palette with cool grey neutrals; three outcome colours used only for meaning.

### Primary
- **Statement Navy** (`primary`, #12305a): filled primary buttons, the step badge, the current step marker, checked boxes and radios, the selected tab's underline, the share bars in the statement, the spinner arc.
- **Ink Navy** (`primary-hover` / `title` / `rail`, #0c1b33): one value in three roles. Headings and strong values, the hover state of primary buttons, and the whole sidebar rail.
- **Link Navy** (`link`, #1d4e89): tertiary (text) buttons, the text caret, the focused field border, and the outer band of the focus ring.
- **Navy Wash** (`primary-soft`, #e9eef5): the hover fill of the file drop area and the ground of the small tag.

### Secondary
- **Ledger Green** (`success-soft` ground, `success-edge` border, `success-ink` text): a finished outcome only ("File uploaded", "108 leads are clean").
- **Caution Amber** (`warning-soft` ground, `warning-edge` border, `warning-ink` text, `warning` icon): something to check, and the note beside an action with a side effect.
- **Removal Red** (`danger`, `danger-hover`, `danger-soft`, `danger-edge`, `danger-ink`): failures, delete and undo buttons, and the hover state of the remove-file button.

### Neutral
- **Page White** (`bg`, #ffffff): the page, fields, secondary buttons, the header bar.
- **Cool Mist** (`mist`, #f2f4f6): the only second surface. Grouped-control panels, the file drop area, row and expander hover, the inline spinner.
- **Hairline** (`border`, #d5dae0): the rule above each section, expander edges, the tab rule, the data grid edge.
- **Soft Hairline** (`border-soft`, #e6e9ed): rules between table rows and statement rows, the bar track, the header's lower edge, the disabled button fill.
- **Field Edge** (`input-border`, #8591a3): the border of every field, secondary button, unchecked box and the dashed drop area. Darker than the hairlines on purpose, so an input reads as an input.
- **Body Ink** (`body`, #36435a): running text, sub-lines, table values.
- **Muted Ink** (`muted`, #5a6679): captions, hints, column heads, heading icons, zero and not-checked rows. Holds 4.5:1 on white and on mist.
- **Placeholder** (`placeholder`, #667286): placeholder text only.
- **Rail Text / Rail Muted / Rail Rule** (`rail-text`, `rail-muted`, `rail-rule`): link text, secondary text and icons, and the two inset rules on the navy rail.

### Named Rules
**The Colour Means Something Rule.** Green, amber and red appear only as an outcome, a caution, or a failure or delete. A next step or a piece of plain information is text with an icon, no tint and no box.

**The One Red Exception Rule.** Buttons are navy, white or text. The single exception is a delete or undo button, which is red in all three ranks.

## Typography

**Display Font:** Libre Franklin (with Segoe UI, sans-serif)
**Body Font:** Libre Franklin (with Segoe UI, sans-serif)
**Label/Mono Font:** none distinct; icons are Material Symbols Rounded, the family Streamlit's own widgets use.

**Character:** One sober grotesque does every job. Hierarchy comes from weight (400, 500, 600, 700) and a narrow size range, not from a second face or from scale contrast.

The face is loaded from Google Fonts by `@import` in the stylesheet and named in `.streamlit/config.toml`. Whether to self-host it is an open decision for the user.

### Hierarchy
- **Display** (600, 1.75rem, line-height 1.2, -0.015em; 1.45rem at 640px and below): the page title, once per page, with one sentence under it at 0.98rem.
- **Headline** (600, 1.2rem, line-height 1.3, -0.01em; 1.1rem at 640px and below): section headings.
- **Title** (600, 1.02rem): sub-headings inside a section and the statement's title. Group labels above related controls sit just under it at 0.95rem, 600.
- **Body** (400, 0.93rem, line-height 1.45): section sub-lines (capped at 95ch), status lines, table values. Captions and hints step down to 0.78rem to 0.87rem in muted ink.
- **Label** (600, 0.74rem, 0.07em, uppercase, muted ink): table column heads, statement group heads, and the per-cell labels that replace the heading row on phones (0.7rem). The small tag uses the same treatment at 0.7rem.
- **Figure** (600, 0.95rem, tabular numerals, right-aligned): counts in the statement and tables. The closing figure is 700 at 1.35rem; metric values are 600 at 1.25rem.

### Named Rules
**The Shared Right Edge Rule.** Figures are set in tabular numerals and right-aligned so every number in a column ends on the same edge.

**The Column Head Rule.** Uppercase tracked type is for labelling a column or a group of figures. It is not used above headings or as running text.

## Layout

A flat navy rail on the left and a white page on the right, with content capped at 1140px. The rail holds the mark and name at the top, the page links under an inset rule, and the account and sign-out pinned to the bottom above a second inset rule. Signed out, the rail is hidden and the sign-in form sits in the centre column of a 1:3:1 split, heading and form on one left edge.

Each page opens with the title and one sentence. Below it the page is a stack of sections, each starting under a hairline with 1.1rem above its heading and 1.75rem below its content. Ordered workflow steps carry a numbered badge; plain sections carry a small muted icon instead, never both. The Clean Leads page puts the four-step strip directly under the page header.

The results statement is capped at 760px so labels and figures stay within one eye movement. Rows inside it are a three-column grid: label, a 90px share bar, a 6.5rem figure.

Responsive behaviour as built:
- **900px and below:** step hints are dropped from the strip.
- **640px and below:** table heading rows are hidden and each cell shows its own label; statement rows drop the share bar; tabs stay on one line and scroll sideways; headings step down.
- **560px and below:** only the current step keeps its label; the others show their marker alone.

## Elevation & Depth

Flat. No drop shadows, no gradients, no blur. Depth is conveyed by three things only: the hairline that opens a section, the mist fill that groups related controls, and the navy rail against the white page. The loading veil is a flat 50% white with no blur, so progress messages stay readable under it.

### Shadow Vocabulary
- **Focus ring** (`box-shadow: 0 0 0 2px #ffffff, 0 0 0 4px #1d4e89`): keyboard focus on every button, link, summary, tab, field, checkbox, radio and the drop area.
- **Focus ring on the rail** (`box-shadow: 0 0 0 2px #0c1b33, 0 0 0 4px #ffffff`): the same ring inverted for controls on navy.
- **Tab underline** (`box-shadow: inset 0 -2px 0 <colour>`): an inset line, not a shadow in effect; hairline on hover, Statement Navy when selected.

### Named Rules
**The Flat Fill Rule.** Every surface is one solid colour. If a surface needs to stand apart, it gets a rule or the mist fill, never a shadow.

## Shapes

Controls and panels have gently squared corners (4px): buttons, fields, the drop area, status lines, the mist panel, the data grid, rail links. The small tag is tighter (2px). Circles (50%) are reserved for markers: the step badge, the step dots, the account initial and the spinner.

Sections, expanders, metrics and tabs have no radius at all because they are drawn with rules rather than boxes: a top hairline for a section or a metric, top and bottom hairlines for an expander, a bottom rule for the tab list.

Borders are always 1px, with two exceptions that carry meaning: the 6px double rule that closes the statement, and the 2px underline of a tab. Dashed 1px borders mark places waiting for content: the file drop area and empty states.

Motion is limited to state changes: background, border and text colour ease over 0.15s (0.2s on the step strip). The loading veil fades in over 0.2s only after a 0.4s delay, so quick reruns do not flash. All of it collapses under `prefers-reduced-motion`.

## Components

### Buttons
Plain and ranked; one hierarchy everywhere.
- **Shape:** gently squared (4px), 2.5rem minimum height, 600 weight at 0.92rem.
- **Primary:** filled Statement Navy with white text; the one main action of a section. The file uploader's Upload button takes this rank.
- **Secondary:** white with a Field Edge border and Ink Navy text; hover fills with mist and darkens the border.
- **Tertiary:** Link Navy text, 2.25rem; hover darkens and underlines.
- **Delete / undo:** the same three ranks in Removal Red.
- **Disabled:** Soft Hairline fill, muted text, hairline border, full opacity.
- **On the rail:** transparent with a 32% white border and white text; hover fills 10% white.
- **Focus:** the two-tone focus ring.

### Tags
- **Style:** Navy Wash ground, Statement Navy text, 2px corners, 0.7rem uppercase at 600. Marks a fact about a row ("You", the current role on the access-denied screen). Not interactive.

### Sections and Panels
- **Section:** transparent, no border except a hairline on top, no radius, 0.4rem above and 1.75rem below.
- **Panel:** mist fill, 4px corners, no border, 1.2rem side padding; holds a group of related controls inside a section.
- **Section heading:** numbered navy badge (26px circle) for ordered steps, or a muted icon for plain sections, then the heading and one sub-line.

### Inputs / Fields
- **Style:** white, 1px Field Edge border, 4px corners; labels are 600 in Ink Navy.
- **Hover:** border darkens to Ink Navy.
- **Focus:** border turns Link Navy with the focus ring.
- **Checkbox / radio:** Field Edge outline; Statement Navy when checked. Long labels wrap rather than clip.
- **File drop area:** mist fill with a dashed Field Edge border; hover turns the border Statement Navy and the fill Navy Wash.

### Navigation
- **Rail:** flat Ink Navy, no border. White mark and name, then an inset rule.
- **Link:** 0.9rem, 500, Rail Text, with a Rail Muted icon; 4px corners; hover fills 7% white.
- **Current page:** a lighter filled row (13% white) with white 700 text and a white icon, so it does not rely on colour alone.
- **Locked page:** shown disabled with "(admins only)" in the label.
- **Tabs:** plain text on a hairline rule, 1.75rem apart. The selected tab is Ink Navy, 700, with a 2px Statement Navy underline.

### Status Lines and Notes
- **Outcome (success, warning, error):** a one-line tinted box with a 1px edge, 4px corners, a leading icon, a 600 title and optional body-ink detail.
- **Next step and information:** the same line with no tint, no border and no side padding.
- **Note:** an amber box at 0.87rem, 500, beside an action with a side effect.
- **Empty state:** centred, white, dashed 1px border, a muted icon, a 600 title and one line saying what to do.

### Workflow Strip
Four steps on one ruled line. A step not yet reached is a white outlined circle with its number in muted ink. A finished step is a white circle outlined in Statement Navy with a tick. The current step is filled Statement Navy with its number in white and its label at 700. The connecting rule turns from hairline to Statement Navy as steps complete.

### Table Rows
A heading row of uppercase labels closed by a 1px Ink Navy rule, then rows separated by soft hairlines, 0.55rem tall padding, mist on hover. The first value in a row may be strong (600, Ink Navy). Email addresses read as plain values, not links.

### Metrics
A label (0.82rem, 500, muted) and a value (1.25rem, 600, tabular) under a top hairline. No box, no large number.

### The Statement (signature)
"Why were leads removed?" set as a reconciliation. It opens with the rows in the file between an Ink Navy rule and a hairline. Each group of reasons has an uppercase head with its subtotal on the right, closed by an Ink Navy rule. Each reason is a row: label with a small hint under it, a 4px share bar, and the figure. Zero rows and unchecked lists drop to muted 400 and say "Not checked" rather than showing a bar. "Total removed" sits over an Ink Navy rule, and "Clean leads" closes the statement under a 6px double rule with the largest figure on the page.

## Do's and Don'ts

### Do:
- **Do** open every section with a 1px hairline (#d5dae0) and leave it unboxed.
- **Do** use mist (#f2f4f6) as the only second surface, for grouping related controls.
- **Do** give each section one filled navy action; everything else is a white bordered button or a text button.
- **Do** set figures in tabular numerals on a shared right edge, and close a total under the double rule.
- **Do** pair every state with a second signal: weight, a filled versus outlined shape, an icon, or the words.
- **Do** keep field borders at #8591a3 so inputs stay visibly inputs.
- **Do** keep the two-tone focus ring on every interactive control, inverted on the rail.
- **Do** keep corners at 4px on controls and panels.

### Don't:
- **Don't** use gradients, glows, blur or drop shadows; the build has none.
- **Don't** float sections as rounded cards on a tinted ground.
- **Don't** use green, amber or red for decoration or for ranking buttons; red buttons are for delete and undo only.
- **Don't** tint or box a next step or plain information; only outcomes get a tinted line.
- **Don't** put both a step badge and an icon on one section heading.
- **Don't** enlarge metrics into hero numbers; the only large figure is the statement's closing line.
- **Don't** add a second typeface.
