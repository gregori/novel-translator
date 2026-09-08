"""Web boundary tests for translation jobs: form, enqueue, follow-up."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from novel_translator.web.app import create_app
from novel_translator.web.auth import hash_password

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


def build_client(tmp_path: Path) -> tuple[TestClient, Path]:
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
    return TestClient(app), workspace


def test_translate_form_prefills_novel_and_sources(
    tmp_path: Path,
) -> None:
    """The form offers catalog defaults and configured chapter sources."""
    client, _ = build_client(tmp_path)
    response = client.get("/translate?novel=novel&chapter=1")
    assert response.status_code == 200
    assert "catalog-model" in response.text
    assert "chapter-1.md" in response.text
    assert 'value="existing-1"' in response.text


def test_enqueue_existing_source_redirects_to_job(
    tmp_path: Path,
) -> None:
    """Posting the form persists a queued job and follows it."""
    client, _ = build_client(tmp_path)
    response = client.post(
        "/translate",
        data={
            "novel": "novel",
            "chapter": "1",
            "source_mode": "existing-1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "Queued" in detail.text
    assert 'hx-get="' in detail.text and "every 2s" in detail.text


def test_enqueue_upload_and_episode(tmp_path: Path) -> None:
    """Uploads persist source text; episodes keep their identifier."""
    client, _ = build_client(tmp_path)
    uploaded = client.post(
        "/translate",
        data={"novel": "novel", "chapter": "9", "source_mode": "upload"},
        files={"upload": ("chapter-9.md", "第九章の原文".encode())},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    assert "upload" in client.get(uploaded.headers["location"]).text

    client.post(
        "/translate",
        data={
            "novel": "novel",
            "chapter": "3",
            "source_mode": "episode",
            "episode": "12345678",
        },
        follow_redirects=False,
    )
    listed = client.get("/translate/jobs").text
    assert "Chapter 9" in listed
    assert "Chapter 3" in listed


def test_enqueue_rejects_bad_input(tmp_path: Path) -> None:
    """Unknown novels and missing sources explain what to do next."""
    client, _ = build_client(tmp_path)
    unknown = client.post("/translate", data={"novel": "nope", "chapter": "1"})
    assert unknown.status_code == 400
    assert "not registered" in unknown.text

    missing = client.post(
        "/translate",
        data={"novel": "novel", "chapter": "2", "source_mode": "existing-1"},
    )
    assert missing.status_code == 400
    assert "no configured source" in missing.text

    empty_upload = client.post(
        "/translate",
        data={"novel": "novel", "chapter": "2", "source_mode": "upload"},
        files={"upload": ("empty.md", b"   ")},
    )
    assert empty_upload.status_code == 400
    assert "must not be empty" in empty_upload.text


def test_cancel_and_retry_cycle(tmp_path: Path) -> None:
    """Queued jobs cancel at once; terminal jobs retry as a child job."""
    client, _ = build_client(tmp_path)
    created = client.post(
        "/translate",
        data={
            "novel": "novel",
            "chapter": "1",
            "source_mode": "existing-1",
        },
        follow_redirects=False,
    )
    job_url = created.headers["location"]
    cancelled = client.post(f"{job_url}/cancel", follow_redirects=False)
    assert cancelled.status_code == 303
    assert "Cancelled" in client.get(job_url).text

    retried = client.post(f"{job_url}/retry", follow_redirects=False)
    assert retried.status_code == 303
    child_url = retried.headers["location"]
    assert child_url != job_url
    child = client.get(child_url).text
    assert "Queued" in child
    assert "Retry of" in child


def test_status_fragment_stops_polling_when_terminal(
    tmp_path: Path,
) -> None:
    """Terminal fragments drop the polling trigger; active ones keep it."""
    client, _ = build_client(tmp_path)
    created = client.post(
        "/translate",
        data={
            "novel": "novel",
            "chapter": "1",
            "source_mode": "existing-1",
        },
        follow_redirects=False,
    )
    job_url = created.headers["location"]
    assert "every 2s" in client.get(f"{job_url}/status").text
    client.post(f"{job_url}/cancel")
    assert "every 2s" not in client.get(f"{job_url}/status").text


def test_password_gate_guards_translate_routes(
    tmp_path: Path, monkeypatch: object
) -> None:
    """With credentials configured, jobs pages redirect to sign-in."""
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "NOVEL_TRANSLATOR_AUTH_PASSWORD_HASH", hash_password("secret")
    )
    monkeypatch.setenv(  # type: ignore[attr-defined]
        "NOVEL_TRANSLATOR_SESSION_SECRET", "s" * 32
    )
    client, _ = build_client(tmp_path)
    response = client.get("/translate", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
