"""HTML deck handler — structured spec → one self-contained .html file.

Authoring contract (W2H/D4): the deliverable is a single portable HTML
file — inline CSS/JS, no external requests. Deck-authored HTML fragments
are sanitized to a whitelist; the only script that ships is the
platform-owned navigation runtime (deck-rt1). Arbitrary deck JS is NOT
admitted in v1 — blocks or sanitized markup only.

Playback/isolation is a separate slice: this file is safe to store,
download, and serve as a static source view; executing it inside the
app requires the admitted isolated player (W2H slices 3–4).
"""

import base64
import hashlib
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path

RUNTIME_VERSION = "deck-rt3"
_SPEC_VERSION = 1
_MARKER = "<!-- caberos-deck:v1 -->"
MAX_SLIDES = 100
_MAX_SPEC_CHARS = 200_000

# Tags whose entire contents are dropped (never rendered, never kept as text).
_DROP_CONTENTS = {"script", "style", "iframe", "object", "embed", "template", "noscript"}
# Tags dropped but inner text preserved.
_DROP_TAG = {
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "option",
    "svg",
    "math",
    "video",
    "audio",
    "source",
    "track",
    "canvas",
    "link",
    "meta",
    "base",
    "title",
    "head",
    "html",
    "body",
}
_ALLOWED = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "details",
    "dfn",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "q",
    "rp",
    "rt",
    "ruby",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "time",
    "tr",
    "u",
    "ul",
    "var",
    "wbr",
}
_VOID = {"br", "hr", "img", "col", "wbr"}
_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
_RASTER_DATA = re.compile(r"^data:image/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=\s]+$", re.I)
# Workspace-relative asset path — no scheme, no leading slash, no traversal
# chars beyond plain segments (resolve_within does the real containment check).
_RELATIVE_SRC = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
_ASSET_MARKER = re.compile(r'src="deck-asset:([^"]+)"')
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_MAX_ASSET_TOTAL = 25 * 1024 * 1024
_MAX_ASSETS = 20
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
}
_SAFE_URL = re.compile(r"^(https?://|mailto:|#)", re.I)


class _Sanitizer(HTMLParser):
    """Whitelist HTML fragment sanitizer — emits clean markup only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._drop = 0  # >0 while inside a dropped-contents element

    def _ok_url(self, value: str) -> bool:
        v = value.strip().lower()
        return bool(_SAFE_URL.match(v)) and "javascript:" not in v and "vbscript:" not in v

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_CONTENTS:
            self._drop += 1
            return
        if self._drop:
            return
        if tag in _DROP_TAG or tag not in _ALLOWED:
            return  # tag dropped, inner text still flows through
        keep: list[tuple[str, str]] = []
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name in {
                "style",
                "id",
                "srcset",
                "ping",
                "formaction",
                "target",
            }:
                continue
            value = value or ""
            if name == "href" and tag == "a":
                if self._ok_url(value):
                    keep.append((name, escape(value, quote=True)))
            elif name == "src" and tag == "img":
                v = value.strip()
                if _RASTER_DATA.match(v):
                    keep.append((name, escape(v, quote=True)))
                elif _RELATIVE_SRC.match(v):
                    # Workspace-relative asset — resolved+embedded at build.
                    keep.append((name, escape(f"deck-asset:{v}", quote=True)))
            elif name in {
                "class",
                "alt",
                "title",
                "colspan",
                "rowspan",
                "start",
                "reversed",
                "open",
                "datetime",
                "cite",
                "type",
                "value",
            }:
                keep.append((name, escape(value, quote=True)))
        attr = "".join(f' {n}="{v}"' for n, v in keep)
        if tag in _VOID:
            self.out.append(f"<{tag}{attr}>")
        else:
            self.out.append(f"<{tag}{attr}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_CONTENTS | _DROP_TAG or tag not in _ALLOWED:
            return
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_CONTENTS:
            self._drop = max(0, self._drop - 1)
            return
        if self._drop or tag in _DROP_TAG or tag not in _ALLOWED or tag in _VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._drop:
            self.out.append(escape(data))

    def handle_entityref(self, name):
        if not self._drop:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self._drop:
            self.out.append(f"&#{name};")


def sanitize_fragment(html: str) -> str:
    s = _Sanitizer()
    s.feed(html)
    s.close()
    return "".join(s.out).strip()


def _hex(value: str, field: str) -> str:
    v = value.strip()
    if not _HEX.match(v):
        raise ValueError(f"theme.{field} must be RRGGBB hex, got {value!r}")
    return "#" + v.lstrip("#").lower()


_FONT_STACKS = {
    "sans": 'ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif',
    "serif": '"Iowan Old Style",Georgia,"Times New Roman",serif',
    "mono": 'ui-monospace,"SF Mono",Menlo,Consolas,monospace',
}
_SLIDE_LAYOUTS = {"content", "title"}


def _theme(spec: dict) -> dict[str, str]:
    theme = spec.get("theme") or {}
    if not isinstance(theme, dict):
        raise ValueError("theme must be an object")
    unknown = set(theme) - {"background", "accent", "text", "font"}
    if unknown:
        raise ValueError(f"unknown theme keys: {sorted(unknown)}")
    out: dict[str, str] = {}
    for k, v in theme.items():
        if not isinstance(v, str):
            continue
        if k == "font":
            if v not in _FONT_STACKS:
                raise ValueError(f"unknown theme font: {v!r} (sans|serif|mono)")
        else:
            v = _hex(v, k)
        out[k] = v
    return out


def _mime_of(data: bytes) -> str | None:
    for magic, mime in _MAGIC.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _load_asset(workspace_path, src: str) -> dict:
    """Workspace-relative image → embedded data URI + manifest entry.

    Containment via resolve_within (realpath — symlinks/.. can't escape);
    type by magic bytes, never extension; raster only (SVG is a script
    vector and fails the magic check anyway).
    """
    from ...sandbox.workspace import resolve_within

    target = resolve_within(workspace_path, src)
    if not target.is_file():
        raise ValueError(f"deck asset not found: {src}")
    raw = target.read_bytes()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(f"deck asset too large ({len(raw)} bytes): {src}")
    mime = _mime_of(raw)
    if mime is None:
        raise ValueError(f"deck asset is not a raster image (png/jpg/gif/webp): {src}")
    import base64 as _b64
    import hashlib as _hl

    return {
        "uri": f"data:{mime};base64,{_b64.b64encode(raw).decode()}",
        "mime": mime,
        "bytes": len(raw),
        "sha256": _hl.sha256(raw).hexdigest(),
    }


def _iter_asset_refs(spec: dict):
    """Yield every workspace-relative asset path the spec references.

    Fragment refs are collected from the SANITIZED html (the same output
    render emits markers into) so collection and rendering can never
    disagree about which src values survive.
    """
    for slide in spec["slides"]:
        if "html" in slide:
            clean = sanitize_fragment(str(slide["html"]))
            for m in _ASSET_MARKER.finditer(clean):
                yield m.group(1)
        for block in slide.get("blocks") or []:
            if block.get("type") == "image":
                src = str(block.get("src", "")).strip()
                if src and not _RASTER_DATA.match(src):
                    yield src


def _resolve_assets(spec: dict, workspace_path) -> dict[str, dict]:
    """Load every referenced asset once; enforce count/size budgets."""
    refs = list(dict.fromkeys(_iter_asset_refs(spec)))
    if len(refs) > _MAX_ASSETS:
        raise ValueError(f"deck references {len(refs)} assets (limit {_MAX_ASSETS})")
    out: dict[str, dict] = {}
    total = 0
    for src in refs:
        entry = _load_asset(workspace_path, src)
        total += entry["bytes"]
        if total > _MAX_ASSET_TOTAL:
            raise ValueError(f"deck assets exceed {_MAX_ASSET_TOTAL} bytes total")
        out[src] = entry
    return out


def _slide_html(slide: dict, assets: dict[str, dict]) -> str:
    """Render one slide spec to section inner HTML."""
    parts: list[str] = []
    if title := slide.get("title"):
        parts.append(f'<h2 class="slide-title">{escape(str(title))}</h2>')
    has_html = "html" in slide
    has_blocks = "blocks" in slide
    if has_html and has_blocks:
        raise ValueError("slide accepts either 'html' or 'blocks', not both")
    if has_html:
        clean = sanitize_fragment(str(slide["html"]))
        if not clean:
            raise ValueError("slide html sanitized to nothing — script/style/foreign tags stripped")

        def _asset_repl(m: re.Match) -> str:
            src = m.group(1)
            if src not in assets:
                raise ValueError(f"deck asset was not resolved: {src}")
            return f'src="{assets[src]["uri"]}"'

        clean = _ASSET_MARKER.sub(_asset_repl, clean)
        if "deck-asset:" in clean:
            raise ValueError("unresolved deck asset marker in slide html")
        parts.append(f'<div class="slide-body">{clean}</div>')
    elif has_blocks:
        parts.append('<div class="slide-body">' + _blocks_html(slide["blocks"], assets) + "</div>")
    elif not slide.get("title"):
        # Title-only slides are legal (covers, section dividers).
        raise ValueError("slide needs 'title', 'html' or 'blocks'")
    if notes := slide.get("notes"):
        parts.append(f'<aside class="deck-notes" hidden>{escape(str(notes))}</aside>')
    return "".join(parts)


def _blocks_html(blocks: list, assets: dict[str, dict]) -> str:
    """Blocks → wrapped .blk divs; reveal:true marks a stepwise-reveal block."""
    out: list[str] = []
    for block in blocks:
        kind = block.get("type")
        inner: str | None = None
        if kind == "heading":
            level = min(6, max(1, int(block.get("level", 2))))
            inner = f"<h{level}>{escape(str(block.get('text', '')))}</h{level}>"
        elif kind == "paragraph":
            inner = f"<p>{escape(str(block.get('text', '')))}</p>"
        elif kind == "bullets":
            items = block.get("items") or []
            if not isinstance(items, list):
                raise ValueError("bullets block needs items[]")
            inner = "<ul>" + "".join(f"<li>{escape(str(i))}</li>" for i in items) + "</ul>"
        elif kind == "table":
            rows = block.get("rows") or []
            if not isinstance(rows, list) or any(not isinstance(r, list) for r in rows):
                raise ValueError("table block needs rows[][]")
            if rows:
                header = "".join(f"<th>{escape(str(c))}</th>" for c in rows[0])
                body = "".join(
                    "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>"
                    for row in rows[1:]
                )
                inner = f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"
            else:
                inner = ""
        elif kind == "image":
            src = str(block.get("src", "")).strip()
            if not src:
                raise ValueError("image block needs src")
            if _RASTER_DATA.match(src):
                uri = src
            elif src in assets:
                uri = assets[src]["uri"]
            else:
                raise ValueError(f"image block asset not resolved: {src}")
            alt = escape(str(block.get("alt", "")), quote=True)
            inner = f'<img src="{uri}" alt="{alt}">'
        elif kind == "divider":
            inner = "<hr>"
        else:
            raise ValueError(f"unknown deck block: {kind}")
        cls = "blk rv" if block.get("reveal") else "blk"
        out.append(f'<div class="{cls}">{inner}</div>')
    return "".join(out)


def _norm_spec(spec: dict) -> dict:
    """Validate + normalize the deck spec; returns the canonical spec."""
    if not isinstance(spec, dict):
        raise ValueError("deck spec must be an object")
    version = spec.get("version", _SPEC_VERSION)
    if version != _SPEC_VERSION:
        raise ValueError(f"unsupported deck spec version: {version!r} (supported: {_SPEC_VERSION})")
    if len(json.dumps(spec, default=str)) > _MAX_SPEC_CHARS:
        raise ValueError("deck spec exceeds size limit")
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("deck spec needs a non-empty slides[]")
    if len(slides) > MAX_SLIDES:
        raise ValueError(f"deck exceeds {MAX_SLIDES} slides")
    norm_slides = []
    seen_ids: set[str] = set()
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError(f"slide {i} must be an object")
        sid = str(slide.get("id") or f"s{i + 1}")
        if sid in seen_ids:
            raise ValueError(f"duplicate slide id: {sid}")
        layout = slide.get("layout", "content")
        if layout not in _SLIDE_LAYOUTS:
            raise ValueError(f"slide {i} unknown layout: {layout!r}")
        seen_ids.add(sid)
        norm_slides.append({**slide, "id": sid})
    return {
        "version": _SPEC_VERSION,
        "title": str(spec.get("title") or "Untitled deck"),
        "theme": _theme(spec),
        "slides": norm_slides,
    }


_CSS = """
:root{--deck-bg:#ffffff;--deck-accent:#3f6212;--deck-text:#1c1917;--deck-muted:#78716c;
  --deck-font:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0;height:100%;background:var(--deck-bg);color:var(--deck-text);
  font-family:var(--deck-font);-webkit-font-smoothing:antialiased}
#deck{height:100%;display:flex;align-items:center;justify-content:center}
#deck-progress{position:fixed;top:0;left:0;right:0;height:3px;z-index:6}
#deck-progress i{display:block;height:100%;width:0;background:var(--deck-accent)}
/* Slides are a true 16:9 canvas letterboxed inside the player — like a
   PowerPoint slide, not a stretched page. container-type:inline-size makes
   cqw units inside resolve against the SLIDE width, so text/padding scale
   with the slide regardless of panel shape. */
.slide{display:none;position:relative;overflow:auto;
  height:min(100%,calc(100vw*9/16));aspect-ratio:16/9;
  container-type:inline-size;
  padding:calc(7%*var(--dfs,1)) calc(8%*var(--dfs,1)) calc(11%*var(--dfs,1));
  background:var(--deck-bg);color:var(--deck-text);
  box-shadow:0 0 0 1px color-mix(in srgb,var(--deck-muted) 22%,transparent),
    0 16px 50px rgba(0,0,0,.10);
  scrollbar-width:thin;scrollbar-color:var(--deck-muted) transparent}
.slide::-webkit-scrollbar{width:8px}
.slide::-webkit-scrollbar-thumb{background:var(--deck-muted);border-radius:4px}
.slide.active{display:flex;flex-direction:column}
/* --dfs is the runtime's shrink-to-fit scale (deck-rt3+): every scalable
   size below multiplies by it so dense slides fit the 16:9 canvas instead
   of scrolling. Sparse slides center vertically via auto margins (they
   collapse to 0 the moment content needs the room). */
.slide-title{font-size:calc(clamp(1.9rem,5cqw,3.6rem)*var(--dfs,1));
  line-height:1.15;margin:0 0 .45em;
  color:var(--deck-text);font-weight:700;letter-spacing:-.01em}
.slide-title::after{content:"";display:block;width:calc(4.4cqw*var(--dfs,1));
  height:max(3px,calc(.35cqw*var(--dfs,1)));margin-top:.4em;
  background:var(--deck-accent);border-radius:2px}
.slide-body{font-size:calc(clamp(.95rem,2.05cqw,1.35rem)*var(--dfs,1));
  line-height:1.6;max-width:64ch;margin-inline:auto}
.slide.active:not(.layout-title)>.slide-body{margin-block:auto}
.slide-body p{margin:0 0 .8em}
.slide-body h1,.slide-body h2,.slide-body h3,.slide-body h4{color:var(--deck-accent);
  margin:1em 0 .4em;line-height:1.25}
.slide-body h1{font-size:1.5em}.slide-body h2{font-size:1.32em}
.slide-body h3{font-size:1.15em}.slide-body h4{font-size:1em}
.slide-body ul,.slide-body ol{margin:.2em 0 .9em;padding-left:1.35em}
.slide-body li{margin:.35em 0}
.slide-body li::marker{color:var(--deck-accent)}
.slide-body table{border-collapse:collapse;margin:.4em 0 1em;font-size:.92em}
.slide-body th{background:color-mix(in srgb,var(--deck-accent) 12%,var(--deck-bg));
  font-weight:600}
.slide-body th,.slide-body td{border:1px solid color-mix(in srgb,var(--deck-muted) 40%,transparent);
  padding:.5em .8em;text-align:left;vertical-align:top}
.slide-body tbody tr:nth-child(even) td{
  background:color-mix(in srgb,var(--deck-muted) 6%,transparent)}
.slide-body img{display:block;max-width:100%;
  max-height:calc(36cqw*var(--dfs,1));height:auto;
  border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.10)}
.slide-body hr{border:0;height:3px;width:calc(5.5cqw*var(--dfs,1));
  background:var(--deck-accent);margin:1.4em 0;border-radius:2px}
.slide-body a{color:var(--deck-accent)}
.blk{margin:0 0 1em}
.blk:last-child{margin-bottom:0}
.blk.rv{opacity:0;transform:translateY(12px)}
.blk.rv.on{opacity:1;transform:none}
.slide.layout-title{align-items:center;justify-content:center;text-align:center}
.slide.layout-title .slide-title{font-size:calc(clamp(2.4rem,6.5cqw,4.6rem)*var(--dfs,1))}
.slide.layout-title .slide-title::after{margin:.45em auto 0}
.slide.layout-title .slide-body{margin-top:1.4em;color:var(--deck-muted);
  font-size:calc(1.18rem*var(--dfs,1))}
.slide-foot{position:absolute;left:8%;right:8%;bottom:3.5%;display:flex;
  justify-content:space-between;font:11px/1 ui-monospace,monospace;
  letter-spacing:.05em;text-transform:uppercase;color:var(--deck-muted)}
.deck-notes{display:none}
#deck-pos{position:fixed;right:14px;bottom:64px;font:12px/1 ui-monospace,monospace;
  color:var(--deck-muted);background:color-mix(in srgb,var(--deck-bg) 80%,transparent);
  padding:4px 8px;border-radius:6px;pointer-events:none;z-index:6}
#deck-nav{position:fixed;left:0;right:0;bottom:0;display:flex;justify-content:space-between;
  padding:14px 18px 12px;pointer-events:none;z-index:7;
  background:linear-gradient(transparent,color-mix(in srgb,var(--deck-bg) 88%,transparent) 45%)}
#deck-nav button{pointer-events:auto;
  border:1px solid color-mix(in srgb,var(--deck-muted) 45%,transparent);
  background:color-mix(in srgb,var(--deck-bg) 88%,transparent);color:var(--deck-text);
  border-radius:999px;padding:7px 16px;font:500 13px/1 var(--deck-font);cursor:pointer;
  backdrop-filter:blur(6px)}
#deck-nav button:hover:not(:disabled){border-color:var(--deck-accent);color:var(--deck-accent)}
#deck-nav button:disabled{opacity:.35;cursor:default}
#deck-notes-overlay{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);
  width:min(580px,92vw);background:var(--deck-text);color:var(--deck-bg);
  border-radius:12px;padding:14px 18px;font-size:14px;line-height:1.55;z-index:9;
  box-shadow:0 12px 40px rgba(0,0,0,.3)}
#deck-notes-overlay strong{display:block;font-size:10px;text-transform:uppercase;
  letter-spacing:.1em;opacity:.55;margin-bottom:5px;font-weight:600}
@media (prefers-reduced-motion:no-preference){
  #deck-progress i{transition:width .25s ease}
  .blk.rv{transition:opacity .28s ease,transform .28s ease}
  .slide.active{animation:deck-in .22s ease-out}
  @keyframes deck-in{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}
  #deck.dir-prev .slide.active{animation-name:deck-in-l}
  @keyframes deck-in-l{from{opacity:0;transform:translateX(-14px)}to{opacity:1;transform:none}}
}
"""

# deck-rt3 — rt2 plus shrink-to-fit: overflowing slides scale their type
# down (PowerPoint-style) instead of scrolling, sparse slides center
# vertically, and the fit re-runs on resize and every reveal step.
_RUNTIME_JS = """
(function(){
  var deck=document.getElementById('deck');
  var slides=[].slice.call(deck.querySelectorAll('.slide'));
  var pos=document.getElementById('deck-pos');
  var prog=document.querySelector('#deck-progress i');
  var prev=document.getElementById('deck-prev'),next=document.getElementById('deck-next');
  var notesOv=document.getElementById('deck-notes-overlay');
  var notesTxt=document.getElementById('deck-notes-text');
  var i=0;
  function rvs(){return slides[i].querySelectorAll('.rv')}
  function pending(){return slides[i].querySelectorAll('.rv:not(.on)').length}
  function revealed(){return slides[i].querySelectorAll('.rv.on').length}
  function hasNotes(){
    var n=slides[i].querySelector('.deck-notes');
    return !!(n&&n.textContent.trim());
  }
  // Shrink-to-fit: --dfs multiplies every scalable size in the slide CSS.
  // Iterate toward clientHeight>=scrollHeight, floor at 55% — beyond that
  // honest scrolling beats unreadable microtext.
  function fit(){
    var s=slides[i];if(!s)return;
    s.style.setProperty('--dfs','1');
    for(var g=0;g<10;g++){
      if(s.scrollHeight<=s.clientHeight+4)break;
      var cur=parseFloat(s.style.getPropertyValue('--dfs'))||1;
      var next=Math.max(0.55,cur*(s.clientHeight/s.scrollHeight)*0.94);
      if(next>=cur-0.002)break;
      s.style.setProperty('--dfs',next.toFixed(3));
    }
  }
  function post(){
    try{parent.postMessage({caberos:'deck',v:1,type:'state',index:i,count:slides.length,
      revealed:revealed(),pending:pending(),canPrev:i>0||revealed()>0,
      canNext:i<slides.length-1||pending()>0,notes:hasNotes()},'*')}catch(e){}
  }
  function sync(){
    fit();
    pos.textContent=(i+1)+' / '+slides.length;
    if(prog)prog.style.width=((i+1)/slides.length*100)+'%';
    prev.disabled=!(i>0||revealed()>0);
    next.disabled=!(i<slides.length-1||pending()>0);
    post();
  }
  function go(n,dir){
    i=Math.max(0,Math.min(slides.length-1,n));
    deck.className=dir<0?'dir-prev':'';
    slides.forEach(function(s,k){s.classList.toggle('active',k===i)});
    if(notesOv)notesOv.hidden=true;
    sync();
  }
  function stepNext(){
    var el=slides[i].querySelector('.rv:not(.on)');
    if(el){el.classList.add('on');sync();return}
    go(i+1,1);
  }
  function stepPrev(){
    var on=slides[i].querySelectorAll('.rv.on');
    if(on.length){on[on.length-1].classList.remove('on');sync();return}
    go(i-1,-1);
  }
  function setReveals(k){
    var els=rvs();
    for(var j=0;j<els.length;j++)els[j].classList.toggle('on',j<k);
  }
  function gotoSlide(n,reveal){
    go(n,0);
    if(typeof reveal==='number')setReveals(Math.max(0,Math.min(rvs().length,reveal|0)));
    sync();
  }
  function toggleNotes(){
    if(!notesOv)return;
    if(notesOv.hidden){
      var n=slides[i].querySelector('.deck-notes');
      notesTxt.textContent=n?n.textContent.trim():'';
      notesOv.hidden=false;
    }else notesOv.hidden=true;
  }
  // Embedded in the app player: platform chrome owns visible controls —
  // hide the deck's own nav/position (keyboard still works inside).
  var embedded=false;
  try{embedded=window.self!==window.top}catch(e){}
  if(embedded){
    var nn=document.getElementById('deck-nav');if(nn)nn.style.display='none';
    if(pos)pos.style.display='none';
  }
  prev.addEventListener('click',stepPrev);
  next.addEventListener('click',stepNext);
  document.addEventListener('keydown',function(e){
    if(e.target&&(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'))return;
    if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();stepNext()}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();stepPrev()}
    else if(e.key==='Home'){e.preventDefault();go(0,-1)}
    else if(e.key==='End'){e.preventDefault();go(slides.length-1,1)}
    else if(e.key==='n'||e.key==='N'){e.preventDefault();toggleNotes()}
  });
  // Trusted platform controls (the in-app player) drive navigation through
  // this narrow bridge — schema-checked messages only, no other authority.
  //   step {dir:±1}  → reveal pending blocks first, then change slide
  //   nav  {index}   → absolute jump, preserving the target's build state
  //   goto {index,reveal?} → absolute jump + exact reveal count (capture)
  window.addEventListener('message',function(e){
    var d=e.data;
    if(!d||d.caberos!=='deck'||d.v!==1)return;
    if(d.type==='step'&&(d.dir===1||d.dir===-1)){d.dir>0?stepNext():stepPrev();return}
    if(d.type==='nav'&&typeof d.index==='number'){go(d.index|0,0);return}
    if(d.type==='goto'&&typeof d.index==='number'){
      gotoSlide(d.index|0,d.reveal);return;
    }
  });
  var rszT=null;
  window.addEventListener('resize',function(){
    clearTimeout(rszT);rszT=setTimeout(fit,120);
  });
  go(0,0);
})();
"""

_RUNTIME_JS_V2 = """
(function(){
  var deck=document.getElementById('deck');
  var slides=[].slice.call(deck.querySelectorAll('.slide'));
  var pos=document.getElementById('deck-pos');
  var prog=document.querySelector('#deck-progress i');
  var prev=document.getElementById('deck-prev'),next=document.getElementById('deck-next');
  var notesOv=document.getElementById('deck-notes-overlay');
  var notesTxt=document.getElementById('deck-notes-text');
  var i=0;
  function rvs(){return slides[i].querySelectorAll('.rv')}
  function pending(){return slides[i].querySelectorAll('.rv:not(.on)').length}
  function revealed(){return slides[i].querySelectorAll('.rv.on').length}
  function hasNotes(){
    var n=slides[i].querySelector('.deck-notes');
    return !!(n&&n.textContent.trim());
  }
  function post(){
    try{parent.postMessage({caberos:'deck',v:1,type:'state',index:i,count:slides.length,
      revealed:revealed(),pending:pending(),canPrev:i>0||revealed()>0,
      canNext:i<slides.length-1||pending()>0,notes:hasNotes()},'*')}catch(e){}
  }
  function sync(){
    pos.textContent=(i+1)+' / '+slides.length;
    if(prog)prog.style.width=((i+1)/slides.length*100)+'%';
    prev.disabled=!(i>0||revealed()>0);
    next.disabled=!(i<slides.length-1||pending()>0);
    post();
  }
  function go(n,dir){
    i=Math.max(0,Math.min(slides.length-1,n));
    deck.className=dir<0?'dir-prev':'';
    slides.forEach(function(s,k){s.classList.toggle('active',k===i)});
    if(notesOv)notesOv.hidden=true;
    sync();
  }
  function stepNext(){
    var el=slides[i].querySelector('.rv:not(.on)');
    if(el){el.classList.add('on');sync();return}
    go(i+1,1);
  }
  function stepPrev(){
    var on=slides[i].querySelectorAll('.rv.on');
    if(on.length){on[on.length-1].classList.remove('on');sync();return}
    go(i-1,-1);
  }
  function setReveals(k){
    var els=rvs();
    for(var j=0;j<els.length;j++)els[j].classList.toggle('on',j<k);
  }
  function gotoSlide(n,reveal){
    go(n,0);
    if(typeof reveal==='number')setReveals(Math.max(0,Math.min(rvs().length,reveal|0)));
    sync();
  }
  function toggleNotes(){
    if(!notesOv)return;
    if(notesOv.hidden){
      var n=slides[i].querySelector('.deck-notes');
      notesTxt.textContent=n?n.textContent.trim():'';
      notesOv.hidden=false;
    }else notesOv.hidden=true;
  }
  // Embedded in the app player: platform chrome owns visible controls —
  // hide the deck's own nav/position (keyboard still works inside).
  var embedded=false;
  try{embedded=window.self!==window.top}catch(e){}
  if(embedded){
    var nn=document.getElementById('deck-nav');if(nn)nn.style.display='none';
    if(pos)pos.style.display='none';
  }
  prev.addEventListener('click',stepPrev);
  next.addEventListener('click',stepNext);
  document.addEventListener('keydown',function(e){
    if(e.target&&(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'))return;
    if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();stepNext()}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();stepPrev()}
    else if(e.key==='Home'){e.preventDefault();go(0,-1)}
    else if(e.key==='End'){e.preventDefault();go(slides.length-1,1)}
    else if(e.key==='n'||e.key==='N'){e.preventDefault();toggleNotes()}
  });
  // Trusted platform controls (the in-app player) drive navigation through
  // this narrow bridge — schema-checked messages only, no other authority.
  //   step {dir:±1}  → reveal pending blocks first, then change slide
  //   nav  {index}   → absolute jump, preserving the target's build state
  //   goto {index,reveal?} → absolute jump + exact reveal count (capture)
  window.addEventListener('message',function(e){
    var d=e.data;
    if(!d||d.caberos!=='deck'||d.v!==1)return;
    if(d.type==='step'&&(d.dir===1||d.dir===-1)){d.dir>0?stepNext():stepPrev();return}
    if(d.type==='nav'&&typeof d.index==='number'){go(d.index|0,0);return}
    if(d.type==='goto'&&typeof d.index==='number'){
      gotoSlide(d.index|0,d.reveal);return;
    }
  });
  go(0,0);
})();
"""

# deck-rt1 — the original runtime, kept admissible so decks built before
# rt2 (reveals/layouts) keep playing in-app instead of degrading to source.
# Byte-exact: admission hash-pins each known runtime independently.
_RUNTIME_JS_V1 = """
(function(){
  var slides=[].slice.call(document.querySelectorAll('#deck > .slide'));
  var pos=document.getElementById('deck-pos');
  var prev=document.getElementById('deck-prev'),next=document.getElementById('deck-next');
  var i=0;
  function post(){
    try{parent.postMessage({caberos:'deck',v:1,type:'state',index:i,count:slides.length},'*')}catch(e){}
  }
  function show(n){
    i=Math.max(0,Math.min(slides.length-1,n));
    slides.forEach(function(s,k){s.classList.toggle('active',k===i)});
    pos.textContent=(i+1)+' / '+slides.length;
    prev.disabled=i===0;next.disabled=i===slides.length-1;
    post();
  }
  // Embedded in the app player: platform chrome owns visible controls —
  // hide the deck's own nav/position (keyboard still works inside).
  var embedded=false;
  try{embedded=window.self!==window.top}catch(e){}
  if(embedded){
    var nn=document.getElementById('deck-nav');if(nn)nn.style.display='none';
    if(pos)pos.style.display='none';
  }
  prev.addEventListener('click',function(){show(i-1)});
  next.addEventListener('click',function(){show(i+1)});
  document.addEventListener('keydown',function(e){
    if(e.target&&(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'))return;
    if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();show(i+1)}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();show(i-1)}
    else if(e.key==='Home'){e.preventDefault();show(0)}
    else if(e.key==='End'){e.preventDefault();show(slides.length-1)}
  });
  // Trusted platform controls (the in-app player) drive navigation through
  // this narrow bridge — schema-checked, index-only, no other authority.
  window.addEventListener('message',function(e){
    var d=e.data;
    if(d&&d.caberos==='deck'&&d.v===1&&d.type==='nav'&&typeof d.index==='number'){
      show(d.index|0);
    }
  });
  show(0);
})();
"""

# Every platform runtime a deck file may legitimately embed.
_KNOWN_RUNTIMES = (
    ("deck-rt3", _RUNTIME_JS),
    ("deck-rt2", _RUNTIME_JS_V2),
    ("deck-rt1", _RUNTIME_JS_V1),
)


def _render_full(spec: dict, assets: dict[str, dict]) -> str:
    """Canonical spec → one self-contained .html deck file."""
    theme = spec["theme"]
    overrides = []
    if theme.get("background"):
        overrides.append(f"--deck-bg:{theme['background']}")
    if theme.get("accent"):
        overrides.append(f"--deck-accent:{theme['accent']}")
    if theme.get("text"):
        overrides.append(f"--deck-text:{theme['text']}")
    theme_css = ";".join(overrides)
    if theme.get("font") in _FONT_STACKS:
        theme_css += f";--deck-font:{_FONT_STACKS[theme['font']]}"
    total = len(spec["slides"])
    sections = []
    for n, slide in enumerate(spec["slides"]):
        sid = escape(slide["id"], quote=True)
        layout = " layout-title" if slide.get("layout") == "title" else ""
        deck_title = escape(spec["title"])
        foot = (
            f'<footer class="slide-foot"><span>{deck_title}</span>'
            f"<span>{n + 1} / {total}</span></footer>"
        )
        sections.append(
            f'<section class="slide{layout}" data-slide-id="{sid}">'
            f"{_slide_html(slide, assets)}{foot}</section>"
        )
    # `<` → < so spec text can never terminate the script element early
    # (e.g. a note literally containing "</script>"). No HTML-escaping:
    # script is a raw-text element — entities would NOT be decoded and
    # would corrupt the JSON (an "&" would become "&amp;").
    spec_json = json.dumps(spec, ensure_ascii=False).replace("<", "\\u003c")
    return (
        "<!doctype html>\n"
        f"{_MARKER}\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(spec['title'])}</title>"
        f"<style>{_CSS}\n:root{{{theme_css}}}</style>"
        "</head><body>"
        f'<main id="deck" data-runtime="{RUNTIME_VERSION}">' + "".join(sections) + "</main>"
        '<div id="deck-progress"><i></i></div>'
        f'<script type="application/json" id="deck-spec">{spec_json}</script>'
        '<nav id="deck-nav" aria-label="Slide navigation">'
        '<button id="deck-prev" type="button">‹ Prev</button>'
        '<button id="deck-next" type="button">Next ›</button>'
        "</nav>"
        '<div id="deck-pos" aria-live="polite"></div>'
        '<div id="deck-notes-overlay" hidden><strong>Presenter notes</strong>'
        '<p id="deck-notes-text"></p></div>'
        f"<script>{_RUNTIME_JS}</script>"
        "</body></html>\n"
    )


def _extract_spec(data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace")
    m = re.search(r'<script type="application/json" id="deck-spec">(.*?)</script>', text, re.S)
    if not m:
        raise ValueError("not a CaberOS deck — missing embedded spec")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"deck spec JSON unreadable: {e}") from e


def _slide_index(spec: dict, ref) -> int:
    """Slide ref → index: int = position, str = slide id."""
    slides = spec["slides"]
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(slides):
            return ref
        raise ValueError(f"slide index out of range: {ref} (deck has {len(slides)})")
    sid = str(ref)
    for i, slide in enumerate(slides):
        if slide.get("id") == sid:
            return i
    raise ValueError(f"unknown slide id: {sid}")


def _finalize(spec: dict, workspace_path) -> bytes:
    """norm spec → resolve workspace assets → self-contained .html bytes.

    The asset manifest (path/mime/bytes/sha256 — never the bytes themselves)
    is embedded in the spec JSON so inspect reports the inventory and a
    revise re-resolves refs against the CURRENT workspace files.
    """
    norm = _norm_spec(spec)
    assets = _resolve_assets(norm, workspace_path)
    norm["assets"] = [
        {"path": src, "mime": e["mime"], "bytes": e["bytes"], "sha256": e["sha256"]}
        for src, e in sorted(assets.items())
    ]
    return _render_full(norm, assets).encode("utf-8")


def build(spec: dict, workspace_path: str | Path) -> bytes:
    return _finalize(spec, workspace_path)


def revise(data: bytes, ops: list[dict], workspace_path: str | Path) -> bytes:
    spec = _extract_spec(data)
    slides = spec["slides"]
    for op in ops:
        kind = op.get("op")
        if kind == "set_title":
            spec["title"] = str(op["title"])
        elif kind == "set_theme":
            spec["theme"] = _theme({"theme": op.get("theme")}) if op.get("theme") else {}
        elif kind == "add_slide":
            slide = op.get("slide")
            if not isinstance(slide, dict):
                raise ValueError("add_slide needs a slide object")
            idx = len(slides)
            if "at" in op:
                idx = _slide_index(spec, op["at"]) if not isinstance(op["at"], int) else op["at"]
                if not 0 <= idx <= len(slides):
                    raise ValueError(f"add_slide 'at' out of range: {idx}")
            sid = str(slide.get("id") or f"s{len(slides) + 1}")
            if any(s.get("id") == sid for s in slides):
                raise ValueError(f"duplicate slide id: {sid}")
            slides.insert(idx, {**slide, "id": sid})
        elif kind == "remove_slide":
            del slides[_slide_index(spec, op["slide"])]
        elif kind == "set_slide":
            i = _slide_index(spec, op["slide"])
            patch = {k: v for k, v in op.items() if k not in {"op", "slide"}}
            slides[i] = {**slides[i], **patch, "id": slides[i]["id"]}
        else:
            raise ValueError(f"unknown deck op: {kind}")
    if not slides:
        raise ValueError("deck would have zero slides — remove_slide refused")
    if len(slides) > MAX_SLIDES:
        raise ValueError(f"deck exceeds {MAX_SLIDES} slides")
    return _finalize(spec, workspace_path)


def inspect(data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace")
    spec = _extract_spec(data)
    section_ids = re.findall(r'<section class="slide[^"]*" data-slide-id="([^"]+)"', text)
    theme = spec.get("theme") or {}
    rt = re.search(r'<main id="deck" data-runtime="([^"]+)"', text)
    return {
        "structure": {
            "title": spec.get("title"),
            "slides": len(spec.get("slides", [])),
            "slide_ids": [s.get("id") for s in spec.get("slides", [])],
            "section_ids_match": section_ids == [s.get("id") for s in spec.get("slides", [])],
            "theme": sorted(theme) if theme else None,
            "runtime": rt.group(1) if rt else RUNTIME_VERSION,
            "assets": spec.get("assets") or [],
            "reveal_blocks": sum(
                1
                for s in spec.get("slides", [])
                for b in (s.get("blocks") or [])
                if isinstance(b, dict) and b.get("reveal")
            ),
            "notes": sum(1 for s in spec.get("slides", []) if s.get("notes")),
        }
    }


_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
_RUNTIME_HASHES = " ".join(
    "'sha256-" + base64.b64encode(hashlib.sha256(js.encode()).digest()).decode() + "'"
    for _, js in _KNOWN_RUNTIMES
)

# Serving boundary for admitted decks: no default resources, no connections,
# no forms/navigation escapes; the ONLY executable scripts are the platform
# runtimes (one per known version), each pinned by hash — even a crafted
# file that slips past admission cannot run foreign JS. The sandbox
# directive keeps the document on an opaque origin even if the iframe
# attribute were ever dropped.
DECK_CSP = (
    "default-src 'none'; "
    f"script-src {_RUNTIME_HASHES}; "
    "style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'self'; sandbox allow-scripts"
)


def admission(data: bytes) -> dict | None:
    """Playback admission — None unless the bytes are a generated deck whose
    every <script> is platform-owned (spec JSON or the exact runtime).

    This is the constrained-scripting-model half of bounded execution: deck
    fragments can't carry script (build-time sanitizer), and admission
    refuses any file containing scripts outside the two known shapes, so
    no arbitrary JS ever reaches the player. Static source/download stays
    available regardless — admission gates *execution*, not access.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _MARKER not in text:
        return None
    if not validate(data)["valid"]:
        return None
    runtime_seen = 0
    runtime_version = None
    known = {js.strip(): ver for ver, js in _KNOWN_RUNTIMES}
    for attrs, body in _SCRIPT_RE.findall(text):
        if 'id="deck-spec"' in attrs:
            try:
                json.loads(body)
            except json.JSONDecodeError:
                return None
            continue
        if body.strip() in known:
            runtime_seen += 1
            runtime_version = known[body.strip()]
            continue
        return None  # any other script → not admissible
    if runtime_seen != 1:
        return None
    spec = _extract_spec(data)
    return {
        "runtime": runtime_version,
        "title": spec.get("title"),
        "slides": len(spec.get("slides", [])),
    }


def validate(data: bytes) -> dict:
    errors: list[str] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"valid": False, "errors": ["not utf-8"]}
    if _MARKER not in text:
        errors.append("missing caberos-deck marker — not a generated deck")
    try:
        spec = _extract_spec(data)
    except ValueError as e:
        errors.append(str(e))
        spec = None
    if spec is not None:
        try:
            _norm_spec(spec)
        except ValueError as e:
            errors.append(f"spec invalid: {e}")
        sections = len(re.findall(r'<section class="slide[^"]*"', text))
        if sections != len(spec.get("slides", [])):
            n_spec = len(spec.get("slides", []))
            errors.append(f"slide section count {sections} != spec slides {n_spec}")
    # Gross well-formedness — the parser is lenient; fatal errors only.
    probe = _Sanitizer()
    try:
        probe.feed(text)
        probe.close()
    except Exception as e:  # HTMLParser rarely raises; belt-and-braces
        errors.append(f"html parse failed: {e}")
    return {"valid": not errors, "errors": errors}
