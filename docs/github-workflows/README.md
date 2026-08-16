# GitHub Actions workflows (moved out of .github/workflows)

These three workflows (backend, content-pipeline, frontend) were authored as
part of the AI MCQ engine, but the repository's automation token does not have
the `workflows` permission, so GitHub rejects pushes that create
`.github/workflows/*` files.

To enable CI, copy these files back into `.github/workflows/` using an
account/token with the `workflows` permission.
