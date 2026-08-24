"""Tests for tools: search_files (content/name/list modes), datetime_now, web_search, web_fetch."""

import os

import pytest

from agentos.capabilities.tools.datetime_tool import datetime_now
from agentos.capabilities.tools.file import read_file, search_files, write_file

# --- search_files: content mode (grep) ---


@pytest.mark.asyncio
async def test_search_content_finds_matches(workspace):
    with open(os.path.join(workspace, "a.py"), "w") as f:
        f.write("def hello():\n    print('hello world')\n")
    with open(os.path.join(workspace, "b.py"), "w") as f:
        f.write("def goodbye():\n    print('bye')\n")

    result = await search_files({"mode": "content", "pattern": "hello"}, workspace_path=workspace)
    assert result["count"] == 2
    assert all(m["file"] == "a.py" for m in result["matches"])
    assert result["matches"][0]["line"] == 1
    assert "hello" in result["matches"][0]["text"]


@pytest.mark.asyncio
async def test_search_content_regex(workspace):
    with open(os.path.join(workspace, "test.py"), "w") as f:
        f.write("import os\nimport sys\nfrom pathlib import Path\n")

    result = await search_files(
        {"mode": "content", "pattern": r"^import \w+"}, workspace_path=workspace
    )
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_search_content_glob_filter(workspace):
    with open(os.path.join(workspace, "code.py"), "w") as f:
        f.write("target_string here\n")
    with open(os.path.join(workspace, "code.js"), "w") as f:
        f.write("target_string here\n")

    result = await search_files(
        {"mode": "content", "pattern": "target_string", "glob": "*.py"},
        workspace_path=workspace,
    )
    assert result["count"] == 1
    assert result["matches"][0]["file"] == "code.py"


@pytest.mark.asyncio
async def test_search_content_ignore_case(workspace):
    with open(os.path.join(workspace, "test.txt"), "w") as f:
        f.write("Hello World\nHELLO\nhello\n")

    result = await search_files(
        {"mode": "content", "pattern": "hello", "ignore_case": True},
        workspace_path=workspace,
    )
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_search_content_max_results(workspace):
    with open(os.path.join(workspace, "big.txt"), "w") as f:
        for i in range(100):
            f.write(f"match line {i}\n")

    result = await search_files(
        {"mode": "content", "pattern": "match", "max_results": 10},
        workspace_path=workspace,
    )
    assert result["count"] == 10
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_search_content_no_matches(workspace):
    with open(os.path.join(workspace, "test.txt"), "w") as f:
        f.write("nothing here\n")

    result = await search_files(
        {"mode": "content", "pattern": "nonexistent"}, workspace_path=workspace
    )
    assert result["count"] == 0
    assert result["matches"] == []


@pytest.mark.asyncio
async def test_search_content_invalid_regex(workspace):
    result = await search_files(
        {"mode": "content", "pattern": "[invalid"}, workspace_path=workspace
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_search_content_skips_hidden_dirs(workspace):
    os.makedirs(os.path.join(workspace, ".git"))
    with open(os.path.join(workspace, ".git", "config"), "w") as f:
        f.write("secret_match\n")
    with open(os.path.join(workspace, "visible.txt"), "w") as f:
        f.write("secret_match\n")

    result = await search_files(
        {"mode": "content", "pattern": "secret_match"}, workspace_path=workspace
    )
    assert result["count"] == 1
    assert result["matches"][0]["file"] == "visible.txt"


# --- search_files: name mode (glob) ---


@pytest.mark.asyncio
async def test_search_name_finds_files(workspace):
    with open(os.path.join(workspace, "a.py"), "w") as f:
        f.write("")
    with open(os.path.join(workspace, "b.py"), "w") as f:
        f.write("")
    with open(os.path.join(workspace, "c.txt"), "w") as f:
        f.write("")

    result = await search_files({"mode": "name", "pattern": "*.py"}, workspace_path=workspace)
    assert result["count"] == 2
    assert "a.py" in result["files"]
    assert "b.py" in result["files"]
    assert "c.txt" not in result["files"]


@pytest.mark.asyncio
async def test_search_name_recursive(workspace):
    os.makedirs(os.path.join(workspace, "src", "deep"))
    with open(os.path.join(workspace, "src", "deep", "test_module.py"), "w") as f:
        f.write("")
    with open(os.path.join(workspace, "main.py"), "w") as f:
        f.write("")

    result = await search_files({"mode": "name", "pattern": "*.py"}, workspace_path=workspace)
    assert result["count"] == 2
    assert "main.py" in result["files"]
    assert any("test_module.py" in f for f in result["files"])


@pytest.mark.asyncio
async def test_search_name_max_results(workspace):
    for i in range(20):
        with open(os.path.join(workspace, f"file_{i}.txt"), "w") as f:
            f.write("")

    result = await search_files(
        {"mode": "name", "pattern": "*.txt", "max_results": 5},
        workspace_path=workspace,
    )
    assert result["count"] == 5
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_search_name_no_matches(workspace):
    result = await search_files(
        {"mode": "name", "pattern": "*.nonexistent"}, workspace_path=workspace
    )
    assert result["count"] == 0
    assert result["files"] == []


# --- search_files: list mode ---


@pytest.mark.asyncio
async def test_search_list_directory(workspace):
    with open(os.path.join(workspace, "a.txt"), "w") as f:
        f.write("a")
    with open(os.path.join(workspace, "b.txt"), "w") as f:
        f.write("b")
    os.makedirs(os.path.join(workspace, "subdir"))

    result = await search_files({"mode": "list", "path": "."}, workspace_path=workspace)
    names = [e["name"] for e in result["entries"]]
    assert "a.txt" in names
    assert "b.txt" in names
    assert "subdir" in names
    # subdir should be typed as "dir"
    subdir_entry = next(e for e in result["entries"] if e["name"] == "subdir")
    assert subdir_entry["type"] == "dir"


# --- read_file / write_file ---


@pytest.mark.asyncio
async def test_read_file(workspace):
    with open(os.path.join(workspace, "test.txt"), "w") as f:
        f.write("hello world")
    result = await read_file({"path": "test.txt"}, workspace_path=workspace)
    assert result["content"] == "hello world"


@pytest.mark.asyncio
async def test_read_file_line_range(workspace):
    with open(os.path.join(workspace, "lines.md"), "w") as f:
        f.write("line 1\nline 2\nline 3\nline 4\n")

    result = await read_file(
        {"path": "lines.md", "start_line": 2, "end_line": 3},
        workspace_path=workspace,
    )

    assert result["content"] == "line 2\nline 3\n"
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["total_lines"] == 4
    assert result["has_more"] is True
    assert result["next_start_line"] == 4


@pytest.mark.asyncio
async def test_read_file_line_range_last_chunk(workspace):
    with open(os.path.join(workspace, "lines.md"), "w") as f:
        f.write("line 1\nline 2\nline 3\nline 4\n")

    result = await read_file(
        {"path": "lines.md", "start_line": 3, "end_line": 4},
        workspace_path=workspace,
    )

    assert result["content"] == "line 3\nline 4\n"
    assert result["has_more"] is False
    assert "next_start_line" not in result


@pytest.mark.asyncio
async def test_read_file_image_requires_vision(workspace):
    from agentos.capabilities.tools.file import read_file

    with open(os.path.join(workspace, "image.png"), "wb") as f:
        f.write(b"fake image bytes")

    result = await read_file({"path": "image.png"}, workspace_path=workspace, supports_vision=False)
    assert result["mime_type"] == "image/png"
    assert "cannot inspect" in result["error"]


@pytest.mark.asyncio
async def test_read_file_image_returns_model_content_for_vision(workspace):
    from agentos.capabilities.tools.file import read_file

    with open(os.path.join(workspace, "image.png"), "wb") as f:
        f.write(b"fake image bytes")

    result = await read_file({"path": "image.png"}, workspace_path=workspace, supports_vision=True)
    assert result["mime_type"] == "image/png"
    assert result["_model_content"][1]["type"] == "image_url"
    assert result["_model_content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_write_file_creates(workspace):
    result = await write_file(
        {"path": "new.txt", "content": "new content"}, workspace_path=workspace
    )
    assert result["success"] is True
    assert result["action"] == "created"
    with open(os.path.join(workspace, "new.txt")) as f:
        assert f.read() == "new content"


@pytest.mark.asyncio
async def test_write_file_modifies(workspace):
    with open(os.path.join(workspace, "mod.txt"), "w") as f:
        f.write("old content")
    result = await write_file(
        {"path": "mod.txt", "content": "new content"}, workspace_path=workspace
    )
    assert result["action"] == "modified"
    assert "diff" in result


# --- datetime_now ---


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


# --- web_search and web_fetch ---
# These make real network calls — we test them with mocking.


@pytest.mark.asyncio
async def test_web_search_returns_results(monkeypatch):
    from agentos.capabilities.tools import web as web_module

    # Mock the DDGS class used by the new implementation
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def text(self, query, max_results=5):
            return [
                {
                    "title": "Example Result",
                    "href": "https://example.com/1",
                    "body": "This is a snippet about the result.",
                },
                {
                    "title": "Second Result",
                    "href": "https://example.com/2",
                    "body": "Another snippet here.",
                },
            ]

    class FakeDDGSModule:
        DDGS = FakeDDGS

    import sys

    monkeypatch.setitem(sys.modules, "duckduckgo_search", FakeDDGSModule)

    result = await web_module.web_search({"query": "test", "max_results": 5})
    assert result["query"] == "test"
    assert result["count"] == 2
    assert result["results"][0]["title"] == "Example Result"
    assert "example.com" in result["results"][0]["url"]


@pytest.mark.asyncio
async def test_web_fetch_extracts_text(monkeypatch):
    from agentos.capabilities.tools import web as web_module

    class FakeResponse:
        text = """
        <html>
        <head><script>bad code</script><style>body { color: red; }</style></head>
        <body>
        <h1>Title</h1>
        <p>Hello world</p>
        <nav>Navigation</nav>
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
    assert "content" in result
    assert "Hello world" in result["content"]
    assert "bad code" not in result["content"]
