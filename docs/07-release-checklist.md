# Release Checklist (Competition v0.4.0)

## 1) Goal
Ship a stable competition release (`v0.4.0`) and ensure all submission assets are complete and verifiable.

## 2) Release Gate (Must Pass Before Tag)

### 2.1 Repository Hygiene
- [ ] Working tree is clean (`git status`)
- [ ] Branch is synced with `origin/main`
- [ ] No unreviewed local-only files in submission-critical paths
- [ ] Final release commit SHA recorded in submission notes

### 2.2 Quality Gates
- [ ] Lint passes
- [ ] Tests pass
- [ ] 3-minute quickstart smoke test passes

```bash
uv run ruff check
uv run pytest -q
uv run python scripts/demo_live_walkthrough.py
```

### 2.3 Competition Docs Gates
- [ ] `docs/06-benchmark.md` complete
- [ ] `docs/07-release-checklist.md` complete
- [ ] `docs/competition/submission_draft.md` has filled Problem/Solution/Demo Flow
- [ ] Benchmark artifacts generated under `artifacts/competition/{date}/`

## 3) Versioning and Changelog
- [ ] Update `pyproject.toml` version to `0.4.0`
- [ ] Create/update `CHANGELOG.md` with key highlights:
  - source recovery hardening
  - recall/briefing reliability improvements
  - competition demo and benchmark assets

## 4) Tag and Push

```bash
git add .
git commit -m "release: prepare v0.4.0 competition package"
git tag v0.4.0
git push origin main
git push origin v0.4.0
```

## 5) GitHub Release
- [ ] Create GitHub release for `v0.4.0`
- [ ] Attach changelog summary
- [ ] Include benchmark artifact links (or report snapshots)
- [ ] Verify release page is publicly accessible

Recommended command:

```bash
gh release create v0.4.0 --title "v0.4.0" --notes-file CHANGELOG.md
```

## 6) Submission Asset Checklist
- [ ] Repository URL verified
- [ ] Release/tag URL verified
- [ ] Demo video uploaded and playable
- [ ] Short clip uploaded
- [ ] Community wave links collected
- [ ] Submission form fields prepared in final draft

## 7) Community Evidence Checklist
- [ ] Wave 1 launch post URL logged
- [ ] Wave 2 technical post URL logged
- [ ] Wave 3 short demo URL logged
- [ ] Metrics snapshot recorded:
  - stars delta
  - demo feedback count
  - Discord meaningful interactions

## 8) Final 72-Hour Freeze Policy
For `2026-03-13` to `2026-03-15`:
- [ ] Bug fixes only
- [ ] No new features
- [ ] No API-contract changes
- [ ] Re-run full quality gates after each fix

## 9) Sign-off
- [ ] Maintainer sign-off
- [ ] Benchmark evidence sign-off
- [ ] Submission packet sign-off
