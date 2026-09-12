"""Xuất PNG/PDF từ các SVG và kiểm chữ đè nhau — dùng Chrome/Edge headless có sẵn.

    python docs/architecture/build_diagrams.py
    python docs/architecture/render.py

Kiểm: (1) chữ nằm ngoài khung; (2) hai nhãn chữ đè lên nhau. Có lỗi thì exit 1.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
BROWSER = next((b for b in BROWSERS if Path(b).exists()), None)
if not BROWSER:
    sys.exit("Không tìm thấy Chrome/Edge")


def run(*args):
    subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--hide-scrollbars", *args],
                   check=True, capture_output=True, timeout=120)


CHECK_JS = r"""
const bad = [];
document.querySelectorAll('svg').forEach(svg => {
  const W = svg.viewBox.baseVal.width, H = svg.viewBox.baseVal.height;
  const name = svg.dataset.name;
  const boxes = [...svg.querySelectorAll('text')].map(t => ({t: t.textContent, b: t.getBBox()}));
  boxes.forEach(({t, b}) => {
    if (b.x < 0 || b.y < 0 || b.x + b.width > W || b.y + b.height > H) bad.push(`${name}: ngoài khung: ${t}`);
  });
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].b, c = boxes[j].b;
    const ox = Math.min(a.x + a.width, c.x + c.width) - Math.max(a.x, c.x);
    const oy = Math.min(a.y + a.height, c.y + c.height) - Math.max(a.y, c.y);
    if (ox > 2 && oy > 3) bad.push(`${name}: đè nhau: "${boxes[i].t}" × "${boxes[j].t}"`);
  }
});
document.getElementById('out').textContent = JSON.stringify(bad);
"""


def check(svgs):
    body = "".join(p.read_text(encoding="utf-8").replace("<svg ", f'<svg data-name="{p.stem}" ', 1) for p in svgs)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(f'<meta charset="utf-8"><body>{body}<pre id="out">PENDING</pre><script>{CHECK_JS}</script>')
    res = subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--virtual-time-budget=5000",
                          "--dump-dom", Path(f.name).as_uri()], capture_output=True, timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', res.stdout.decode("utf-8", "replace"), re.S)
    if not m or m.group(1) == "PENDING":
        sys.exit("Không đọc được kết quả kiểm")
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))


def main():
    svgs = sorted(OUT.glob("0*.svg"))
    for p in svgs:
        w, h = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', p.read_text(encoding="utf-8")).groups())
        png = p.with_suffix(".png")
        run(f"--screenshot={png}", f"--window-size={int(w)},{int(h)}", "--force-device-scale-factor=1", p.as_uri())
        print(f"{p.stem}: {int(w)}x{int(h)} → {png.name}")
    index = OUT / "index.html"
    run(f"--screenshot={OUT / 'preview.png'}", "--window-size=1500,1000", index.as_uri())
    run(f"--print-to-pdf={OUT / 'Your-Eyes-Architecture.pdf'}", "--no-pdf-header-footer", index.as_uri())
    print("preview.png + Your-Eyes-Architecture.pdf")
    bad = check(svgs)
    for b in bad:
        print("  ✗", b)
    print(f"Kiểm chữ: {len(bad)} lỗi trên {len(svgs)} hình")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
