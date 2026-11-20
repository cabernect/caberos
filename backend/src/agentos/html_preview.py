"""Static HTML preview: preserve inline design without executing a web app."""

from bs4 import BeautifulSoup

_TAGS = set(
    "html head body title style main header footer nav section article aside "
    "div span p h1 h2 h3 h4 h5 h6 br hr pre code blockquote "
    "ul ol li dl dt dd table caption colgroup col thead tbody tfoot tr th td "
    "figure figcaption img picture a b strong i em u s small sub sup mark "
    "abbr time details summary address kbd samp var wbr".split()
)
_DROP_CONTENT = {
    "script",
    "iframe",
    "frame",
    "frameset",
    "object",
    "embed",
    "template",
    "noscript",
    "svg",
    "math",
}
_ATTRS = {
    "class",
    "id",
    "style",
    "title",
    "lang",
    "dir",
    "role",
    "alt",
    "width",
    "height",
    "colspan",
    "rowspan",
    "scope",
    "start",
    "reversed",
    "open",
    "datetime",
}
STATIC_HTML_CSP = (
    "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'"
)


def static_html_document(source: str) -> str:
    """Defense in depth: strip navigation/active markup, then pin a first CSP.

    The consumer MUST also use an empty iframe sandbox (no scripts, same-origin,
    forms, popups or top navigation). CSS network loads are blocked by CSP.
    """
    soup = BeautifulSoup(source, "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.parent is None:
            continue
        if tag.name in _DROP_CONTENT:
            tag.decompose()
        elif tag.name not in _TAGS:
            tag.unwrap()
        else:
            for attr in list(tag.attrs):
                if attr == "src" and tag.name == "img":
                    value = str(tag[attr]).strip().lower()
                    if not value.startswith(
                        (
                            "data:image/png;base64,",
                            "data:image/jpeg;base64,",
                            "data:image/gif;base64,",
                            "data:image/webp;base64,",
                        )
                    ):
                        del tag[attr]
                elif attr not in _ATTRS and not attr.startswith("aria-"):
                    del tag[attr]
    # Rebuild the head so a supplied meta refresh/base/CSP can never precede ours.
    styles = "".join(str(tag.extract()) for tag in soup.find_all("style"))
    body = soup.body
    content = str(body) if body else f"<body>{soup}</body>"
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{STATIC_HTML_CSP}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{styles}</head>{content}</html>"
    )
