"""Inject the Streamlit/Vite preload-error recovery hook at build time.

The dashboard previously installed this hook with ``components.html`` from
``carbon_dash.py``. That preserves recovery from stale JS chunks on Cloud Run,
but it also creates a Streamlit component block at the top of every page. Even
with height=0, Streamlit can reserve visible whitespace.

This script patches Streamlit's installed frontend shell instead. It is intended
to run during the dashboard Docker build, after dependencies are installed. The
hook then runs in the top window without adding any Streamlit layout element.
"""

from __future__ import annotations

from pathlib import Path

import streamlit


MARKER = "AF_PRELOAD_RELOAD_HOOK"

HOOK = f"""<!-- {MARKER}: start -->
<script>
(function () {{
  if (window.__afPreloadReloadHooked) return;
  window.__afPreloadReloadHooked = true;

  window.addEventListener("vite:preloadError", function (event) {{
    try {{ event.preventDefault(); }} catch (_) {{}}
    var KEY = "__afViteReloadedAt";
    var now = Date.now();
    var last = parseInt(window.sessionStorage.getItem(KEY) || "0", 10);
    if (!last || now - last > 10000) {{
      window.sessionStorage.setItem(KEY, String(now));
      window.location.reload();
    }}
  }});
}})();
</script>
<!-- {MARKER}: end -->"""


def _candidate_index_files() -> list[Path]:
    """Return candidate Streamlit frontend shell files to patch."""
    package_root = Path(streamlit.__file__).resolve().parent
    static_root = package_root / "static"
    if not static_root.exists():
        raise FileNotFoundError(f"Streamlit static directory not found: {static_root}")

    return sorted(static_root.rglob("index.html"))


def _looks_like_streamlit_shell(html: str) -> bool:
    """Heuristic guard so we only patch Streamlit's app shell."""
    lowered = html.lower()
    return "</head>" in lowered and ("streamlit" in lowered or "vite" in lowered)


def patch_index(path: Path) -> bool:
    """Patch one index.html file. Return True when the file was modified."""
    html = path.read_text(encoding="utf-8")

    if MARKER in html:
        print(f"Preload hook already present: {path}")
        return False

    if not _looks_like_streamlit_shell(html):
        print(f"Skipping non-Streamlit-looking index.html: {path}")
        return False

    lower_html = html.lower()
    insert_at = lower_html.rfind("</head>")
    if insert_at == -1:
        raise ValueError(f"Could not find </head> in {path}")

    patched = html[:insert_at] + "\n" + HOOK + "\n" + html[insert_at:]
    path.write_text(patched, encoding="utf-8")
    print(f"Injected preload hook into: {path}")
    return True


def main() -> None:
    candidates = _candidate_index_files()
    if not candidates:
        raise FileNotFoundError("No Streamlit index.html files found to patch")

    modified = [path for path in candidates if patch_index(path)]
    already_patched = []
    for path in candidates:
        if MARKER in path.read_text(encoding="utf-8"):
            already_patched.append(path)

    if not modified and not already_patched:
        raise RuntimeError(
            "Found Streamlit index.html files, but none were patched. "
            "Streamlit's frontend layout may have changed."
        )


if __name__ == "__main__":
    main()