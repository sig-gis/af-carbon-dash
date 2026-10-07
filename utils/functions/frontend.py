"""Frontend resilience helpers injected into the Streamlit page.

Streamlit's own frontend is a Vite build served as hashed JS chunks under
``/static/js/index.<hash>.js``. When the app scales to zero on Cloud Run, a
chunk fetch triggered by a rerun (e.g. selecting an FVS variant) can land on a
cold-starting or just-reaped instance and drop mid-flight. The browser then
raises ``TypeError: error loading dynamically imported module`` and the page is
stuck until a manual refresh.

Vite dispatches a ``vite:preloadError`` event on ``window`` whenever a
dynamically imported chunk fails to load. The Vite-recommended handling is to
reload once on that event, turning the transient failure into an invisible
refresh. We inject a listener via a same-origin ``components.html`` iframe so it
can reach the top window where Streamlit's Vite app runs.
"""

import streamlit as st
import streamlit.components.v1 as components

# JS runs inside a same-origin srcdoc iframe; ``window.parent`` is the top
# window hosting Streamlit's Vite bundle. A time-based guard prevents reload
# loops while still allowing recovery from a later, unrelated chunk failure.
_RELOAD_ON_PRELOAD_ERROR = """
<style>
html, body, iframe {
  width: 0 !important;
  height: 0 !important;
  min-width: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
}
</style>
<script>
(function () {
  var w = window.parent || window;
  if (w.__afPreloadReloadHooked) return;  // attach once per top window
  w.__afPreloadReloadHooked = true;

  // Streamlit wraps components in normal block layout even when the iframe is
  // height=0. Collapse this component's iframe and its nearby wrappers so the
  // recovery hook does not create a blank row above the page content.
  try {
    var frame = window.frameElement;
    var node = frame;
    for (var i = 0; node && i < 3; i += 1) {
      var style = node.style;
      if (style) {
        if (i === 0) {
          style.setProperty("display", "block", "important");
        }
        style.setProperty("height", "0", "important");
        style.setProperty("min-height", "0", "important");
        style.setProperty("margin", "0", "important");
        style.setProperty("padding", "0", "important");
        style.setProperty("overflow", "hidden", "important");
      }
      node = node.parentElement;
    }
  } catch (_) {}

  w.addEventListener("vite:preloadError", function (event) {
    try { event.preventDefault(); } catch (_) {}  // suppress Vite's rethrow
    var KEY = "__afViteReloadedAt";
    var now = Date.now();
    var last = parseInt(w.sessionStorage.getItem(KEY) || "0", 10);
    if (!last || now - last > 10000) {  // at most one reload per 10s
      w.sessionStorage.setItem(KEY, String(now));
      w.location.reload();
    }
  });
})();
</script>
"""


def inject_chunk_reload() -> None:
    """Auto-recover from failed dynamic chunk imports (Cloud Run cold starts).

    Call once per run, before the page renders. The helper renders a component
    iframe, then hides its Streamlit wrapper so it is visually/layout inert.
    """
    components.html(_RELOAD_ON_PRELOAD_ERROR, height=0, width=0)
