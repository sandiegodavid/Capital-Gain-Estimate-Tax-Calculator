"""Loading-page renderer for the asynchronous dashboard request."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from ..dashboard_selection import DashboardSelection


def render_loading_dashboard(selection: DashboardSelection) -> str:
    """Render immediately while the browser requests the potentially slow data view."""
    query_values: dict[str, str | int | Path] = {
        "source": selection.source_dir,
        "output": selection.output_dir,
    }
    if selection.year is not None:
        query_values["year"] = selection.year
    query_items = list(query_values.items())
    if selection.included_source_files is not None:
        query_items.append(("source_selection", "1"))
        query_items.extend(("included_source", source_file) for source_file in selection.included_source_files)
    data_url = f"/dashboard?{urlencode(query_items)}"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Loading · Capital Gain Estimate Tax Calculator</title><style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#f4f7fa; color:#102a43; font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif }}
    main {{ max-width:520px; margin:24px; padding:32px; text-align:center; background:white; border:1px solid #d9e2ec; border-radius:12px; box-shadow:0 1px 2px #102a4310 }}
    .spinner {{ width:32px; height:32px; margin:0 auto 18px; border:4px solid #d9e2ec; border-top-color:#1f5f8b; border-radius:50%; animation:spin .8s linear infinite }} @keyframes spin {{ to {{ transform:rotate(360deg) }} }} h1 {{ margin:0; font-size:24px }} p {{ color:#627d98 }}
    </style></head><body><main><div class="spinner" aria-hidden="true"></div><h1>Loading your investment data</h1><p>Reading the selected brokerage exports and calculating your dashboard. This can take a moment for larger files.</p></main><script>fetch("{data_url}").then(response => response.text()).then(page => {{ document.open(); document.write(page); document.close(); }}).catch(() => {{ document.querySelector("p").textContent = "We couldn’t load the data. Check the source folder and refresh this page."; }});</script></body></html>'''
