"""Layout checks for the operator pages that only a browser can answer.

`tests/pagecheck.py` asserts what the markup promises. These assert what the
rendering delivers: that nothing overflows sideways, that every piece of text
clears WCAG AA against the surface behind it, and that a drawing is never shown
at a size where its own labels stop being readable.

    python3 tools/pagecheck-browser.py PAGE.html [PAGE.html ...]

Needs `playwright` and its Chromium, which is why it is a tool rather than part
of `tests/run.sh` — the suite must stay runnable with a bare Python.
"""

from __future__ import annotations

import sys

WIDTHS = (1600, 1440, 1180, 1057, 1055, 900, 719, 700, 639, 500, 390)
# Below this a label has stopped being information. The map is hidden rather
# than shrunk past it; the rail underneath carries the same sequence in text.
MIN_LABEL_PX = 9.0

CONTRAST = """() => {
  const parse = c => (c.match(/[\\d.]+/g) || []).map(Number);
  const lin = v => { v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); };
  const lum = ([r,g,b]) => .2126*lin(r) + .7152*lin(g) + .0722*lin(b);
  const ratio = (a,b) => { const l1=lum(a), l2=lum(b), hi=Math.max(l1,l2), lo=Math.min(l1,l2);
                           return (hi+.05)/(lo+.05); };
  const ground = el => { let n = el;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c.length >= 3 && (c[3] === undefined || c[3] > 0)) return c.slice(0,3);
      n = n.parentElement; }
    return parse(getComputedStyle(document.body).backgroundColor).slice(0,3); };
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || el.closest('.vh,.skip')) return;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
    const fg = parse(s.color), bg = ground(el);
    const a = (fg[3] === undefined ? 1 : fg[3]) * (parseFloat(s.opacity) || 1);
    const eff = fg.slice(0,3).map((v,i) => v*a + bg[i]*(1-a));
    const px = parseFloat(s.fontSize), bold = parseInt(s.fontWeight,10) >= 700;
    const need = (px >= 24 || (px >= 18.66 && bold)) ? 3 : 4.5;
    const got = ratio(eff, bg);
    if (got < need) out.push({px: Math.round(px), got: +got.toFixed(2), need,
                              text: (el.textContent||'').trim().slice(0,44)});
  });
  return out; }"""

# The drawing scales with its container, so a label's rendered size is its
# authored size times that scale — which is the number that has to hold up.
LABELS = """() => {
  const svg = document.querySelector('.map svg');
  if (!svg || !svg.getClientRects().length) return null;
  const box = svg.viewBox.baseVal, scale = svg.getBoundingClientRect().width / box.width;
  let smallest = Infinity;
  svg.querySelectorAll('text').forEach(t => {
    smallest = Math.min(smallest, parseFloat(getComputedStyle(t).fontSize) * scale); });
  return {scale: +scale.toFixed(3), smallest: +smallest.toFixed(2)}; }"""


def main(paths: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    failures = 0
    with sync_playwright() as engine:
        browser = engine.chromium.launch()
        for path in paths:
            url = path if "://" in path else f"file://{path}"
            for scheme in ("light", "dark"):
                for width in WIDTHS:
                    page = browser.new_page(viewport={"width": width, "height": 900},
                                            color_scheme=scheme)
                    page.goto(url, wait_until="networkidle")
                    page.wait_for_timeout(220)
                    page.evaluate("()=>document.querySelectorAll('details').forEach(d=>d.open=true)")
                    page.wait_for_timeout(120)
                    where = f"{path.rsplit('/', 1)[-1]} {scheme} {width}px"

                    size = page.evaluate(
                        "()=>({sw:document.documentElement.scrollWidth,"
                        "cw:document.documentElement.clientWidth})")
                    if size["sw"] > size["cw"]:
                        print(f"FAIL {where}: scrolls sideways {size}")
                        failures += 1

                    for bad in page.evaluate(CONTRAST):
                        print(f"FAIL {where}: {bad['got']}:1 needs {bad['need']} "
                              f"at {bad['px']}px — {bad['text']!r}")
                        failures += 1

                    labels = page.evaluate(LABELS)
                    if labels and labels["smallest"] < MIN_LABEL_PX:
                        print(f"FAIL {where}: drawing shown at {labels['scale']}, "
                              f"smallest label {labels['smallest']}px "
                              f"(hide it below {MIN_LABEL_PX}px)")
                        failures += 1
                    page.close()
        browser.close()
    print(f"\n{failures} failures" if failures else "\nall browser layout checks pass")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else print(__doc__) or 2)
