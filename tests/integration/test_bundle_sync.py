"""Integration tests for local and web run bundle sync."""

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from novel_translator.application.approve import (
    ApproveArtifact,
    ArtifactApprovalInput,
)
from novel_translator.application.bundles import (
    ExportRunBundle,
    ExportRunBundleInput,
    ImportRunBundle,
    ImportRunBundleInput,
)
from novel_translator.application.export import (
    ExportArtifact,
    ExportArtifactInput,
)
from novel_translator.domain.translation import TranslationBible
from novel_translator.infrastructure.export import FilesystemArtifactWriter
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text
from novel_translator.web.app import create_app

RUN_ID = "b" * 32


def seed_run(
    workspace: Path,
    run_id: str = RUN_ID,
    *,
    draft: str = "# Episode 1: Rainy Day\n\nDraft text.",
    source: str = "Source text.",
) -> None:
    """Persist one minimal verifiable run through raw workspace files."""
    bible = TranslationBible(title="Novel").model_dump_json()
    run_dir = workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "source.txt").write_text(source, encoding="utf-8")
    (run_dir / "draft.md").write_text(draft, encoding="utf-8")
    (run_dir / "draft.sha256").write_text(sha256_text(draft), encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "identity": {"novel": "novel", "chapter": 1},
                "source_hash": sha256_text(source),
                "bible_hash": sha256_text(
                    TranslationBible.model_validate_json(
                        bible
                    ).model_dump_json()
                ),
                "status": "draft_completed",
                "timestamp": "2026-09-06T10:00:00+00:00",
                "provider": "opencode-go",
                "model": "catalog-model",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "bible.json").write_text(bible, encoding="utf-8")
    current = workspace / "current"
    current.mkdir(exist_ok=True)
    (current / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "draft_hash": sha256_text(draft)}),
        encoding="utf-8",
    )


RUN_ID = "b" * 32

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
"""


def build_client(tmp_path: Path) -> tuple[TestClient, Path]:
    """Compose the web app over a temporary catalog and workspace."""
    (tmp_path / "sources").mkdir(exist_ok=True)
    (tmp_path / "sources" / "chapter-1.md").write_text(
        "source", encoding="utf-8"
    )
    (tmp_path / "bible.yaml").write_text("title: Novel\n", encoding="utf-8")
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    workspace = tmp_path / "web-workspace"
    workspace.mkdir(exist_ok=True)
    database_url = f"sqlite:///{(tmp_path / 'web.sqlite').as_posix()}"
    app = create_app(config, workspace, database_url)
    return TestClient(app), workspace


def test_local_to_web_to_local_round_trip(tmp_path: Path) -> None:
    """A bundle travels local, web, local with verified artifacts intact."""
    local = tmp_path / "local"
    seed_run(local)
    workspace = Workspace(local)
    ApproveArtifact(workspace).execute(ArtifactApprovalInput(RUN_ID, None))
    ExportArtifact(workspace, FilesystemArtifactWriter()).execute(
        ExportArtifactInput(RUN_ID, tmp_path / "site.md", None)
    )
    payload = (
        ExportRunBundle(workspace)
        .execute(ExportRunBundleInput(RUN_ID))
        .payload
    )

    client, web_workspace = build_client(tmp_path)
    response = client.post(
        "/bundles/import",
        files={"bundle": ("run.ntbundle", payload, "application/zip")},
        data={"novel": "novel"},
    )
    assert response.status_code in (200, 303)

    web = Workspace(web_workspace)
    draft = web.runs.generated_draft(RUN_ID).content
    assert draft == "# Episode 1: Rainy Day\n\nDraft text."
    assert len(web.approvals.approval_events(RUN_ID)) == 1
    assert len(web.exports.events_for_run(RUN_ID)) == 1

    back = ExportRunBundle(web).execute(ExportRunBundleInput(RUN_ID)).payload
    final = tmp_path / "final"
    ImportRunBundle(Workspace(final)).execute(ImportRunBundleInput(back))
    final_draft = Workspace(final).runs.generated_draft(RUN_ID).content
    assert final_draft == "# Episode 1: Rainy Day\n\nDraft text."


def test_web_download_then_cli_style_import(tmp_path: Path) -> None:
    """The chapter download carries a filename and re-importable bytes."""
    seed_run(tmp_path / "local")
    local = Workspace(tmp_path / "local")
    payload = (
        ExportRunBundle(local).execute(ExportRunBundleInput(RUN_ID)).payload
    )
    client, web_workspace = build_client(tmp_path)
    ImportRunBundle(Workspace(web_workspace)).execute(
        ImportRunBundleInput(payload)
    )

    response = client.get("/novels/novel/chapters/1/bundle")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith('.ntbundle"')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("bundle.json"))
    assert manifest["run_id"] == RUN_ID

    reimported = ImportRunBundle(Workspace(tmp_path / "clone")).execute(
        ImportRunBundleInput(response.content)
    )
    assert reimported.created is True


def test_import_rejects_divergent_bytes(tmp_path: Path) -> None:
    """The web import refuses bundles colliding with different bytes."""
    seed_run(tmp_path / "local")
    payload = (
        ExportRunBundle(Workspace(tmp_path / "local"))
        .execute(ExportRunBundleInput(RUN_ID))
        .payload
    )
    client, web_workspace = build_client(tmp_path)
    seed_run(web_workspace, draft="# Episode 1: Rainy Day\n\nDifferent draft.")

    response = client.post(
        "/novels/novel/chapters/1/bundle/import",
        files={"bundle": ("run.ntbundle", payload, "application/zip")},
        data={"run_choice": ""},
    )

    assert response.status_code == 409
    assert "different content" in response.text.lower()


def test_chapter_page_exposes_sync_card(tmp_path: Path) -> None:
    """The chapter page links the bundle download and import form."""
    client, web_workspace = build_client(tmp_path)
    seed_run(web_workspace)

    html = client.get("/novels/novel/chapters/1").text

    assert "Download bundle" in html
    assert "/novels/novel/chapters/1/bundle" in html
    assert "Import bundle" in html


def test_bundle_upload_rejects_oversize_and_garbage(tmp_path: Path) -> None:
    """Oversize and non-zip uploads fail without storing a run."""
    from novel_translator.web.routes.bundles import MAX_BUNDLE_BYTES

    client, web_workspace = build_client(tmp_path)
    oversize = client.post(
        "/novels/novel/chapters/1/bundle/import",
        files={"bundle": ("big.ntbundle", b"x" * (MAX_BUNDLE_BYTES + 1), "x")},
        data={"run_choice": ""},
    )
    assert oversize.status_code == 400
    garbage = client.post(
        "/novels/novel/chapters/1/bundle/import",
        files={"bundle": ("run.ntbundle", b"garbage", "application/zip")},
        data={"run_choice": ""},
    )
    assert garbage.status_code == 400
    assert not (web_workspace / "runs" / RUN_ID).exists()
    draft_hash = sha256_text("# Episode 1: Rainy Day\n\nDraft text.")
    assert draft_hash is not None


def test_web_import_rejects_divergent_current_projection(
    tmp_path: Path,
) -> None:
    """A clashing current/ projection is refused loudly via web import."""
    seed_run(tmp_path / "local")
    payload = (
        ExportRunBundle(Workspace(tmp_path / "local"))
        .execute(ExportRunBundleInput(RUN_ID))
        .payload
    )
    client, web_workspace = build_client(tmp_path)
    seed_run(web_workspace)
    (web_workspace / "current" / f"{RUN_ID}.json").write_text(
        json.dumps({"run_id": RUN_ID, "draft_hash": "0" * 64, "forged": True}),
        encoding="utf-8",
    )

    response = client.post(
        "/novels/novel/chapters/1/bundle/import",
        files={"bundle": ("run.ntbundle", payload, "application/zip")},
        data={"run_choice": ""},
    )

    assert response.status_code == 409
    assert "different content" in response.text.lower()
    stored = json.loads(
        (web_workspace / "current" / f"{RUN_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored["forged"] is True


def test_generic_import_refuses_ghost_novel_without_redirect(
    tmp_path: Path,
) -> None:
    """A bundle for an unregistered novel never yields a Location."""
    seed_run(tmp_path / "local")
    payload = (
        ExportRunBundle(Workspace(tmp_path / "local"))
        .execute(ExportRunBundleInput(RUN_ID))
        .payload
    )
    client, web_workspace = build_client(tmp_path)
    (tmp_path / "novels.yaml").write_text("novels: {}\n", encoding="utf-8")
    response = client.post(
        "/bundles/import",
        files={"bundle": ("run.ntbundle", payload, "application/zip")},
        data={"novel": "ghost"},
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert "location" not in dict(response.headers)
    assert not (web_workspace / "runs" / RUN_ID).exists()


def test_scoped_import_rejects_cross_novel_bundle_without_persist(
    tmp_path: Path,
) -> None:
    """A novel-1 bundle posted to the novel-2 chapter URL fails closed."""
    seed_run(tmp_path / "local")
    payload = (
        ExportRunBundle(Workspace(tmp_path / "local"))
        .execute(ExportRunBundleInput(RUN_ID))
        .payload
    )
    client, web_workspace = build_client(tmp_path)
    response = client.post(
        "/novels/other/chapters/1/bundle/import",
        files={"bundle": ("run.ntbundle", payload, "application/zip")},
        data={"run_choice": ""},
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert "location" not in dict(response.headers)
    assert not (web_workspace / "runs" / RUN_ID).exists()


def test_scoped_import_rejects_cross_chapter_bundle_without_persist(
    tmp_path: Path,
) -> None:
    """A chapter-1 bundle posted to the chapter-2 URL fails closed."""
    seed_run(tmp_path / "local")
    payload = (
        ExportRunBundle(Workspace(tmp_path / "local"))
        .execute(ExportRunBundleInput(RUN_ID))
        .payload
    )
    client, web_workspace = build_client(tmp_path)
    response = client.post(
        "/novels/novel/chapters/2/bundle/import",
        files={"bundle": ("run.ntbundle", payload, "application/zip")},
        data={"run_choice": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "location" not in dict(response.headers)
    assert "requested novel and chapter" in response.text
    assert not (web_workspace / "runs" / RUN_ID).exists()
