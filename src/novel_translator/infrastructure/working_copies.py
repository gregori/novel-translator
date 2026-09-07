"""SQLite repository for mutable editorial working copies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError as SqlalchemyIntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from novel_translator.domain.errors import IntegrityError, WorkingCopyConflict
from novel_translator.domain.models import ArtifactKind, WorkingCopy
from novel_translator.infrastructure.database import Database


class Base(DeclarativeBase):
    """Declarative base for the SQLite persistence schema."""


class WorkingCopyRow(Base):
    """One active editing session row for exactly one run."""

    __tablename__ = "working_copies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True)
    base_artifact_kind: Mapped[str] = mapped_column(String(32))
    base_artifact_id: Mapped[str | None] = mapped_column(String(32))
    base_content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column()
    created_at: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(64))


class SqlAlchemyWorkingCopyRepository:
    """Persist working copies with optimistic version control."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_by_id(self, working_copy_id: str) -> WorkingCopy | None:
        """Return the working copy with the given identifier."""
        with self._database.session() as session:
            row = session.scalar(
                select(WorkingCopyRow).where(
                    WorkingCopyRow.id == working_copy_id
                )
            )
            return None if row is None else self._to_working_copy(row)

    def get_by_run(self, run_id: str) -> WorkingCopy | None:
        """Return the single active working copy for a run."""
        with self._database.session() as session:
            row = session.scalar(
                select(WorkingCopyRow).where(WorkingCopyRow.run_id == run_id)
            )
            return None if row is None else self._to_working_copy(row)

    def insert(self, working_copy: WorkingCopy) -> None:
        """Persist a new working copy; one active copy per run."""
        row = WorkingCopyRow(
            id=working_copy.id,
            run_id=working_copy.run_id,
            base_artifact_kind=working_copy.base_artifact_kind.value,
            base_artifact_id=working_copy.base_artifact_id,
            base_content_hash=working_copy.base_content_hash,
            content=working_copy.content,
            version=working_copy.version,
            created_at=working_copy.created_at,
            updated_at=working_copy.updated_at,
        )
        with self._database.session() as session:
            session.add(row)
            try:
                session.commit()
            except SqlalchemyIntegrityError as error:
                raise IntegrityError(
                    "A working copy already exists for this run."
                ) from error

    def update_content(
        self, working_copy_id: str, expected_version: int, content: str
    ) -> WorkingCopy:
        """Atomically save content for one expected version."""
        statement = (
            update(WorkingCopyRow)
            .where(
                WorkingCopyRow.id == working_copy_id,
                WorkingCopyRow.version == expected_version,
            )
            .values(
                content=content,
                version=expected_version + 1,
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        with self._database.session() as session:
            result = cast(CursorResult[Any], session.execute(statement))
            changed = result.rowcount
            if changed == 1:
                session.commit()
                row = session.get(WorkingCopyRow, working_copy_id)
                if row is None:
                    raise IntegrityError(
                        "Working copy disappeared after a successful save."
                    )
                return self._to_working_copy(row)
            row = session.get(WorkingCopyRow, working_copy_id)
            if row is None:
                raise IntegrityError(
                    "Working copy no longer exists for this run."
                )
            raise WorkingCopyConflict(
                current_content=row.content,
                current_version=row.version,
                submitted_content=content,
                submitted_version=expected_version,
            )

    def delete(self, working_copy_id: str) -> None:
        """Remove only the working copy; all artifacts stay untouched."""
        with self._database.session() as session:
            row = session.get(WorkingCopyRow, working_copy_id)
            if row is None:
                return
            session.delete(row)
            session.commit()

    def active_run_ids(self) -> frozenset[str]:
        """Return the run identifiers that currently hold a copy."""
        with self._database.session() as session:
            rows = session.scalars(select(WorkingCopyRow.run_id))
            return frozenset(rows)

    def _to_working_copy(self, row: WorkingCopyRow) -> WorkingCopy:
        """Convert one row into its typed domain value."""
        try:
            kind = ArtifactKind(row.base_artifact_kind)
        except ValueError as error:
            raise IntegrityError(
                "Working copy base artifact kind is invalid."
            ) from error
        return WorkingCopy(
            id=row.id,
            run_id=row.run_id,
            base_artifact_kind=kind,
            base_artifact_id=row.base_artifact_id,
            base_content_hash=row.base_content_hash,
            content=row.content,
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
