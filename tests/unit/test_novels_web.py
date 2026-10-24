"""Web boundary tests for novel registration: form, error, redirect."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from novel_translator.web.app import create_app

CATALOG_YAML = """novels:
  novel:
    title: Test Novel
    bible: bible.yaml
    source_directory: sources
    export:
      repository: gregori/novels-site
      directory: src/content/novels/novel
      filename_template: "{chapter:03}.md"
    translation:
      provider: opencode-go
      model: catalog-model
      default_volume: 2
"""

BIBLE_YAML = """title: Example Novel
source_language: ja
target_language: en
characters:
  - name: Haru
    aliases: [Haru-kun]
terminology:
  \u9b54\u6cd5: magic
honorific_rules:
  - Preserve meaningful honorifics.
naming_conventions:
  - Use canonical character names.
style_instructions:
  - Use natural English prose.
"""


def build_client(tmp_path: Path) -> TestClient:
    """Compose the web app over a temporary catalog and workspace."""
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "chapter-1.md").write_text("原文テキスト", encoding="utf-8")
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database_url = f"sqlite:///{(tmp_path / 'web.sqlite').as_posix()}"
    app = create_app(config, workspace, database_url)
    return TestClient(app)


def test_novel_new_form_renders_with_example_bible(
    tmp_path: Path,
) -> None:
    """The registration form shows defaults and the example bible."""
    client = build_client(tmp_path)
    response = client.get("/novels/new")
    assert response.status_code == 200
    assert 'name="novel_id"' in response.text
    assert 'name="bible_text"' in response.text
    assert 'name="bible_upload"' in response.text
    assert 'name="source_files"' in response.text
    assert "Example Novel" in response.text
    assert "gregori/novels-site" in response.text


def test_novel_new_registers_and_redirects_to_novel_page(
    tmp_path: Path,
) -> None:
    """Valid registration lands on the new novel's chapter listing."""
    client = build_client(tmp_path)
    response = client.post(
        "/novels/new",
        data={
            "novel_id": "fresh",
            "title": "Fresh Novel",
            "provider": "opencode-go",
            "model": "test-model",
            "volume": "3",
            "kakuyomu_work": "https://kakuyomu.jp/works/123",
            "export_repository": "gregori/novels-site",
            "export_directory": "src/content/titles/fresh",
            "export_filename_template": "{chapter:03}.md",
            "bible_text": BIBLE_YAML,
        },
        files=[("source_files", ("chapter-1.md", "原文".encode()))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/novels/fresh"
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "Fresh Novel" in page.text
    assert "Chapter 1" in page.text


def test_novel_new_registers_with_uploads_and_skips_sources(
    tmp_path: Path,
) -> None:
    """Bible uploads register; chapter sources may come later."""
    client = build_client(tmp_path)
    config = tmp_path / "novels.yaml"
    response = client.post(
        "/novels/new",
        data={
            "novel_id": "later",
            "title": "Later Novel",
            "model": "test-model",
        },
        files=[("bible_upload", ("bible.yaml", BIBLE_YAML.encode()))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/novels/later"
    stored = config.read_text(encoding="utf-8")
    assert "later:" in stored
    bible_path = tmp_path / "config" / "later.translation-bible.yaml"
    assert bible_path.read_text(encoding="utf-8") == BIBLE_YAML
    page = client.get("/novels/later")
    assert "No chapters yet." in page.text


def test_novel_new_reports_errors_in_form(tmp_path: Path) -> None:
    """Duplicates and bible conflicts re-render the form orienting."""
    client = build_client(tmp_path)
    duplicate = client.post(
        "/novels/new",
        data={
            "novel_id": "novel",
            "title": "Clash",
            "model": "test-model",
            "bible_text": BIBLE_YAML,
        },
    )
    assert duplicate.status_code == 400
    assert "already registered" in duplicate.text
    assert 'name="bible_text"' in duplicate.text

    conflict = client.post(
        "/novels/new",
        data={
            "novel_id": "other",
            "title": "Other",
            "model": "test-model",
            "bible_text": BIBLE_YAML,
        },
        files=[("bible_upload", ("bible.yaml", BIBLE_YAML.encode()))],
    )
    assert conflict.status_code == 400
    assert "either bible text or a bible file" in conflict.text

    oversized = client.post(
        "/novels/new",
        data={
            "novel_id": "big",
            "title": "Big",
            "model": "test-model",
            "bible_text": "",
        },
        files=[("bible_upload", ("bible.yaml", b"x" * (1_000_001)))],
    )
    assert oversized.status_code == 400
    assert "at most 1 MB" in oversized.text


def test_novel_new_rejects_too_many_source_files(tmp_path: Path) -> None:
    """A 33-file batch re-renders the form with 400, not 413."""
    from novel_translator.web.routes.novels import MAX_SOURCE_FILES

    assert MAX_SOURCE_FILES == 32
    client = build_client(tmp_path)
    files = [("source_files", (f"chapter-{i}.md", b"x")) for i in range(33)]
    response = client.post(
        "/novels/new",
        data={
            "novel_id": "crowded",
            "title": "Crowded",
            "model": "test-model",
            "bible_text": BIBLE_YAML,
        },
        files=files,
    )
    assert response.status_code == 400
    assert "At most 32 source files" in response.text
    assert 'name="bible_text"' in response.text


def test_novel_new_rejects_oversize_source_total(tmp_path: Path) -> None:
    """Sources totaling over 8 MB fail orienting before any file lands."""
    from novel_translator.web.routes.novels import MAX_SOURCE_BYTES

    assert MAX_SOURCE_BYTES == 8_000_000
    client = build_client(tmp_path)
    big = "x" * 900_000
    response = client.post(
        "/novels/new",
        data={
            "novel_id": "heavy",
            "title": "Heavy",
            "model": "test-model",
            "bible_text": BIBLE_YAML,
        },
        files=[
            ("source_files", (f"chapter-{i}.md", big.encode()))
            for i in range(9)
        ],
    )
    assert response.status_code == 400
    assert "at most 8 MB" in response.text
    assert not (tmp_path / "novel-sources" / "heavy").exists()


def test_dashboard_links_new_novel(tmp_path: Path) -> None:
    """The reading room points at the registration form, even when empty."""
    client = build_client(tmp_path)
    dashboard = client.get("/")
    assert 'href="/novels/new"' in dashboard.text


def test_healthz_skips_reload_and_serves_stale_dashboard(
    tmp_path: Path,
) -> None:
    """A corrupt catalog still answers healthz and stale reads."""
    client = build_client(tmp_path)
    assert client.get("/").status_code == 200
    (tmp_path / "novels.yaml").write_text(
        "novels: [broken\n", encoding="utf-8"
    )
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.text == "ok"
    stale = client.get("/")
    assert stale.status_code == 200
    assert "Test Novel" in stale.text


def test_cli_novel_register_and_duplicate(tmp_path: Path) -> None:
    """The CLI registers a novel and rejects a repeated identifier."""
    from typer.testing import CliRunner

    from novel_translator.cli.app import app as cli_app

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "chapter-1.md").write_text("原文テキスト", encoding="utf-8")
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    bible = tmp_path / "new-bible.yaml"
    bible.write_text(BIBLE_YAML, encoding="utf-8")
    runner = CliRunner()
    registered = runner.invoke(
        cli_app,
        [
            "novel",
            "register",
            "--novel-id",
            "fresh",
            "--title",
            "Fresh Novel",
            "--model",
            "test-model",
            "--bible",
            str(bible),
            "--config",
            str(config),
        ],
    )
    assert registered.exit_code == 0
    assert "Registered: fresh" in registered.output
    duplicate = runner.invoke(
        cli_app,
        [
            "novel",
            "register",
            "--novel-id",
            "fresh",
            "--title",
            "Fresh Novel",
            "--model",
            "test-model",
            "--bible",
            str(bible),
            "--config",
            str(config),
        ],
    )
    assert duplicate.exit_code == 2
    assert "already registered" in duplicate.output


def test_cli_novel_register_rejects_reserved_source_name(
    tmp_path: Path,
) -> None:
    """The CLI reuses the shared filename allowlist for --source-dir."""
    from typer.testing import CliRunner

    from novel_translator.cli.app import app as cli_app

    seed = tmp_path / "seed-sources"
    seed.mkdir()
    (seed / "COM1.md").write_text("reserved", encoding="utf-8")
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    bible = tmp_path / "new-bible.yaml"
    bible.write_text(BIBLE_YAML, encoding="utf-8")
    rejected = CliRunner().invoke(
        cli_app,
        [
            "novel",
            "register",
            "--novel-id",
            "fresh",
            "--title",
            "Fresh Novel",
            "--model",
            "test-model",
            "--bible",
            str(bible),
            "--config",
            str(config),
            "--source-dir",
            str(seed),
        ],
    )
    assert rejected.exit_code == 2
    assert "Invalid source filename" in rejected.output


def test_persistent_corruption_fails_loud_after_stale_serves(
    tmp_path: Path,
) -> None:
    """Permanent catalog damage serves stale briefly, then fails loud."""
    client = build_client(tmp_path)
    assert client.get("/").status_code == 200
    (tmp_path / "novels.yaml").write_text(
        "novels: [broken\n", encoding="utf-8"
    )
    for _ in range(3):
        assert client.get("/").status_code == 200
    loud = client.get("/")
    assert loud.status_code == 500
    assert client.get("/healthz").status_code == 200
