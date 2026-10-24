"""Behavior tests for novel registration and catalog seeding."""

from pathlib import Path

import pytest
import yaml

from novel_translator.application.novels import (
    RegisterNovel,
    RegisterNovelInput,
    validate_source_filename,
)
from novel_translator.domain.errors import ValidationError
from novel_translator.infrastructure.catalog import (
    NovelRegistry,
    ensure_catalog_seeded,
    load_catalog,
)

CATALOG_YAML = """novels:
  test-novel:
    title: Test Novel
    run_aliases:
      - legacy-test-novel
    bible: bible.yaml
    source_directory: sources
    kakuyomu_episode_root: https://kakuyomu.jp/works/123/episodes/
    export:
      repository: gregori/novels-site
      directory: src/content/novels/test-novel
      filename_template: "{chapter:03}.md"
    translation:
      provider: opencode-go
      model: test-model
      default_volume: 2
"""

BIBLE_TEXT = """title: New Novel
characters:
  - name: Haru
terminology:
  "魔法": magic
honorific_rules:
  - Preserve meaningful honorifics.
naming_conventions:
  - Use canonical character names.
style_instructions:
  - Use natural English prose.
"""


def create_registry(tmp_path: Path) -> NovelRegistry:
    """Create one valid catalog with bible and source directories."""
    (tmp_path / "sources").mkdir()
    (tmp_path / "bible.yaml").write_text(
        "title: Test Novel\n", encoding="utf-8"
    )
    config = tmp_path / "novels.yaml"
    config.write_text(CATALOG_YAML, encoding="utf-8")
    return load_catalog(config)


def register_request(**overrides: object) -> RegisterNovelInput:
    """Build one valid registration input with optional overrides."""
    fields: dict[str, object] = {
        "novel_id": "new-novel",
        "title": "New Novel",
        "model": "test-model",
        "export_repository": "gregori/novels-site",
        "bible_text": BIBLE_TEXT,
        "kakuyomu_episode_root": None,
    }
    fields.update(overrides)
    return RegisterNovelInput(**fields)  # type: ignore[arg-type]


def test_register_valid_novel_writes_bible_sources_and_catalog(
    tmp_path: Path,
) -> None:
    """A valid registration persists bible, sources, and catalog entry."""
    registry = create_registry(tmp_path)
    result = RegisterNovel(registry).execute(
        register_request(
            source_files={"chapter-1.md": "第一章"},
            kakuyomu_episode_root="https://kakuyomu.jp/works/456/episodes/",
        )
    )
    assert result.novel_id == "new-novel"
    assert result.bible.read_text(encoding="utf-8").startswith(
        "title: New Novel"
    )
    assert (result.source_directory / "chapter-1.md").read_text(
        encoding="utf-8"
    ) == "第一章"
    assert result.registry.novel("new-novel").title == "New Novel"
    assert (
        result.registry.novel("new-novel").kakuyomu_episode_root
        == "https://kakuyomu.jp/works/456/episodes"
    )
    raw = yaml.safe_load(
        (tmp_path / "novels.yaml").read_text(encoding="utf-8")
    )
    assert raw["novels"]["new-novel"]["translation"]["model"] == "test-model"


def test_register_rejects_duplicate_id(tmp_path: Path) -> None:
    """Re-registering an existing novel fails with an orienting error."""
    registry = create_registry(tmp_path)
    with pytest.raises(ValidationError, match="already registered"):
        RegisterNovel(registry).execute(
            register_request(novel_id="test-novel")
        )


def test_register_rejects_alias_collision(tmp_path: Path) -> None:
    """A novel id colliding with a registered alias is rejected."""
    registry = create_registry(tmp_path)
    with pytest.raises(ValidationError, match="already registered"):
        RegisterNovel(registry).execute(
            register_request(novel_id="legacy-test-novel")
        )


def test_register_rejects_invalid_bible(tmp_path: Path) -> None:
    """A bible that violates the schema fails before any file is written."""
    registry = create_registry(tmp_path)
    with pytest.raises(ValidationError, match="Invalid translation bible"):
        RegisterNovel(registry).execute(
            register_request(bible_text="characters: [unbalanced")
        )
    assert not (
        tmp_path / "config" / "new-novel.translation-bible.yaml"
    ).exists()
    assert (
        load_catalog(tmp_path / "novels.yaml").novel("test-novel").title
        == "Test Novel"
    )


def test_reregister_after_success_fails_with_orienting_error(
    tmp_path: Path,
) -> None:
    """Registering the same novel twice reports the existing registration."""
    registry = create_registry(tmp_path)
    use_case = RegisterNovel(registry)
    result = use_case.execute(register_request())
    with pytest.raises(ValidationError, match="already registered"):
        RegisterNovel(result.registry).execute(register_request())


def test_seed_copies_once_and_never_overwrites(tmp_path: Path) -> None:
    """Seeding copies the baked-in catalog once and keeps later edits."""
    seed = tmp_path / "seed.yaml"
    seed.write_text(CATALOG_YAML, encoding="utf-8")
    target = tmp_path / "data" / "novels.yaml"
    first = ensure_catalog_seeded(seed, target)
    assert first == target.resolve()
    assert target.read_text(encoding="utf-8") == CATALOG_YAML
    target.write_text("novels: {}\n", encoding="utf-8")
    second = ensure_catalog_seeded(seed, target)
    assert second == target.resolve()
    assert target.read_text(encoding="utf-8") == "novels: {}\n"


def test_seed_without_seed_file_leaves_target_absent(tmp_path: Path) -> None:
    """A missing seed image never creates a catalog out of thin air."""
    target = tmp_path / "data" / "novels.yaml"
    resolved = ensure_catalog_seeded(tmp_path / "missing.yaml", target)
    assert resolved == target.resolve()
    assert not target.exists()


@pytest.mark.parametrize(
    "name",
    [
        "COM1.md",
        "com1.md",
        "Com1.txt",
        "LPT9.md",
        "CON.yaml.md",
        "aux.txt",
        "NUL.md",
        "x:y.md",
        " leading.md",
        "a .md",
        "trailing. ",
        ".md",
        "a b:c.md",
        "chapter 1.md",
        "ch.md.bak",
        "../chapter-1.md",
        "sub/chapter-1.md",
        "back\\slash.md",
        "",
    ],
)
def test_validate_source_filename_rejects_reserved_and_odd_names(
    name: str,
) -> None:
    """Reserved devices, spaces, and colons never become source files."""
    with pytest.raises(ValidationError, match="Invalid source filename"):
        validate_source_filename(name)


@pytest.mark.parametrize(
    "name",
    ["chapter-1.md", "a..b.md", "A-1_B.2.txt", "1.md", "trailing-dot..md"],
)
def test_validate_source_filename_accepts_plain_names(name: str) -> None:
    """Plain names, including interior double dots, remain accepted."""
    validate_source_filename(name)


def test_concurrent_registers_leave_winner_intact_without_orphans(
    tmp_path: Path,
) -> None:
    """Two racing registrations persist exactly one bible and catalog row."""
    import threading

    registry = create_registry(tmp_path)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt() -> None:
        barrier.wait()
        try:
            RegisterNovel(registry).execute(
                register_request(source_files={"chapter-1.md": "第一章"})
            )
            outcomes.append("won")
        except ValidationError as error:
            assert "already registered" in str(error) or (
                "already exists" in str(error)
            )
            outcomes.append("lost")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["lost", "won"]
    assert (tmp_path / "novel-sources" / "new-novel").is_dir()
    assert (
        tmp_path / "config" / "new-novel.translation-bible.yaml"
    ).read_text(encoding="utf-8") == register_request().bible_text
    survivors = list((tmp_path / "config").glob("*.yaml"))
    assert [path.name for path in survivors] == [
        "new-novel.translation-bible.yaml"
    ]
    fresh = load_catalog(tmp_path / "novels.yaml")
    assert fresh.novel("new-novel").title == "New Novel"


def test_stale_registry_sees_novel_after_reload(
    tmp_path: Path,
) -> None:
    """A live registry never stays blind to a concurrent registration."""
    reader = create_registry(tmp_path)
    writer = load_catalog(tmp_path / "novels.yaml")
    RegisterNovel(writer).execute(register_request())
    assert "new-novel" not in reader.config.novels
    reader.reload()
    assert reader.novel("new-novel").title == "New Novel"
