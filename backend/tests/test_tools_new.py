"""Tests for the new tools: file.search, file.glob, datetime.now, web.search, web.fetch."""

import os

import pytest

from agentos.capabilities.tools.datetime_tool import datetime_now
from agentos.capabilities.tools.search import file_glob, file_search


# --- file.search ---

@pytest.mark.asyncio
async def test_file_search_finds_matches(workspace):
    # Create test files
    with open(os.path.join(workspace, "a.py"), "w") as f:
        f.write("def hello():\n    print('hello world')\n")
    with open(os.path.join(workspace, "b.py"), "w") as f:
        f.write("def goodbye():\n    print('bye')\n")

    result = await file_search({"pattern": "hello"}, workspace_path=workspace)
    # "hello" appears in both "def hello():" and "print('hello world')"
    assert result["count"] == 2
    assert all(m["file"] == "a.py" for m in result["matches"])
    assert result["matches"][0]["line"] == 1
    assert "hello" in result["matches"][0]["text"]


@pytest.mark.asyncio
async def test_file_search_regex(workspace):
    with open(os.path.join(workspace, "test.py"), "w") as f:
        f.write("import os\nimport sys\nfrom pathlib import Path\n")

    result = await file_search({"pattern": r"^import \w+"}, workspace_path=workspace)
    # Only lines starting with "import" — not "from pathlib import Path"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_file_search_glob_filter(workspace):
    with open(os.path.join(workspace, "code.py"), "w") as f:
        f.write("target_string here\n")
    with open(os.path.join(workspace, "code.js"), "w") as f:
        f.write("target_string here\n")

    result = await file_search(
        {"pattern": "target_string", "glob": "*.py"},
        workspace_path=workspace,
    )
    assert result["count"] == 1
    assert result["matches"][0]["file"] == "code.py"


@pytest.mark.asyncio
async def test_file_search_ignore_case(workspace):
    with open(os.path.join(workspace, "test.txt"), "w") as f:
        f.write("Hello World\nHELLO\nhello\n")

    result = await file_search(
        {"pattern": "hello", "ignore_case": True},
        workspace_path=workspace,
    )
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_file_search_max_results(workspace):
    with open(os.path.join(workspace, "big.txt"), "w") as f:
        for i in range(100):
            f.write(f"match line {i}\n")

    result = await file_search(
        {"pattern": "match", "max_results": 10},
        workspace_path=workspace,
    )
    assert result["count"] == 10
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_file_search_no_matches(workspace):
    with open(os.path.join(workspace, "test.txt"), "w") as f:
        f.write("nothing here\n")

    result = await file_search({"pattern": "nonexistent"}, workspace_path=workspace)
    assert result["count"] == 0
    assert result["matches"] == []


@pytest.mark.asyncio
async def test_file_search_invalid_regex(workspace):
    result = await file_search({"pattern": "[invalid"}, workspace_path=workspace)
    assert "error" in result


@pytest.mark.asyncio
async def test_file_search_skips_hidden_dirs(workspace):
    os.makedirs(os.path.join(workspace, ".git"))
    with open(os.path.join(workspace, ".git", "config"), "w") as f:
        f.write("secret_match\n")
    with open(os.path.join(workspace, "visible.txt"), "w") as f:
        f.write("secret_match\n")

    result = await file_search({"pattern": "secret_match"}, workspace_path=workspace)
    assert result["count"] == 1
    assert result["matches"][0]["file"] == "visible.txt"


# --- file.glob ---

@pytest.mark.asyncio
async def test_file_glob_finds_files(workspace):
    with open(os.path.join(workspace, "a.py"), "w") as f:
        f.write("")
    with open(os.path.join(workspace, "b.py"), "w") as f:
        f.write("")
    with open(os.path.join(workspace, "c.txt"), "w") as f:
        f.write("")

    result = await file_glob({"pattern": "*.py"}, workspace_path=workspace)
    assert result["count"] == 2
    assert "a.py" in result["files"]
    assert "b.py" in result["files"]
    assert "c.txt" not in result["files"]


@pytest.mark.asyncio
async def test_file_glob_recursive(workspace):
    os.makedirs(os.path.join(workspace, "src", "deep"))
    with open(os.path.join(workspace, "src", "deep", "test_module.py"), "w") as f:
        f.write("")
    with open(os.path.join(workspace, "main.py"), "w") as f:
        f.write("")

    result = await file_glob({"pattern": "*.py"}, workspace_path=workspace)
    assert result["count"] == 2
    assert "main.py" in result["files"]
    assert any("test_module.py" in f for f in result["files"])


@pytest.mark.asyncio
async def test_file_glob_max_results(workspace):
    for i in range(20):
        with open(os.path.join(workspace, f"file_{i}.txt"), "w") as f:
            f.write("")

    result = await file_glob(
        {"pattern": "*.txt", "max_results": 5},
        workspace_path=workspace,
    )
    assert result["count"] == 5
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_file_glob_no_matches(workspace):
    result = await file_glob({"pattern": "*.nonexistent"}, workspace_path=workspace)
    assert result["count"] == 0
    assert result["files"] == []


# --- datetime.now ---

@pytest.mark.asyncio
async def test_datetime_now_utc():
    result = await datetime_now({})
    assert "iso" in result
    assert "date" in result
    assert "time" in result
    assert "timezone" in result
    assert "weekday" in result
    assert "unix" in result
    assert "UTC" in result["timezone"] or "utc" in result["timezone"].lower()


@pytest.mark.asyncio
async def test_datetime_now_with_timezone():
    result = await datetime_now({"timezone": "America/New_York"})
    assert "iso" in result
    assert "New_York" in result["timezone"] or "America/New_York" in result["timezone"]


@pytest.mark.asyncio
async def test_datetime_now_invalid_timezone():
    result = await datetime_now({"timezone": "Invalid/Zone"})
    assert "error" in result
    assert "utc" in result  # falls back to UTC


# --- web.search and web.fetch ---
# These make real network calls — we test them with mocking to avoid
# network dependencies in the test suite.

@pytest.mark.asyncio
async def test_web_search_returns_results(monkeypatch):
    """Test web.search with a mocked HTTP response."""
    from agentos.capabilities.tools import web as web_module

    class FakeResponse:
        text = """
        <html><body>
        <div class="result">
            <h2 class="result__title"><a href="/l/?uddg=https%3A%2F%2Fexample.com%2F1">Example Result</a></h2>
            <a class="result__snippet">This is a snippet about the result.</a>
        </div>
        <div class="result">
            <h2 class="result__title"><a href="/l/?uddg=https%3A%2F%2Fexample.com%2F2">Second Result</a></h2>
            <a class="result__snippet">Another snippet here.</a>
        </div>
        </body></html>
        """
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(web_module.httpx, "AsyncClient", FakeClient)

    result = await web_module.web_search({"query": "test", "max_results": 5})
    assert result["query"] == "test"
    assert result["count"] == 2
    assert result["results"][0]["title"] == "Example Result"
    assert "example.com" in result["results"][0]["url"]


@pytest.mark.asyncio
async def test_web_fetch_extracts_text(monkeypatch):
    """Test web.fetch with a mocked HTML response."""
    from agentos.capabilities.tools import web as web_module

    class FakeResponse:
        text = """
        <html>
        <head><script>bad code</script><style>body { color: red; }</style></head>
        <body>
            <nav>Navigation</nav>
            <main>
                <h1>Title</h1>
                <p>This is the main content of the page.</p>
            </main>
            <footer>Footer text</footer>
        </body>
        </html>
        """
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(web_module.httpx, "AsyncClient", FakeClient)

    result = await web_module.web_fetch({"url": "https://example.com"})
    assert result["url"] == "https://example.com"
    assert "main content" in result["text"]
    # Script and style content should be removed
    assert "bad code" not in result["text"]
    assert "color: red" not in result["text"]


@pytest.mark.asyncio
async def test_web_fetch_truncates(monkeypatch):
    """Test web.fetch truncates long content."""
    from agentos.capabilities.tools import web as web_module

    long_text = "<html><body>" + ("A" * 20000) + "</body></html>"

    class FakeResponse:
        text = long_text
        headers = {"content-type": "text/html"}

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(web_module.httpx, "AsyncClient", FakeClient)

    result = await web_module.web_fetch(
        {"url": "https://example.com", "max_chars": 1000}
    )
    assert result["truncated"] is True
    assert "[... truncated]" in result["text"]
