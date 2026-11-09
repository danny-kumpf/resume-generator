// Resume template. Content lives in resume.yaml and the contact block in
// contact.yaml (gitignored); this file only does layout.
//
// Build:   typst compile resume.typ Kumpf_Resume.pdf
// Live:    typst watch resume.typ Kumpf_Resume.pdf
// Variant: typst compile resume.typ out.pdf --input data=other_content.yaml
// Contact: typst compile resume.typ out.pdf --input contact=contact.example.yaml

#let data = yaml(sys.inputs.at("data", default: "resume.yaml"))
#let contact-lines = yaml(sys.inputs.at("contact", default: "contact.yaml"))

// ---------------------------------------------------------------------------
// Style knobs
// ---------------------------------------------------------------------------
#let style = (
  font: ("Arial", "Liberation Sans"),
  body-size: 11pt,
  name-size: 35pt,
  contact-size: 9pt,
  section-title-size: 14pt,
  // Heading of each entry (a job, school, or project); role titles within an
  // entry stay at body size.
  entry-heading-size: 12pt,
  // Gap between consecutive lines of text (descender to next line's ascender).
  line-gap: 0.42em,
  link-color: rgb("#1a1aa6"),
  margin: (left: 0.5in, right: 0.45in, top: 0.45in, bottom: 0.45in),
  bullet-indent: 0in,
  // Gap between a bullet marker and its text. Keep it under about 0.15in:
  // poppler's pdftotext treats a wider gap as a column break and reads all the
  // markers before any of the bullet text (tests/test_text_extraction.py).
  bullet-body-indent: 0.14in,
  // Rule under each section title, and the lighter rule between entries.
  section-rule: 1.2pt + black,
  entry-rule: 0.5pt + luma(150),
  // Gap between a section title's rule and its first entry.
  section-title-gap: 4pt,
)

// Vertical spacing between blocks. Each gap is its minimum size plus a share
// of whatever page height is left over, so the page fills evenly and removing
// a line spreads the freed space across every gap instead of leaving it at
// the bottom. A section gap takes `weight` times the share an entry gap gets.
// Each share is capped at `max-growth-per-weight`, so a much shorter resume
// stops spreading out and leaves the remainder blank at the bottom.
#let spacing = (
  after-header: (min: 2pt, weight: 0.5),
  section: (min: 9pt, weight: 2),
  entry: (min: 5pt, weight: 1),
  max-growth-per-weight: 8pt,
)

// ---------------------------------------------------------------------------
// Inline markup: **bold**, [label](url), and bare http(s) URLs.
// ---------------------------------------------------------------------------
#let styled-link(url, label) = link(url, text(fill: style.link-color, label))

#let inline-markup = regex(
  "\\*\\*(.+?)\\*\\*"                          // **bold**
  + "|\\[([^\\]]+)\\]\\(([^)\\s]+)\\)"         // [label](url)
  + "|(https?://[^\\s,)]*[^\\s,).])",          // bare URL, minus trailing punctuation
)

#let rich(s) = {
  let pieces = ()
  let cursor = 0
  for m in s.matches(inline-markup) {
    pieces.push(s.slice(cursor, m.start))
    let (bold, label, url, bare-url) = m.captures
    if bold != none {
      pieces.push(strong(rich(bold)))
    } else if label != none {
      pieces.push(styled-link(url, label))
    } else {
      pieces.push(styled-link(bare-url, bare-url))
    }
    cursor = m.end
  }
  pieces.push(s.slice(cursor))
  pieces.join()
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------
#let header = grid(
  columns: (1fr, auto),
  column-gutter: 1em,
  text(
    size: style.name-size,
    weight: "bold",
    underline(stroke: 0.06em, offset: 0.12em, data.name),
  ),
  pad(top: 0.4em, text(size: style.contact-size, {
    set par(leading: 0.3em)
    contact-lines.map(rich).join(linebreak())
  })),
)

#let section-title(title) = {
  text(size: style.section-title-size, weight: "bold", upper(title))
  v(0.12em, weak: true)
  line(length: 100%, stroke: style.section-rule)
  v(style.section-title-gap, weak: true)
}

// A title on the left and (optional) dates flush right, on one line.
//
// The gap between them is filled with spaces rather than left empty. Spaces
// are invisible, but they are real characters in the PDF's text layer, so
// text extractors that group characters by position (pdfminer, and the
// resume parsers built on it) see one line instead of a separate column of
// dates, which they would otherwise splice into the middle of bullets. The
// 1em box of spaces before the dates stands in for a column gutter.
#let title-line(title, dates) = grid(
  columns: (1fr, auto),
  strong(rich(title)) + box(width: 1fr, repeat(" ")),
  box(width: 1em, repeat(" ")) + strong(dates),
)

// A bullet is either a string, or a dictionary with `text` and nested `bullets`.
#let bullet-list(items) = list(..items.map(item => {
  if type(item) == str {
    rich(item)
  } else {
    rich(item.text)
    bullet-list(item.bullets)
  }
}))

// A role within an entry: its title line, then its own bullets.
#let role-block(role) = {
  title-line(role.title, role.at("dates", default: ""))
  if "bullets" in role {
    bullet-list(role.bullets)
  }
}

// Entry-level bullets describe the whole entry, so they come before its roles.
#let entry(e) = {
  if "heading" in e {
    text(size: style.entry-heading-size, title-line(e.heading, e.at("dates", default: "")))
  }
  if "bullets" in e {
    bullet-list(e.bullets)
  }
  for role in e.at("roles", default: ()) {
    role-block(role)
  }
}

// The whole page body, with each gap's share of leftover space set to
// `growth-per-weight`.
#let page-body(growth-per-weight) = {
  let gap-height(kind) = kind.min + kind.weight * growth-per-weight
  // Entries are separated by a light rule centered in the entry gap.
  let entry-divider = {
    let half-gap = gap-height(spacing.entry) / 2
    v(half-gap)
    line(length: 100%, stroke: style.entry-rule)
    v(half-gap)
  }
  header
  for (i, section) in data.sections.enumerate() {
    v(gap-height(if i == 0 { spacing.after-header } else { spacing.section }))
    section-title(section.title)
    for (i, e) in section.entries.enumerate() {
      if i > 0 { entry-divider }
      entry(e)
    }
  }
}

#let total-gap-weight = (
  spacing.after-header.weight
  + (data.sections.len() - 1) * spacing.section.weight
  + data.sections.map(s => (s.entries.len() - 1) * spacing.entry.weight).sum()
)

// ---------------------------------------------------------------------------
// Document
// ---------------------------------------------------------------------------
#set document(title: data.name + " – Resume", author: data.name)
#set page(paper: "us-letter", margin: style.margin)
#set text(font: style.font, size: style.body-size, lang: "en")
#set par(leading: style.line-gap, spacing: style.line-gap)
#set block(spacing: style.line-gap)
#set list(
  marker: ([•], [•]),
  indent: style.bullet-indent,
  body-indent: style.bullet-body-indent,
  spacing: style.line-gap,
)

#layout(available => {
  let natural-height = measure(page-body(0pt), width: available.width).height
  let leftover = available.height - natural-height
  let growth-per-weight = calc.min(
    calc.max(leftover / total-gap-weight, 0pt),
    spacing.max-growth-per-weight,
  )
  page-body(growth-per-weight)
})
