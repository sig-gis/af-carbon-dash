// Some definitions presupposed by pandoc's typst output.
#let blockquote(body) = [
  #set text( size: 0.92em )
  #block(inset: (left: 1.5em, top: 0.2em, bottom: 0.2em))[#body]
]

#let horizontalrule = line(start: (25%,0%), end: (75%,0%))

#let endnote(num, contents) = [
  #stack(dir: ltr, spacing: 3pt, super[#num], contents)
]

#show terms: it => {
  it.children
    .map(child => [
      #strong[#child.term]
      #block(inset: (left: 1.5em, top: -0.4em))[#child.description]
      ])
    .join()
}

// Some quarto-specific definitions.

#show raw.where(block: true): set block(
    fill: luma(230),
    width: 100%,
    inset: 8pt,
    radius: 2pt
  )

#let block_with_new_content(old_block, new_content) = {
  let d = (:)
  let fields = old_block.fields()
  fields.remove("body")
  if fields.at("below", default: none) != none {
    // TODO: this is a hack because below is a "synthesized element"
    // according to the experts in the typst discord...
    fields.below = fields.below.abs
  }
  return block.with(..fields)(new_content)
}

#let empty(v) = {
  if type(v) == str {
    // two dollar signs here because we're technically inside
    // a Pandoc template :grimace:
    v.trim().len() == 0
  } else if type(v) == content {
    if v.at("text", default: none) != none {
      return empty(v.text)
    }
    for child in v.at("children", default: ()) {
      if not empty(child) {
        return false
      }
    }
    return true
  }

}

// Subfloats
// This is a technique that we adapted from https://github.com/tingerrr/subpar/
#let quartosubfloatcounter = counter("quartosubfloatcounter")

#let quarto_super(
  kind: str,
  caption: none,
  label: none,
  supplement: str,
  position: none,
  subrefnumbering: "1a",
  subcapnumbering: "(a)",
  body,
) = {
  context {
    let figcounter = counter(figure.where(kind: kind))
    let n-super = figcounter.get().first() + 1
    set figure.caption(position: position)
    [#figure(
      kind: kind,
      supplement: supplement,
      caption: caption,
      {
        show figure.where(kind: kind): set figure(numbering: _ => numbering(subrefnumbering, n-super, quartosubfloatcounter.get().first() + 1))
        show figure.where(kind: kind): set figure.caption(position: position)

        show figure: it => {
          let num = numbering(subcapnumbering, n-super, quartosubfloatcounter.get().first() + 1)
          show figure.caption: it => {
            num.slice(2) // I don't understand why the numbering contains output that it really shouldn't, but this fixes it shrug?
            [ ]
            it.body
          }

          quartosubfloatcounter.step()
          it
          counter(figure.where(kind: it.kind)).update(n => n - 1)
        }

        quartosubfloatcounter.update(0)
        body
      }
    )#label]
  }
}

// callout rendering
// this is a figure show rule because callouts are crossreferenceable
#show figure: it => {
  if type(it.kind) != str {
    return it
  }
  let kind_match = it.kind.matches(regex("^quarto-callout-(.*)")).at(0, default: none)
  if kind_match == none {
    return it
  }
  let kind = kind_match.captures.at(0, default: "other")
  kind = upper(kind.first()) + kind.slice(1)
  // now we pull apart the callout and reassemble it with the crossref name and counter

  // when we cleanup pandoc's emitted code to avoid spaces this will have to change
  let old_callout = it.body.children.at(1).body.children.at(1)
  let old_title_block = old_callout.body.children.at(0)
  let old_title = old_title_block.body.body.children.at(2)

  // TODO use custom separator if available
  let new_title = if empty(old_title) {
    [#kind #it.counter.display()]
  } else {
    [#kind #it.counter.display(): #old_title]
  }

  let new_title_block = block_with_new_content(
    old_title_block, 
    block_with_new_content(
      old_title_block.body, 
      old_title_block.body.body.children.at(0) +
      old_title_block.body.body.children.at(1) +
      new_title))

  block_with_new_content(old_callout,
    block(below: 0pt, new_title_block) +
    old_callout.body.children.at(1))
}

// 2023-10-09: #fa-icon("fa-info") is not working, so we'll eval "#fa-info()" instead
#let callout(body: [], title: "Callout", background_color: rgb("#dddddd"), icon: none, icon_color: black, body_background_color: white) = {
  block(
    breakable: false, 
    fill: background_color, 
    stroke: (paint: icon_color, thickness: 0.5pt, cap: "round"), 
    width: 100%, 
    radius: 2pt,
    block(
      inset: 1pt,
      width: 100%, 
      below: 0pt, 
      block(
        fill: background_color, 
        width: 100%, 
        inset: 8pt)[#text(icon_color, weight: 900)[#icon] #title]) +
      if(body != []){
        block(
          inset: 1pt, 
          width: 100%, 
          block(fill: body_background_color, width: 100%, inset: 8pt, body))
      }
    )
}



#let article(
  title: none,
  subtitle: none,
  authors: none,
  date: none,
  abstract: none,
  abstract-title: none,
  cols: 1,
  margin: (x: 1.25in, y: 1.25in),
  paper: "us-letter",
  lang: "en",
  region: "US",
  font: "libertinus serif",
  fontsize: 11pt,
  title-size: 1.5em,
  subtitle-size: 1.25em,
  heading-family: "libertinus serif",
  heading-weight: "bold",
  heading-style: "normal",
  heading-color: black,
  heading-line-height: 0.65em,
  sectionnumbering: none,
  pagenumbering: "1",
  toc: false,
  toc_title: none,
  toc_depth: none,
  toc_indent: 1.5em,
  doc,
) = {
  set page(
    paper: paper,
    margin: margin,
    numbering: pagenumbering,
  )
  set par(justify: true)
  set text(lang: lang,
           region: region,
           font: font,
           size: fontsize)
  set heading(numbering: sectionnumbering)
  if title != none {
    align(center)[#block(inset: 2em)[
      #set par(leading: heading-line-height)
      #if (heading-family != none or heading-weight != "bold" or heading-style != "normal"
           or heading-color != black) {
        set text(font: heading-family, weight: heading-weight, style: heading-style, fill: heading-color)
        text(size: title-size)[#title]
        if subtitle != none {
          parbreak()
          text(size: subtitle-size)[#subtitle]
        }
      } else {
        text(weight: "bold", size: title-size)[#title]
        if subtitle != none {
          parbreak()
          text(weight: "bold", size: subtitle-size)[#subtitle]
        }
      }
    ]]
  }

  if authors != none {
    let count = authors.len()
    let ncols = calc.min(count, 3)
    grid(
      columns: (1fr,) * ncols,
      row-gutter: 1.5em,
      ..authors.map(author =>
          align(center)[
            #author.name \
            #author.affiliation \
            #author.email
          ]
      )
    )
  }

  if date != none {
    align(center)[#block(inset: 1em)[
      #date
    ]]
  }

  if abstract != none {
    block(inset: 2em)[
    #text(weight: "semibold")[#abstract-title] #h(1em) #abstract
    ]
  }

  if toc {
    let title = if toc_title == none {
      auto
    } else {
      toc_title
    }
    block(above: 0em, below: 2em)[
    #outline(
      title: toc_title,
      depth: toc_depth,
      indent: toc_indent
    );
    ]
  }

  if cols == 1 {
    doc
  } else {
    columns(cols, doc)
  }
}

#let top-margin = 1.25in

#set page(
  background: image("data/fig/watermark.jpg", width: 100%, height: 100%)
)

#set table(
  inset: 6pt,
  stroke: none
)
#let brand-color = (
  background: rgb("#ffffff"),
  charcoal-grey: rgb("#0B193B"),
  foreground: rgb("#555555"),
  forest-green: rgb("#005251"),
  orange: rgb("#E94D4D"),
  primary: rgb("#005251"),
  secondary: rgb("#E94D4D"),
  white: rgb("#ffffff")
)
#set page(fill: brand-color.background)
#set text(fill: brand-color.foreground)
#set table.hline(stroke: (paint: brand-color.foreground))
#set line(stroke: (paint: brand-color.foreground))
#let brand-color-background = (
  background: color.mix((brand-color.background, 15%), (brand-color.background, 85%)),
  charcoal-grey: color.mix((brand-color.charcoal-grey, 15%), (brand-color.background, 85%)),
  foreground: color.mix((brand-color.foreground, 15%), (brand-color.background, 85%)),
  forest-green: color.mix((brand-color.forest-green, 15%), (brand-color.background, 85%)),
  orange: color.mix((brand-color.orange, 15%), (brand-color.background, 85%)),
  primary: color.mix((brand-color.primary, 15%), (brand-color.background, 85%)),
  secondary: color.mix((brand-color.secondary, 15%), (brand-color.background, 85%)),
  white: color.mix((brand-color.white, 15%), (brand-color.background, 85%))
)
#set text(weight: 400, )
#set par(leading: 0.75em)
#show heading: set text(font: ("Montserrat",), weight: 600, style: "normal", fill: brand-color.primary, )
#show heading: set par(leading: 0.45em)
#show link: set text(fill: brand-color.primary, baseline: -0.5pt,)
#show link: underline.with(stroke: 0.7pt + brand-color.primary)

#show: doc => article(
  margin: (top: 0in,),
  font: ("Open Sans",),
  pagenumbering: "1",
  toc_title: [Table of contents],
  toc_depth: 3,
  cols: 1,
  doc,
)

#set figure(numbering: none)
#show figure.caption: set align(left)
#block(fill: brand-color.primary, width: 100%, height: 1.5in, outset: (x: 1.25in))[
#show heading.where(level: 1): set text(fill: white, size: 36pt)
#place(bottom + left, dy:-0.25in)[

#heading(level: 1, outlined: false)[Resilient Reforestation Plan]
<gresham>
]
// Conditional logo - uncomment when AFlogo3.png is available
// #place(top + right, dx: 0.8in, dy: 0.4in)[
// #box(image("data/fig/AFlogo3.png", width: 1.5in))
// ]
]

#include "report_files/figure-typst/variant-image.typ"

#line(length: 100%, stroke: 0.5pt + gray)
#v(0.5cm)  // vertical gap

#grid(
  columns: 2,
  column-gutter: 2.5cm,
  [
    #include "report_files/figure-typst/strategy-summary.typ"
  ],
  [
    #include "report_files/figure-typst/species-mix.typ"
  ]
)

#pagebreak()
#v(top-margin)

#show outline.entry: set block(spacing: 2em)
#outline()

#pagebreak()
#v(top-margin)

#heading(level: 1)[Introduction]

#v(0.5cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[This report was generated directly from the #link("https://nwgiebink-af-carbon-dash.share.connect.posit.cloud/")[Reforestation Financial & Carbon Dashboard]. The dashboard allows users to adjust planting parameters (species mix, site index, and survival), select one or more carbon accounting protocols, and adjust financial options. Forest stand metrics, such as cumulative onsite carbon, are calculated in real-time based on user inputs and are used to estimate carbon credits and associated project financials.]
]

#v(0.25cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[The report uses predictions from machine learning models trained to approximate outputs from the Forest Vegetation Simulator (FVS) - a widely applied, publicly available forest growth and yield model used across the United States. Each FVS variant represents a specific geographic region and contains its own calibrated parameters, species list, growth equations, and ecological assumptions; our machine learning models are trained to capture variant-level differences represented by FVS. Selecting a variant ensures that tree growth, mortality, and carbon accumulation are modeled in a way that reflects the environmental conditions of the project location.]
]

#v(0.25cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[The chosen variant for this report is based on the spatial location of the project (Figure 1). Each variant includes its own set of species capable of growing within that region; this report uses those built-in species definitions to generate growth and carbon estimates. Only the species selected in the dashboard (shown on page 1) were used to simulate future stand development.]
]

#v(0.25cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[The dashboard supports multiple carbon accounting protocols, but only the accounting protocols selected by the user in the dashboard are included in the carbon and financial projections below.]
]

#pagebreak()
#v(top-margin)

#heading(level: 1)[Carbon Projections]

#v(0.25cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[The carbon projections presented here are generated using the ML-approximated FVS growth model for the selected species mix and site conditions. FVS simulates tree- and stand-level carbon accumulation over time, including live biomass, mortality, and structural changes in the forest. The dashboard combines these raw five-year outputs and interpolates them to produce annual estimates of on-site carbon storage. This approach preserves the long-term growth trends modeled by FVS while providing more continuous year-by-year results.]
]

#v(0.15cm)  // vertical gap

#figure([
#box(image("report_files/figure-typst/cell-11-output-1.svg", width: 65%))
], caption: figure.caption(
position: bottom, 
[
  #align(center)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Figure 2. Annual cumulative onsite Carbon per acre (tons CO₂ per acre).]
]
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)

#v(0.25cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[Figure 2 shows the total net carbon stored over time within one acre, accounting for all modeled growth and mortality. The shape of the curve reflects the selected species' biological growth pattern and the productivity defined by the site index.]
]

#v(0.05cm)  // vertical gap

#figure([
#box(image("report_files/figure-typst/cell-12-output-1.svg", width: 65%))
], caption: figure.caption(
position: bottom, 
[
  #align(center)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Figure 3. Annual cumulative onsite Carbon for the full project area (tons CO₂).]
]
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)

#pagebreak()
#v(top-margin)

#align(left)[
  #text(weight: "bold", size: 11pt)[Different carbon protocols apply unique sets of rules related to risk buffers, leakage deductions, and measurement requirements. Because the same biological growth can be credited differently depending on these rules, different protocols may yield different carbon units (CUs) over time, even for the same underlying forest scenario.]
]

#v(0.25cm)  // vertical gap

#figure([
#box(image("report_files/figure-typst/cell-13-output-1.svg", width: 70%))
], caption: figure.caption(
position: bottom, 
[
  #align(center)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Figure 4.  Annual Carbon Units for the full project area by selected protocols.]
]
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)

#v(0.35cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[The dashboard standardizes biological modeling by using ML-approximated FVS for all protocols (see FAQs), and then applies protocol-specific rules to calculate eligible credits. This ensures that differences shown in the graphs reflect accounting rules, not differences in forest growth modeling.]
]

#pagebreak()
#v(top-margin)

#heading(level: 1)[Financial Projections]
#v(0.5cm)  // vertical gap

#align(left)[
  #text(weight: "bold", size: 11pt)[The financial projections integrate user-selected financial inputs with modeled carbon outputs to estimate annual and cumulative revenues and costs for the project.]
]

#v(0.25cm)  // vertical gap

#heading(level: 3, outlined: false)[Selected Financial Options:]

#grid(
  columns: 2,
  column-gutter: 2.5cm,
  [
    #include "report_files/figure-typst/financial-options1.typ"
  ],
  [
    #include "report_files/figure-typst/financial-options2.typ"
  ]
)

#v(0.25cm)  // vertical gap

#heading(level: 3, outlined: false)[Carbon Revenue]

Annual carbon revenues are calculated by multiplying the annual number of carbon units
(CUs) generated under each protocol by the assumed market price in that year. The initial
price per CU and the annual price increase rate are set by the user. These annual revenues
are summed across the project period to produce the total revenue values.

#v(0.25cm)  // vertical gap
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Table 1. Per-protocol financial projections sorted by Net Revenue (USD), from highest to lowest.]
]

#align(center)[
  #include "report_files/figure-typst/protocol-summary.typ"
]

#v(0.15cm)  // vertical gap

The following cost categories are included in the projection:

- CFI plot costs and number of plots, which determine sampling and field verification
  costs.
- Validation and verification costs, which occur at fixed intervals according to
  protocol rules.
- Registry fees and issuance fees per CU, which apply during the credit registration
  and issuance process.
- Initial planting costs and seedling costs, applied at the start of the project.
- Anticipated inflation, applied to verification-related and registry-related expenses.
- Discount rate, which is used in calculation of the 20-year net present value.

Net revenue represents the difference between Total Revenue and Total Costs.

#pagebreak()
#v(top-margin)

Table 1, Figure 5 and Figure 6 summarize the Net Revenue, including the Total Revenue and Total Costs across the project
lifetime and compare financial performance across the selected protocols.

#figure([
#box(image("report_files/figure-typst/cell-20-output-1.svg", width: 60%))
], caption: figure.caption(
position: bottom, 
[
  #align(center)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Figure 5. Total Revenue (in millions of USD) generated by each protocol over the full project period, including both Net Revenue and Total Costs from the selected planting scenario]
  ]
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)

#v(0.25cm)  // vertical gap


#align(left)[
  #text(weight: "bold", size: 11pt)[The annual net revenue trend illustrates how project cashflow varies over time. Peaks typically correspond to verification or credit issuance years, as CUs are credited in discrete events rather than every year.]
]

#v(0.15cm)  // vertical gap

#figure([
#box(image("report_files/figure-typst/cell-21-output-1.svg", width: 60%))
], caption: figure.caption(
position: bottom, 
[
  #align(center)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Figure 6. Annual net revenue trends by protocol for the selected planting scenario across the duration of the project]
]
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)

#pagebreak()
#v(top-margin)

#heading(level: 1)[Frequently Asked Questions]

#v(0.5cm)  // vertical gap

#block[

#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[What does "Cumulative Onsite Carbon" mean?]
]

Cumulative Onsite Carbon is the net amount of carbon stored within a project area over time, adding up all eligible carbon.  
It reflects everything that happens within each acre in the selected variant.
]
#v(0.5cm)  // vertical gap

#block[
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[What is the baseline scenario assumption?]
]

The baseline scenario in the current version of the dashboard assumes bare ground with no natural regeneration.
]
#v(0.5cm)  // vertical gap

#block[
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[What Forest Vegetation Simulator (FVS) modeling approach is applied?]
]

The current version of the dashboard approximates a let-grow simulation for the duration of the project, with a growth/reporting interval of 5 years.
]
#v(0.5cm)  // vertical gap

#block[
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[How are the five-year outputs converted to annual CO₂e/ac stocking values?]
]

We apply a cubic spline interpolation to create continuous annual stocking values from 5-year intervals.
]
#v(0.5cm)  // vertical gap

#block[
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[What is the difference between the carbon protocols?]
]

The same project scenario can yield different credit numbers across protocols because of differences in accounting rules #footnote[To isolate protocol-rule effects, the dashboard uses FVS modules for all protocols (we do not switch between Jenkins and FVS).].  
Below are the protocols currently supported in the dashboard and the modeled assumptions for risk/buffer #footnote[The 25% risk buffer for Isometric reflects a valid value within their allowed range. Because the dashboard compares default assumptions, 20% would be most consistent across protocols. However, the current 25% value serves as a placeholder until the financial verification cost step is implemented, which will further differentiate Isometric from the others. This value will be updated in future versions.], leakage, uncertainty, and measurement.

#table(
  columns: 5,
  align: (left, center, center, center, center),
  table.header(
    [Protocol],
    [Risk/Buffer],
    [Leakage],
    [Uncertainty],
    [Measurement],
  ),
  [#link("https://verra.org/methodologies/vm0047-afforestation-reforestation-and-revegetation-v1-0/")[Verra (VCS)]], [20%], [0%], [0%], [FVS],
  [#link("https://acrcarbon.org/methodology/afforestation-and-reforestation-of-degraded-lands/")[ACR]], [20%], [0%], [0%], [FVS],
  [#link("https://www.climateactionreserve.org/wp-content/uploads/2023/07/Final_Forest_Protocol_V5.1_7.14.2023.pdf")[CAR]], [20%], [0%], [0%], [FVS],
  [#link("https://registry.isometric.com/protocol/reforestation/1.0")[Isometric]], [25%], [0%], [0%], [FVS],
  [#link("https://globalgoals.goldstandard.org/403-luf-ar-methodology-ghgs-emission-reduction-and-sequestration-methodology/")[Gold Standard]], [0%], [0%], [0%], [FVS],
)

]

#pagebreak()
#v(top-margin)

#block[
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[How are FVS simulations approximated for real-time analysis in the dashboard?]
]

We run a sample of single-stand FVS simulations representing the project lifetime over a range of possible combinations of planting parameters, repeated over each supported FVS Variant with variant-appropriate species. Using this representative sample of FVS simulations as a training set, we train Polynomial Regression models to predict FVS outputs for each timestep across the project lifetime. Each time the user tweaks planting parameters, the models make real-time predictions of FVS outputs, without the latency of running an FVS simulation.
]
#v(0.5cm)  // vertical gap

#block[
#align(left)[
  #text(weight: "bold", size: 11pt, fill: brand-color.primary)[Is it possible to model an unrealistic scenario?]
]

Yes.  
The dashboard would have warned you if the total TPA (trees per acre) for either of the tree species exceeded a cap, but extreme inputs can still produce unrealistic scenarios.
]
