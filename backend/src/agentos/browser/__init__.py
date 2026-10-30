"""W4 Browser module — managed browser automation on raw CDP.

Decisions locked by the spike (scripts/spike_browser/RESULTS.md):
- raw DevTools Protocol over websockets — no framework client;
- observation = interactive/landmark AX projection, 80-element cap,
  omission marker, delta-by-line post-action observations;
- browser process tree ~1 GB RSS — idle shutdown + concurrency caps are
  mandatory, not optional;
- element refs are backendDOMNodeId-scoped and die with page state.
"""
