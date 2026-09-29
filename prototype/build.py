"""Bundle a dependency-free, offline design prototype. Does not start services."""
from pathlib import Path

root = Path(__file__).resolve().parent
shell = (root / "shell.html").read_text()
html = shell.replace("/*STYLE*/", (root / "app.css").read_text()).replace(
    "/*SCRIPT*/", (root / "app.js").read_text()
)
(root / "index.html").write_text(html)
print(f"Prototype bundled: {root / 'index.html'}")
