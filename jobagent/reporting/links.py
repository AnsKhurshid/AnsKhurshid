"""A small local HTML page of LinkedIn search links to open manually."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from jobagent.config import Settings
from jobagent.utils.files import atomic_write_text


def write_links_page(settings: Settings, links: list[dict]) -> Path:
    rows = "\n".join(
        f"<tr><td>{html.escape(l['title'])}</td><td>{html.escape(l['location'])}</td>"
        f"<td>{html.escape(l['work_arrangement'])}</td><td><a href=\"{html.escape(l['url'])}\" target=\"_blank\" "
        f"rel=\"noopener\">open search</a></td></tr>" for l in links)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>LinkedIn search links</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;max-width:1000px}}td,th{{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}}</style>
</head><body><h1>LinkedIn job searches</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M}. Open each search in your own browser. For interesting jobs, save the job page
(Ctrl+S) or copy the description into a text file in <code>{html.escape(str(settings.path(settings.sources.linkedin.inbox_dir)))}</code>,
or list job URLs in a .txt file there. Then run <code>python -m jobagent run</code>.</p>
<p><b>Note:</b> this tool does not access LinkedIn automatically, so it only knows about jobs you import.</p>
<table><tr><th>Title</th><th>Location</th><th>Arrangement</th><th></th></tr>{rows}</table></body></html>"""
    out = settings.path(settings.reporting.output_dir) / "linkedin_search_links.html"
    atomic_write_text(out, page)
    return out
