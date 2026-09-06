When the user invokes AI-DLC, read and follow
`.aidlc/aidlc-rules/aws-aidlc-rules/core-workflow.md` to start the workflow.

Project requirements and product scope are defined in `REQUIREMENTS.md`.
Treat `REQUIREMENTS.md` as the authoritative source for product requirements:
baseline CLI v1 scope, translation/publication separation, technical
constraints, and the translation bible model.

`WEB_VERSION_PLAN.md` governs only post-v1 evolution — the web interface and
its implementation phases. It supersedes `REQUIREMENTS.md` solely on the
historical v1 exclusion of a web interface; any other conflict resolves in
favor of `REQUIREMENTS.md`. Follow `WEB_VERSION_PLAN.md` to implement new
web-era features.

**Always** be brief and use less tokens on communication.

Python code **must** pass `ruff`, `pytest` and `pyright`.
