"""HTTP boundary tests for the web reading and review room."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from novel_translator.shared.utils import sha256_text
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

CHAPTER_URL = "/novels/novel/chapters/1"
FETCH_HEADERS = {"X-Requested-With": "fetch"}


def create_catalog(tmp_path: Path) -> Path:
    """Register one novel with two configured chapter sources."""
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "chapter-1.md").write_text("原文テキスト", encoding="utf-8")
    (sources / "chapter-2.md").write_text("第二章の原文", encoding="utf-8")
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    return config


def create_run(
    workspace: Path,
    run_id: str,
    *,
    novel: str = "novel",
    chapter: int = 1,
    draft: str = "Draft text.",
    source: str = "原文テキスト",
    status: str = "draft_completed",
    timestamp: str = "2026-09-06T10:00:00",
) -> None:
    """Persist one minimal valid translation run fixture."""
    run_dir = workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "identity": {"novel": novel, "chapter": chapter},
                "status": status,
                "timestamp": timestamp,
                "provider": "opencode-go",
                "model": "catalog-model",
                "source_hash": "1" * 64,
                "prompt_hash": "2" * 64,
                "prompt_template_hash": "3" * 64,
                "context_hash": "4" * 64,
                "bible_hash": "5" * 64,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "source.txt").write_text(source, encoding="utf-8")
    if status == "draft_completed":
        (run_dir / "draft.md").write_text(draft, encoding="utf-8")
        (run_dir / "draft.sha256").write_text(
            sha256_text(draft), encoding="utf-8"
        )
        current = workspace / "current"
        current.mkdir(exist_ok=True)
        (current / f"{run_id}.json").write_text(
            json.dumps({"run_id": run_id, "draft_hash": sha256_text(draft)}),
            encoding="utf-8",
        )


def build_client(
    tmp_path: Path, *, site_root: Path | None = None
) -> tuple[TestClient, Path]:
    """Compose the web app over a temporary catalog and workspace."""
    config = create_catalog(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database_url = f"sqlite:///{(tmp_path / 'web.sqlite').as_posix()}"
    app = create_app(config, workspace, database_url, site_root=site_root)
    return TestClient(app), workspace


class _Panels(HTMLParser):
    """Map the split container state and each panel to its visibility."""

    def __init__(self) -> None:
        super().__init__()
        self.grid_active: str | None = None
        self.hidden: dict[str, bool] = {}

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "div":
            return
        names = dict(attrs)
        if "chapter-grid" in (names.get("class") or "").split():
            self.grid_active = names.get("data-active")
        if names.get("role") == "tabpanel" and names.get("id"):
            assert names["id"] is not None
            self.hidden[names["id"]] = "hidden" in names


def working_copy_version(html: str) -> int:
    """Extract the optimistic version token from the editor."""
    match = re.search(r'name="version" value="(\d+)"', html)
    assert match is not None, "editor version input not found"
    return int(match.group(1))


def working_copy_id(html: str) -> str:
    """Extract the editor session identity token."""
    match = re.search(r'name="working_copy_id" value="([0-9a-f]{32})"', html)
    assert match is not None, "working copy identity input not found"
    return match.group(1)


def start_working_copy(client: TestClient, run_choice: str = "") -> None:
    """Start the working copy for the fixture chapter."""
    response = client.post(
        f"{CHAPTER_URL}/working-copy",
        data={"run_choice": run_choice},
        follow_redirects=False,
    )
    assert response.status_code == 303


def save_working_copy(
    client: TestClient,
    version: int,
    content: str,
    *,
    run_choice: str = "",
    copy_id: str | None = None,
) -> Any:
    """Save the working copy the way the autosave script does."""
    if copy_id is None:
        copy_id = working_copy_id(client.get(CHAPTER_URL).text)
    return client.post(
        f"{CHAPTER_URL}/working-copy/save",
        data={
            "working_copy_id": copy_id,
            "version": str(version),
            "content": content,
            "run_choice": run_choice,
        },
        headers=FETCH_HEADERS,
    )


def test_dashboard_lists_novels_recent_chapters_and_states(
    tmp_path: Path,
) -> None:
    """The dashboard groups chapters without exposing run identifiers."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    html = client.get("/").text
    assert "Test Novel" in html
    assert "Chapter 1" in html
    assert "Draft available" in html
    assert "a" * 32 not in html


def test_novel_page_filters_by_state_and_search(tmp_path: Path) -> None:
    """Search and state filters narrow the chapter list."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    html = client.get("/novels/novel").text
    assert "Chapter 1" in html
    assert "Chapter 2" in html

    filtered = client.get(
        "/novels/novel?state=draft_available",
        headers={"HX-Request": "true"},
    ).text
    assert "<html" not in filtered
    assert "Chapter 1" in filtered
    assert "Chapter 2" not in filtered

    searched = client.get(
        "/novels/novel?q=2", headers={"HX-Request": "true"}
    ).text
    assert "Chapter 2" in searched
    assert "Chapter 1" not in searched


def test_chapter_page_shows_source_and_draft_with_details_collapsed(
    tmp_path: Path,
) -> None:
    """The chapter page reads well and keeps identifiers collapsed."""
    client, workspace = build_client(tmp_path)
    run_id = "c" * 32
    create_run(workspace, run_id)
    html = client.get(CHAPTER_URL).text
    assert "原文テキスト" in html
    assert "Draft text." in html
    assert "Start working copy" in html
    details_at = html.index("Technical details")
    assert run_id not in html[:details_at]
    assert run_id in html[details_at:]


def test_ambiguous_chapter_requires_explicit_run_choice(
    tmp_path: Path,
) -> None:
    """Two valid runs force an explicit choice; each choice opens its run."""
    client, workspace = build_client(tmp_path)
    create_run(
        workspace,
        "a" * 32,
        draft="First draft.",
        timestamp="2026-09-06T10:00:00",
    )
    create_run(
        workspace,
        "b" * 32,
        draft="Second draft.",
        timestamp="2026-09-06T11:00:00",
    )

    picker = client.get(CHAPTER_URL).text
    assert "more than one translation run" in picker
    assert "First draft." not in picker
    assert "Second draft." not in picker
    assert 'href="/novels/novel/chapters/1?run_choice=1"' in picker
    assert 'href="/novels/novel/chapters/1?run_choice=2"' in picker

    first = client.get(f"{CHAPTER_URL}?run_choice=1").text
    assert "First draft." in first
    second = client.get(f"{CHAPTER_URL}?run_choice=2").text
    assert "Second draft." in second

    invalid = client.get(f"{CHAPTER_URL}?run_choice=3")
    assert invalid.status_code == 400
    assert "Invalid run choice" in invalid.text


def test_working_copy_save_diff_preview_and_revision_flow(
    tmp_path: Path,
) -> None:
    """Editing flows through save, diff, safe preview, and revision."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    start_working_copy(client)

    page = client.get(CHAPTER_URL).text
    assert "Draft text." in page
    version = working_copy_version(page)
    assert version >= 1

    content = "Edited **bold** text.\n\n<script>alert(1)</script>"
    saved = save_working_copy(client, version, content)
    assert saved.status_code == 200
    assert f'data-version="{version + 1}"' in saved.text

    reloaded = client.get(CHAPTER_URL).text
    assert "Edited" in reloaded
    assert working_copy_version(reloaded) == version + 1

    diff = client.get(f"{CHAPTER_URL}/working-copy/diff").text
    assert "Draft text." in diff
    assert "Edited" in diff

    preview = client.get(f"{CHAPTER_URL}/working-copy/preview").text
    assert "<strong>bold</strong>" in preview
    assert "&lt;script&gt;" in preview
    assert "<script>" not in preview

    revision = client.post(
        f"{CHAPTER_URL}/revision",
        data={
            "working_copy_id": working_copy_id(reloaded),
            "note": "polish",
            "run_choice": "",
        },
        follow_redirects=False,
    )
    assert revision.status_code == 303
    history = client.get(f"{CHAPTER_URL}?done=revision-created").text
    assert "Revision 1" in history
    assert "polish" in history
    assert "Working copy ready" not in history
    assert "Revision created from your working copy." in history
    assert "Start working copy" in history


def test_stale_save_returns_conflict_preserving_both_versions(
    tmp_path: Path,
) -> None:
    """A stale version returns 409 with both contents and no silent loss."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    start_working_copy(client)

    page = client.get(CHAPTER_URL).text
    version = working_copy_version(page)
    first = save_working_copy(client, version, "First version")
    assert first.status_code == 200

    stale = save_working_copy(client, version, "Second version")
    assert stale.status_code == 409
    assert "First version" in stale.text
    assert "Second version" in stale.text
    assert "Keep my version" in stale.text
    assert 'name="version" value="2"' in stale.text

    server_page = client.get(CHAPTER_URL).text
    assert "First version" in server_page
    assert "Second version" not in server_page

    resolved = save_working_copy(client, version + 1, "Second version")
    assert resolved.status_code == 200
    final_page = client.get(CHAPTER_URL).text
    assert "Second version" in final_page


def test_discard_working_copy_keeps_draft_untouched(tmp_path: Path) -> None:
    """Discarding removes only the working copy."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    start_working_copy(client)

    page = client.get(CHAPTER_URL).text
    version = working_copy_version(page)
    save_working_copy(client, version, "Changed locally")

    discarded = client.post(
        f"{CHAPTER_URL}/working-copy/discard",
        data={
            "working_copy_id": working_copy_id(page),
            "run_choice": "",
        },
        follow_redirects=False,
    )
    assert discarded.status_code == 303
    after = client.get(f"{CHAPTER_URL}?done=discarded").text
    assert "Working copy discarded" in after
    assert "Draft text." in after
    assert "Changed locally" not in after
    assert "Start working copy" in after


def test_approve_revoke_and_export_revision(tmp_path: Path) -> None:
    """Approval gates export into the configured site checkout."""
    site_root = tmp_path / "site"
    site_root.mkdir()
    client, workspace = build_client(tmp_path, site_root=site_root)
    create_run(workspace, "a" * 32)
    start_working_copy(client)

    page = client.get(CHAPTER_URL).text
    version = working_copy_version(page)
    copy_id = working_copy_id(page)
    save_working_copy(
        client,
        version,
        "Chapter 1: A New Dawn\n\nBody.",
        copy_id=copy_id,
    )
    client.post(
        f"{CHAPTER_URL}/revision",
        data={"working_copy_id": copy_id, "note": "", "run_choice": ""},
    )

    approved = client.post(
        f"{CHAPTER_URL}/approval", data={"revision": "1", "run_choice": ""}
    )
    assert approved.status_code == 200
    history = client.get(CHAPTER_URL).text
    assert "Approved" in history

    exported = client.post(
        f"{CHAPTER_URL}/export",
        data={"revision": "1", "run_choice": ""},
        follow_redirects=False,
    )
    assert exported.status_code == 303
    destination = site_root / "src" / "content" / "novels" / "novel" / "001.md"
    exported_text = destination.read_text(encoding="utf-8")
    assert 'chapterTitle: "Chapter 1: A New Dawn"' in exported_text
    assert "publishDate:" in exported_text
    assert "Body." in exported_text

    revoked = client.post(
        f"{CHAPTER_URL}/approval/revoke",
        data={"revision": "1", "run_choice": ""},
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    assert "Approved" not in client.get(CHAPTER_URL).text


def test_export_without_approval_is_rejected(tmp_path: Path) -> None:
    """Exporting an unapproved revision orients the reviewer."""
    site_root = tmp_path / "site"
    site_root.mkdir()
    client, workspace = build_client(tmp_path, site_root=site_root)
    create_run(workspace, "a" * 32)
    response = client.post(f"{CHAPTER_URL}/export", data={"run_choice": ""})
    assert response.status_code == 409
    assert "not been approved" in response.text


def test_error_and_empty_states_orient_the_reader(tmp_path: Path) -> None:
    """Unknown novels and runless chapters explain what to do next."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)

    unknown = client.get("/novels/unknown")
    assert unknown.status_code == 404
    assert "not registered" in unknown.text

    runless = client.get("/novels/novel/chapters/2").text
    assert "no translation run yet" in runless
    assert "第二章の原文" in runless
    assert "/translate?novel=novel&chapter=2" in runless

    missing_page = client.get("/novels/novel/chapters/99")
    assert missing_page.status_code == 404
    assert "not configured" in missing_page.text

    unconfigured = client.post(
        f"{CHAPTER_URL}/export", data={"run_choice": ""}
    )
    assert unconfigured.status_code == 400
    assert "Exports are not configured" in unconfigured.text


def test_textual_chapter_search_returns_no_matches(tmp_path: Path) -> None:
    """A nonnumeric query never degenerates into an unfiltered listing."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)

    html = client.get(
        "/novels/novel?q=chapter", headers={"HX-Request": "true"}
    ).text

    assert "Chapter 1" not in html
    assert "Chapter 2" not in html


def test_draft_remains_readable_when_source_is_missing(tmp_path: Path) -> None:
    """Independent artifact reads preserve a valid generated draft."""
    client, workspace = build_client(tmp_path)
    run_id = "a" * 32
    create_run(workspace, run_id, draft="Readable without source.")
    (workspace / "runs" / run_id / "source.txt").unlink()

    html = client.get(CHAPTER_URL).text

    assert "Readable without source." in html
    assert "source text for this run is not readable" in html


def test_replaced_working_copy_rejects_stale_editor_identity(
    tmp_path: Path,
) -> None:
    """A stale tab cannot write into a replacement working copy."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    start_working_copy(client)
    old_page = client.get(CHAPTER_URL).text
    old_id = working_copy_id(old_page)
    client.post(
        f"{CHAPTER_URL}/working-copy/discard",
        data={"working_copy_id": old_id, "run_choice": ""},
    )
    start_working_copy(client)
    new_page = client.get(CHAPTER_URL).text
    new_id = working_copy_id(new_page)

    response = save_working_copy(
        client,
        working_copy_version(old_page),
        "Stale tab content",
        copy_id=old_id,
    )

    assert old_id != new_id
    assert response.status_code == 409
    assert "editing session is stale" in response.text
    current = client.get(CHAPTER_URL).text
    assert "Stale tab content" not in current
    assert "Draft text." in current


def test_active_working_copy_is_reported_as_in_review(tmp_path: Path) -> None:
    """An active editorial session changes the aggregate chapter state."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    start_working_copy(client)

    html = client.get("/").text

    assert "In review" in html


def test_technical_details_expose_available_audit_hashes(
    tmp_path: Path,
) -> None:
    """Operators can inspect complete hashes without exposing them normally."""
    client, workspace = build_client(tmp_path)
    run_id = "a" * 32
    create_run(workspace, run_id)

    html = client.get(CHAPTER_URL).text
    technical = html[html.index("Technical details") :]

    assert sha256_text("Draft text.") in technical
    for digit in "12345":
        assert digit * 64 in technical


def test_draft_approval_is_scoped_to_selected_run_and_artifact(
    tmp_path: Path,
) -> None:
    """The draft badge reflects its exact run even when revisions exist."""
    client, workspace = build_client(tmp_path)
    create_run(
        workspace,
        "a" * 32,
        draft="First draft.",
        timestamp="2026-09-06T10:00:00",
    )
    create_run(
        workspace,
        "b" * 32,
        draft="Second draft.",
        timestamp="2026-09-06T11:00:00",
    )
    client.post(
        f"{CHAPTER_URL}/approval",
        data={"run_choice": "1"},
    )

    approved_page = client.get(f"{CHAPTER_URL}?run_choice=1").text
    other_page = client.get(f"{CHAPTER_URL}?run_choice=2").text
    approved_row = approved_page[
        approved_page.index("Generated draft") : approved_page.index(
            "</li>", approved_page.index("Generated draft")
        )
    ]
    other_row = other_page[
        other_page.index("Generated draft") : other_page.index(
            "</li>", other_page.index("Generated draft")
        )
    ]

    assert "Approved" in approved_row
    assert "Approved" not in other_row

    start_working_copy(client, "1")
    editor = client.get(f"{CHAPTER_URL}?run_choice=1").text
    client.post(
        f"{CHAPTER_URL}/revision",
        data={
            "working_copy_id": working_copy_id(editor),
            "run_choice": "1",
            "note": "",
        },
    )
    with_revision = client.get(f"{CHAPTER_URL}?run_choice=1").text
    draft_row = with_revision[
        with_revision.index("Generated draft") : with_revision.index(
            "</li>", with_revision.index("Generated draft")
        )
    ]
    assert "Approved" in draft_row


def test_multipart_crlf_save_creates_readable_revision(tmp_path: Path) -> None:
    """Browser newline encoding cannot corrupt immutable revision hashes."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    start_working_copy(client)
    editor = client.get(CHAPTER_URL).text
    copy_id = working_copy_id(editor)

    saved = client.post(
        f"{CHAPTER_URL}/working-copy/save",
        files={
            "working_copy_id": (None, copy_id),
            "version": (None, str(working_copy_version(editor))),
            "content": (None, "Line one\r\nLine two\r\n"),
            "run_choice": (None, ""),
        },
        headers=FETCH_HEADERS,
    )
    revision = client.post(
        f"{CHAPTER_URL}/revision",
        data={
            "working_copy_id": copy_id,
            "run_choice": "",
            "note": "multipart",
        },
        follow_redirects=False,
    )
    diff = client.get(f"{CHAPTER_URL}/revisions/1/diff")

    assert saved.status_code == 200
    assert revision.status_code == 303
    assert diff.status_code == 200
    assert "Line one" in diff.text


def test_healthz_answers_without_state(tmp_path: Path) -> None:
    """Orchestrator probes succeed without templates or workspace reads."""
    client, _ = build_client(tmp_path)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


def test_cross_site_post_is_refused(tmp_path: Path) -> None:
    """A foreign Origin cannot drive mutations with the reviewer's auth."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    response = client.post(
        f"{CHAPTER_URL}/working-copy",
        data={"run_choice": ""},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_same_origin_post_starts_working_copy(tmp_path: Path) -> None:
    """The reviewer's own Origin reaches the mutation behind the check."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    response = client.post(
        f"{CHAPTER_URL}/working-copy",
        data={"run_choice": ""},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_cross_site_fetch_metadata_is_refused(tmp_path: Path) -> None:
    """Fetch metadata backs the Origin check when headers are stripped."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    response = client.post(
        f"{CHAPTER_URL}/working-copy",
        data={"run_choice": ""},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_chapter_defaults_to_source_with_split_container(
    tmp_path: Path,
) -> None:
    """Wide screens split source beside edit/preview from this structure."""
    client, workspace = build_client(tmp_path)
    create_run(workspace, "a" * 32)
    panels = _Panels()
    panels.feed(client.get(CHAPTER_URL).text)
    assert panels.grid_active == "source"
    assert panels.hidden == {
        "panel-source": False,
        "panel-edit": True,
        "panel-preview": True,
    }
