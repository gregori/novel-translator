"""Tests for the GitHub Contents API publication adapter."""

import base64
import json
from typing import Any

import httpx
import pytest

from novel_translator.application.publish import PublishOutcome
from novel_translator.domain.errors import PublicationError
from novel_translator.infrastructure.github import GitHubSitePublisher

REPOSITORY = "gregori/novels-site"
PATH = "src/content/novels/test-novel/001.md"
BRANCH = "novel-translator/test-novel-ch1-abcdef12"
CONTENT = '---\nchapterTitle: "Chapter 1"\n---\n\nBody.\n'
OTHER_CONTENT = "Stale remote body.\n"


def encode(content: str) -> str:
    """Encode file content the way the Contents API returns it."""
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


class GitHubMock:
    """Route GitHub API calls to staged responses and record requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.staged: dict[tuple[str, str], httpx.Response] = {}
        self.bodies: dict[tuple[str, str], dict[str, Any]] = {}

    def stage(
        self,
        method: str,
        path: str,
        status: int,
        payload: Any = None,
    ) -> None:
        """Stage one response for a method and path."""
        body = b"" if payload is None else json.dumps(payload).encode()
        self.staged[(method, path)] = httpx.Response(status, content=body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Serve one staged response while recording the request."""
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key in self.staged:
            return self.staged[key]
        return httpx.Response(404, content=b"{}")

    def json_body(self, method: str, path: str) -> dict[str, Any]:
        """Return the decoded JSON body sent to one endpoint."""
        for request in self.requests:
            if request.method == method and request.url.path == path:
                return json.loads(request.content.decode("utf-8"))
        raise AssertionError(f"No request recorded for {method} {path}")


def publisher(
    mock: GitHubMock, token: str = "secret-token"
) -> GitHubSitePublisher:
    """Build a publisher whose transport is fully mocked."""
    transport = httpx.MockTransport(mock.handler)
    return GitHubSitePublisher(token, transport=transport)


def stage_base(mock: GitHubMock, *, remote_content: str | None = None) -> None:
    """Stage repository, branch head, and optional base file reads."""
    mock.stage("GET", f"/repos/{REPOSITORY}", 200, {"default_branch": "main"})
    mock.stage(
        "GET",
        f"/repos/{REPOSITORY}/branches/main",
        200,
        {"commit": {"sha": "base-sha"}},
    )
    if remote_content is None:
        mock.stage("GET", f"/repos/{REPOSITORY}/contents/{PATH}", 404)
    else:
        mock.stage(
            "GET",
            f"/repos/{REPOSITORY}/contents/{PATH}",
            200,
            {
                "type": "file",
                "content": encode(remote_content),
                "sha": "file-sha",
            },
        )


def test_publish_creates_branch_file_and_pull_request() -> None:
    """The happy path creates a branch, writes content, and opens a PR."""
    mock = GitHubMock()
    stage_base(mock)
    mock.stage("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}", 404)
    mock.stage("POST", f"/repos/{REPOSITORY}/git/refs", 201, {})
    mock.stage(
        "PUT",
        f"/repos/{REPOSITORY}/contents/{PATH}",
        201,
        {"commit": {"sha": "commit-sha"}},
    )
    mock.stage(
        "POST",
        f"/repos/{REPOSITORY}/pulls",
        201,
        {"html_url": "https://github.com/gregori/novels-site/pull/7"},
    )

    outcome = publisher(mock).publish(
        repository=REPOSITORY,
        path=PATH,
        content=CONTENT,
        branch=BRANCH,
        title="Publish test-novel chapter 1",
        body="Approved revision.",
    )

    assert outcome == PublishOutcome(
        git_commit="commit-sha",
        pull_request_url="https://github.com/gregori/novels-site/pull/7",
        branch=BRANCH,
        created=True,
    )
    ref_body = mock.json_body("POST", f"/repos/{REPOSITORY}/git/refs")
    assert ref_body["ref"] == f"refs/heads/{BRANCH}"
    assert ref_body["sha"] == "base-sha"
    put_body = mock.json_body("PUT", f"/repos/{REPOSITORY}/contents/{PATH}")
    assert base64.b64decode(put_body["content"]).decode("utf-8") == CONTENT
    assert put_body["branch"] == BRANCH
    assert mock.requests[0].headers["authorization"] == "Bearer secret-token"


def test_publish_short_circuits_when_base_matches() -> None:
    """Identical base content needs no branch, write, or pull request."""
    mock = GitHubMock()
    stage_base(mock, remote_content=CONTENT)

    outcome = publisher(mock).publish(
        repository=REPOSITORY,
        path=PATH,
        content=CONTENT,
        branch=BRANCH,
        title="Publish test-novel chapter 1",
        body="Approved revision.",
    )

    assert outcome.created is False
    assert outcome.pull_request_url is None
    assert outcome.git_commit == "base-sha"
    methods = [(request.method, request.url.path) for request in mock.requests]
    assert ("PUT", f"/repos/{REPOSITORY}/contents/{PATH}") not in methods
    assert ("POST", f"/repos/{REPOSITORY}/pulls") not in methods


def test_publish_reuses_open_pull_request_for_existing_branch() -> None:
    """A duplicate PR open is reused instead of failing the publish."""
    mock = GitHubMock()
    stage_base(mock, remote_content=OTHER_CONTENT)
    mock.stage("GET", f"/repos/{REPOSITORY}/git/ref/heads/{BRANCH}", 200, {})
    mock.stage(
        "PUT",
        f"/repos/{REPOSITORY}/contents/{PATH}",
        201,
        {"commit": {"sha": "commit-sha-2"}},
    )
    mock.stage("POST", f"/repos/{REPOSITORY}/pulls", 422, {})
    mock.stage(
        "GET",
        f"/repos/{REPOSITORY}/pulls",
        200,
        [{"html_url": "https://github.com/gregori/novels-site/pull/3"}],
    )

    outcome = publisher(mock).publish(
        repository=REPOSITORY,
        path=PATH,
        content=CONTENT,
        branch=BRANCH,
        title="Publish test-novel chapter 1",
        body="Approved revision.",
    )

    assert outcome.git_commit == "commit-sha-2"
    assert outcome.pull_request_url == (
        "https://github.com/gregori/novels-site/pull/3"
    )
    assert outcome.created is True


def test_publish_rejects_malformed_repository_without_requests() -> None:
    """Identifiers outside the owner/name shape fail before any call."""
    mock = GitHubMock()

    with pytest.raises(PublicationError):
        publisher(mock).publish(
            repository="not-a-repo",
            path=PATH,
            content=CONTENT,
            branch=BRANCH,
            title="Publish test-novel chapter 1",
            body="Approved revision.",
        )

    assert mock.requests == []


def test_publish_surfaces_upstream_failures() -> None:
    """A GitHub outage becomes a typed publication error."""
    mock = GitHubMock()
    mock.stage("GET", f"/repos/{REPOSITORY}", 500)

    with pytest.raises(PublicationError):
        publisher(mock).publish(
            repository=REPOSITORY,
            path=PATH,
            content=CONTENT,
            branch=BRANCH,
            title="Publish test-novel chapter 1",
            body="Approved revision.",
        )


def test_transport_failure_becomes_publication_error() -> None:
    """A dead connection surfaces as a typed error, never a traceback."""

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(boom)
    with pytest.raises(PublicationError):
        GitHubSitePublisher("token", transport=transport).publish(
            repository=REPOSITORY,
            path=PATH,
            content=CONTENT,
            branch=BRANCH,
            title="Publish test-novel chapter 1",
            body="Approved revision.",
        )


def test_read_returns_decoded_base_content() -> None:
    """Reads decode the live site file for date pinning."""
    mock = GitHubMock()
    mock.stage("GET", f"/repos/{REPOSITORY}", 200, {"default_branch": "main"})
    mock.stage(
        "GET",
        f"/repos/{REPOSITORY}/contents/{PATH}",
        200,
        {"type": "file", "content": encode(CONTENT), "sha": "file-sha"},
    )
    assert publisher(mock).read(repository=REPOSITORY, path=PATH) == CONTENT


def test_read_returns_none_for_missing_file() -> None:
    """Reads report absence without failing the publication."""
    mock = GitHubMock()
    mock.stage("GET", f"/repos/{REPOSITORY}", 200, {"default_branch": "main"})
    mock.stage("GET", f"/repos/{REPOSITORY}/contents/{PATH}", 404)
    assert publisher(mock).read(repository=REPOSITORY, path=PATH) is None
