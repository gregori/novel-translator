"""HTTP route aggregation for the reading and review room."""

from fastapi import APIRouter

from novel_translator.web.routes.actions import router as actions_router
from novel_translator.web.routes.catalog import router as catalog_router
from novel_translator.web.routes.chapter import router as chapter_router
from novel_translator.web.routes.support import wants_partial
from novel_translator.web.routes.working_copy import (
    router as working_copy_router,
)

router = APIRouter()
router.include_router(catalog_router)
router.include_router(chapter_router)
router.include_router(working_copy_router)
router.include_router(actions_router)

__all__ = ["router", "wants_partial"]
