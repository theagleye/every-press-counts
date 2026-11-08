# Builds docs/report.pdf from the same markdown files the repository shows, so the PDF and the repo never disagree.
# Needs pandoc, the Mermaid CLI (mmdc) and Python Playwright with Chromium. Optional: the .md files are the source.
import os
import re
import subprocess
import tempfile
from playwright.sync_api import sync_playwright

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
PARTS = ["concept.md", "value.md", "limits.md"]
CSS = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm; }
body { font: 10.5pt/1.5 "Source Sans 3", "DejaVu Sans", Arial, sans-serif; color: #1c232a; }
h1 { font-size: 20pt; margin: 0 0 10pt; page-break-before: always; color: #1c232a; }
h1.title { page-break-before: avoid; font-size: 30pt; margin-top: 60mm; }
h2 { font-size: 13.5pt; margin: 16pt 0 6pt; color: #b06a00; page-break-after: avoid; }
p, li { text-align: left; } p { margin: 0 0 7pt; } ul, ol { margin: 0 0 8pt; padding-left: 18pt; } li { margin-bottom: 3pt; }
img { max-width: 100%; max-height: 225mm; width: auto; height: auto; display: block; margin: 8pt auto; page-break-inside: avoid; }
pre { background: #f2f3f0; border: 1px solid #d3d8dc; border-radius: 4pt; padding: 7pt; font-size: 8.5pt; white-space: pre-wrap; page-break-inside: avoid; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.8pt; }
.sub { font-size: 13pt; color: #5a6571; margin: 0 0 4pt; } .toc { margin-top: 18mm; font-size: 11pt; }
"""


def main():
    tmp = tempfile.mkdtemp()
    body = []
    for f in PARTS:
        md = open(os.path.join(D, f)).read()
        # the workflow diagram is Mermaid on GitHub; the PDF gets the same diagram as an image
        m = re.search(r"```mermaid\n(.*?)```", md, re.S)
        if m:
            src, png = os.path.join(tmp, "flow.mmd"), os.path.join(D, "fig", "workflow.png")
            open(src, "w").write(m.group(1))
            subprocess.run(["mmdc", "-i", src, "-o", png, "-b", "white", "-w", "900", "-s", "2"], check=True, capture_output=True)
            md = md.replace(m.group(0), "![SMART workflow](fig/workflow.png)\n")
        body.append(subprocess.run(["pandoc", "-f", "gfm", "-t", "html"], input=md, text=True, capture_output=True, check=True).stdout)
    title = ('<h1 class="title">Every Press Counts</h1><p class="sub">Weight from stroke counts for Europress SMART</p>'
             '<p class="sub">Europress challenge, Since AI Hackathon 2026, Turku. Team THEAGLEYE. 8 November 2026.</p>'
             '<div class="toc"><p>Part 1: Getting the weight</p><p>Part 2: What the weight is worth, how it runs in SMART, and what Europress can build on it</p>'
             '<p>What this work rests on, and what it does not show</p><p>All data is synthetic, and all euro figures use the dataset\'s hypothetical prices. '
             'Code, results and the demo page are in the repository.</p></div>')
    html = os.path.join(D, "_report.html")
    open(html, "w").write(f"<!doctype html><meta charset='utf-8'><title>Every Press Counts</title><style>{CSS}</style><body>{title}{''.join(body)}</body>")
    foot = '<div style="font-size:8pt;color:#5a6571;width:100%;text-align:center;">Every Press Counts · <span class="pageNumber"></span> / <span class="totalPages"></span></div>'
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto("file://" + os.path.abspath(html))
        pg.wait_for_load_state("networkidle")
        pg.pdf(path=os.path.join(D, "report.pdf"), format="A4", print_background=True, display_header_footer=True,
               header_template="<span></span>", footer_template=foot, margin=dict(top="20mm", bottom="18mm", left="18mm", right="18mm"))
        b.close()
    os.remove(html)
    print("docs/report.pdf written")


if __name__ == "__main__":
    main()
