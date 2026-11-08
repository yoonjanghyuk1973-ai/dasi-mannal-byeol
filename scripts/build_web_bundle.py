"""Pack the one web page shared by Render and the Toss web bundle."""
import pathlib, sys, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
HTML = ROOT / 'static' / 'index.html'
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'dist' / 'web-bundle.zip')
OUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    z.write(HTML, 'index.html')
print(OUT)
