"""Translation orchestration use case."""

from __future__ import annotations

import uuid
from asyncio import CancelledError
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from novel_translator.domain.errors import (
    TransientProviderError,
    ValidationError,
)
from novel_translator.domain.models import (
    ChapterIdentity,
    PromptCall,
    RunCompletion,
    RunPhase,
    RunRecord,
    RunStatus,
    SegmentPromptManifest,
)
from novel_translator.domain.translation import (
    DEFAULT_SEGMENT_LIMIT,
    PREVIOUS_TRANSLATION_CONTEXT_CHARS,
    PROMPT_TEMPLATE,
    PROMPT_TEMPLATE_VERSION,
    RUN_SCHEMA_VERSION,
    SourceDocument,
    TranslationBible,
    TranslatorGateway,
    build_context,
    estimate_tokens,
    extract_draft_title,
    prompt_manifest_hash,
    render_translation_prompt,
    segment_text,
)
from novel_translator.infrastructure.workspace import Workspace
from novel_translator.shared.utils import sha256_text


@dataclass(frozen=True, slots=True)
class StartTranslationInput:
    """Typed input for a complete translation run."""

    identity: ChapterIdentity
    source: SourceDocument
    bible: TranslationBible
    provider: str
    model: str
    volume: int | None = None
    segment_limit: int = DEFAULT_SEGMENT_LIMIT
    progress: Callable[[int, int, int], None] | None = None
    retry_notice: (
        Callable[[int, int, int, TransientProviderError], None] | None
    ) = None


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Identity of a persisted translation run."""

    run_id: str


class StartTranslation:
    """Coordinate and persist one complete translation run."""

    def __init__(
        self, workspace: Workspace, gateway: TranslatorGateway
    ) -> None:
        self._workspace = workspace
        self._gateway = gateway

    def execute(self, request: StartTranslationInput) -> TranslationResult:
        """Execute one translation from validated input."""
        context = build_context(request.bible)
        run_id = uuid.uuid4().hex
        started_at = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            identity=request.identity,
            source_hash=sha256_text(request.source.content),
            provider=request.provider,
            model=request.model,
            schema_version=RUN_SCHEMA_VERSION,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            prompt_hash=prompt_manifest_hash([]),
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_template_hash=sha256_text(PROMPT_TEMPLATE),
            context_hash=sha256_text(context),
            segment_manifest=[],
            bible_hash=sha256_text(request.bible.model_dump_json()),
            timestamp=started_at,
            status=RunStatus.STARTED,
            bible_version=request.bible.version,
            volume=request.volume,
            source_title=request.source.extracted_title,
        )
        self._workspace.runs.create_run(record, request.source, request.bible)
        phase = RunPhase.TRANSLATION
        current_segment: int | None = None
        current_attempt: int | None = None
        try:
            segments = segment_text(
                request.source.content, request.segment_limit
            )
            translations: list[str] = []
            previous_translation = ""
            for index, segment in enumerate(segments, start=1):
                current_segment = index
                current_attempt = None
                continuity_context = ""
                if previous_translation:
                    tail = previous_translation[
                        -PREVIOUS_TRANSLATION_CONTEXT_CHARS:
                    ]
                    continuity_context = (
                        "\n\nPrevious translated passage for "
                        "continuity only; do not repeat it:\n"
                        f"{tail}"
                    )
                prompt = render_translation_prompt(
                    context, continuity_context, index, segment
                )
                rendered_prompt_hash = sha256_text(prompt)
                self._workspace.runs.record_prompt_segment(
                    run_id,
                    SegmentPromptManifest(
                        segment_index=index,
                        source_segment_hash=sha256_text(segment),
                        continuity_context_hash=sha256_text(
                            continuity_context
                        ),
                        rendered_prompt_hash=rendered_prompt_hash,
                        gateway_calls=[],
                    ),
                )
                for attempt in range(1, 4):
                    current_attempt = attempt
                    if request.progress is not None:
                        request.progress(index, len(segments), attempt)
                    try:
                        self._workspace.runs.record_prompt_call(
                            run_id,
                            index,
                            PromptCall(attempt, rendered_prompt_hash),
                        )
                        translation = self._gateway.translate(prompt)
                        translations.append(translation)
                        previous_translation = translation
                        break
                    except TransientProviderError as error:
                        if request.retry_notice is not None:
                            request.retry_notice(
                                index, len(segments), attempt, error
                            )
                else:
                    raise ValidationError(
                        "Translation failed after three attempts."
                    )
            draft = "".join(translations)
            phase = RunPhase.DRAFT_PERSISTENCE
            current_segment = None
            current_attempt = None
            self._workspace.runs.save_draft(run_id, draft)
            phase = RunPhase.FINALIZATION
            completed_at = datetime.now(UTC)
            self._workspace.runs.complete_run(
                run_id,
                completed_at,
                RunCompletion(
                    duration_seconds=(
                        completed_at - started_at
                    ).total_seconds(),
                    source_characters=len(request.source.content),
                    draft_characters=len(draft),
                    source_tokens=estimate_tokens(
                        request.source.content, request.bible.source_language
                    ),
                    draft_tokens=estimate_tokens(
                        draft, request.bible.target_language
                    ),
                    draft_title=extract_draft_title(
                        draft, request.identity.chapter
                    ),
                ),
            )
        except (KeyboardInterrupt, CancelledError) as error:
            self._record_termination(
                run_id,
                RunStatus.INTERRUPTED,
                error,
                phase,
                current_segment,
                current_attempt,
            )
            raise
        except Exception as error:
            self._record_termination(
                run_id,
                RunStatus.FAILED,
                error,
                phase,
                current_segment,
                current_attempt,
            )
            raise
        return TranslationResult(run_id)

    def _record_termination(
        self,
        run_id: str,
        status: RunStatus,
        error: BaseException,
        phase: RunPhase,
        segment: int | None,
        attempt: int | None,
    ) -> None:
        """Best-effort terminal recording that preserves the original error."""
        try:
            self._workspace.runs.terminate_run(
                run_id,
                status,
                error,
                phase,
                segment,
                attempt,
                datetime.now(UTC),
            )
        except Exception as lifecycle_error:
            error.add_note(
                "Could not persist terminal run state: "
                f"{type(lifecycle_error).__name__}"
            )
