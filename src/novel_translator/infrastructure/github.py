"""GitHub Contents API publisher for novels-site pull requests."""

from __future__ import annotations

import base64
from typing import cast

import httpx

from novel_translator.application.publish import PublishOutcome
from novel_translator.domain.errors import PublicationError


class GitHubSitePublisher:
    """Open publication pull requests without a local site checkout."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def publish(
        self,
        *,
        repository: str,
        path: str,
        content: str,
        branch: str,
        title: str,
        body: str,
    ) -> PublishOutcome:
        """Create or reuse one branch and pull request for rendered content."""
        owner = _owner_of(repository)
        try:
            with httpx.Client(
                base_url=self._base_url,
                headers=_headers(self._token),
                timeout=self._timeout,
                transport=self._transport,
            ) as session:
                return self._run(
                    session,
                    owner,
                    repository,
                    path,
                    content,
                    branch,
                    title,
                    body,
                )
        except httpx.HTTPError as error:
            raise PublicationError(
                f"GitHub request failed ({type(error).__name__})."
            ) from error

    def read(self, *, repository: str, path: str) -> str | None:
        """Return the base branch file content, if it exists."""
        _owner_of(repository)
        try:
            with httpx.Client(
                base_url=self._base_url,
                headers=_headers(self._token),
                timeout=self._timeout,
                transport=self._transport,
            ) as session:
                base = self._default_branch(session, repository)
                return self._file_content(session, repository, path, base)
        except httpx.HTTPError as error:
            raise PublicationError(
                f"GitHub request failed ({type(error).__name__})."
            ) from error

    def _run(
        self,
        session: httpx.Client,
        owner: str,
        repository: str,
        path: str,
        content: str,
        branch: str,
        title: str,
        body: str,
    ) -> PublishOutcome:
        """Execute the branch, contents, and pull request sequence."""
        base = self._default_branch(session, repository)
        base_sha = self._branch_head(session, repository, base)
        if self._base_matches(session, repository, path, base, content):
            return PublishOutcome(
                git_commit=base_sha,
                pull_request_url=None,
                branch=branch,
                created=False,
            )
        self._ensure_branch(session, repository, branch, base_sha)
        commit = self._put_contents(
            session, repository, path, content, branch, title
        )
        pr_url = self._ensure_pull_request(
            session, repository, owner, branch, base, title, body
        )
        return PublishOutcome(
            git_commit=commit,
            pull_request_url=pr_url,
            branch=branch,
            created=True,
        )

    def _default_branch(self, session: httpx.Client, repository: str) -> str:
        """Read the repository default branch for one PR base."""
        response = session.get(f"/repos/{repository}")
        if response.status_code != 200:
            raise PublicationError(
                f"GitHub could not read repository {repository} "
                f"({response.status_code})."
            )
        payload = _json_object(response, what="repository")
        branch = payload.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise PublicationError(
                f"GitHub returned no default branch for {repository}."
            )
        return branch

    def _branch_head(
        self, session: httpx.Client, repository: str, branch: str
    ) -> str:
        """Resolve one branch head commit sha."""
        response = session.get(f"/repos/{repository}/branches/{branch}")
        if response.status_code != 200:
            raise PublicationError(
                f"GitHub could not read branch {branch} "
                f"({response.status_code})."
            )
        payload = _json_object(response, what="branch")
        holder = payload.get("commit")
        if not isinstance(holder, dict):
            raise PublicationError(
                f"GitHub returned no head commit for {branch}."
            )
        nested = cast(dict[str, object], holder)
        commit = nested.get("sha")
        if not isinstance(commit, str) or not commit:
            raise PublicationError(
                f"GitHub returned no head commit for {branch}."
            )
        return commit

    def _base_matches(
        self,
        session: httpx.Client,
        repository: str,
        path: str,
        base: str,
        content: str,
    ) -> bool:
        """Report whether the base branch already carries exact content."""
        return self._file_content(session, repository, path, base) == content

    def _file_content(
        self,
        session: httpx.Client,
        repository: str,
        path: str,
        ref: str,
    ) -> str | None:
        """Decode one branch file, returning None when it does not exist."""
        response = session.get(
            f"/repos/{repository}/contents/{path}", params={"ref": ref}
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PublicationError(
                f"GitHub could not read {path} ({response.status_code})."
            )
        payload = _json_object(response, what="file")
        if payload.get("type") != "file":
            raise PublicationError(f"GitHub path is not a file: {path}.")
        encoded = payload.get("content", "")
        if not isinstance(encoded, str):
            raise PublicationError(
                f"GitHub returned unreadable content for {path}."
            )
        try:
            return base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeError) as error:
            raise PublicationError(
                f"GitHub returned unreadable content for {path}."
            ) from error

    def _ensure_branch(
        self,
        session: httpx.Client,
        repository: str,
        branch: str,
        base_sha: str,
    ) -> None:
        """Create one publication branch from base unless it already exists."""
        existing = session.get(f"/repos/{repository}/git/ref/heads/{branch}")
        if existing.status_code == 200:
            return
        if existing.status_code != 404:
            raise PublicationError(
                f"GitHub could not read branch {branch} "
                f"({existing.status_code})."
            )
        created = session.post(
            f"/repos/{repository}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if created.status_code not in (200, 201, 422):
            raise PublicationError(
                f"GitHub could not create branch {branch} "
                f"({created.status_code})."
            )

    def _put_contents(
        self,
        session: httpx.Client,
        repository: str,
        path: str,
        content: str,
        branch: str,
        message: str,
    ) -> str:
        """Write rendered content on the branch, retrying one sha race."""
        response = self._write_contents(
            session, repository, path, content, branch, message
        )
        if response.status_code in (200, 201):
            return self._commit_of(response, path)
        if response.status_code not in (409, 422):
            raise PublicationError(
                f"GitHub could not write {path} ({response.status_code})."
            )
        retry = self._write_contents(
            session, repository, path, content, branch, message
        )
        if retry.status_code in (200, 201):
            return self._commit_of(retry, path)
        raise PublicationError(
            f"GitHub could not write {path} ({retry.status_code})."
        )

    def _write_contents(
        self,
        session: httpx.Client,
        repository: str,
        path: str,
        content: str,
        branch: str,
        message: str,
    ) -> httpx.Response:
        """Write rendered content with the current branch blob sha."""
        payload: dict[str, object] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode("ascii"),
            "branch": branch,
        }
        sha = self._blob_sha(session, repository, path, branch)
        if sha is not None:
            payload["sha"] = sha
        return session.put(
            f"/repos/{repository}/contents/{path}", json=payload
        )

    def _commit_of(self, response: httpx.Response, path: str) -> str:
        """Extract one commit sha from a successful contents write."""
        payload = _json_object(response, what="commit")
        holder = payload.get("commit")
        if not isinstance(holder, dict):
            raise PublicationError(f"GitHub returned no commit for {path}.")
        commit = cast(dict[str, object], holder).get("sha")
        if not isinstance(commit, str) or not commit:
            raise PublicationError(f"GitHub returned no commit for {path}.")
        return commit

    def _blob_sha(
        self,
        session: httpx.Client,
        repository: str,
        path: str,
        branch: str,
    ) -> str | None:
        """Return the current blob sha on the branch, if the file exists."""
        response = session.get(
            f"/repos/{repository}/contents/{path}", params={"ref": branch}
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PublicationError(
                f"GitHub could not read {path} ({response.status_code})."
            )
        sha = _json_object(response, what="file").get("sha")
        return sha if isinstance(sha, str) else None

    def _ensure_pull_request(
        self,
        session: httpx.Client,
        repository: str,
        owner: str,
        branch: str,
        base: str,
        title: str,
        body: str,
    ) -> str:
        """Open one pull request, reusing the open one for the same branch."""
        opened = session.post(
            f"/repos/{repository}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        if opened.status_code == 201:
            url = _json_object(opened, what="pull request").get("html_url")
            if isinstance(url, str) and url:
                return url
            raise PublicationError("GitHub returned no pull request URL.")
        if opened.status_code != 422:
            raise PublicationError(
                f"GitHub could not open a pull request ({opened.status_code})."
            )
        listed = session.get(
            f"/repos/{repository}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open"},
        )
        if listed.status_code != 200:
            raise PublicationError(
                f"GitHub could not list pull requests ({listed.status_code})."
            )
        raw_pulls: object = listed.json()
        if not isinstance(raw_pulls, list):
            raise PublicationError("GitHub returned an unreadable pull list.")
        for pull in cast(list[object], raw_pulls):
            if isinstance(pull, dict):
                url = cast(dict[str, object], pull).get("html_url")
                if isinstance(url, str) and url:
                    return url
        raise PublicationError(
            f"GitHub has no open pull request for {branch}."
        )


def _json_object(response: httpx.Response, *, what: str) -> dict[str, object]:
    """Decode one JSON object payload or fail as a publication error."""
    data: object = response.json()
    if not isinstance(data, dict):
        raise PublicationError(f"GitHub returned an unreadable {what}.")
    return cast(dict[str, object], data)


def _owner_of(repository: str) -> str:
    """Split the repository owner from one owner/name identifier."""
    owner, separator, name = repository.partition("/")
    if not separator or not owner or not name or "/" in name:
        raise PublicationError(
            f"Repository must use the owner/name shape: {repository}."
        )
    return owner


def _headers(token: str) -> dict[str, str]:
    """Build authenticated JSON headers without exposing the token."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
