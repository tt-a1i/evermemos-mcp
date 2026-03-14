# Release Checklist (Competition v0.5.6)

## 1) Goal
Ship a stable competition release (`v0.5.6`) and ensure all submission assets are complete and verifiable.

## 2) Release Gate (Must Pass Before Tag)

### 2.1 Repository Hygiene
- [ ] Working tree is clean (`git status`)
- [ ] Branch is synced with `origin/main`
- [ ] No unreviewed local-only files in submission-critical paths
- [ ] Final release commit SHA recorded in submission notes

### 2.2 Quality Gates
- [x] Lint passes
- [x] Tests pass
- [x] 3-minute quickstart smoke test passes

Current status:
- Cloud auth is working again with the refreshed project key.
- `scripts/demo_preload.py --check-status` now completes and all three demo spaces become recallable in the non-prefix smoke path.
- `scripts/demo_live_walkthrough.py` now completes the standard list/recall/briefing smoke path on the non-prefix demo spaces.
- `scripts/demo_live_walkthrough.py --do-forget` now completes the live walkthrough path and falls back to `fetch_history` when recall shows only profile rows, but the forget step still returns `deleted_count=0` on current Cloud.
- `scripts/competition_lifecycle_appendix.py` now defaults to `--timeout 240 --interval 10`; the latest live artifact `artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/` reached `3/3` searchable spaces and `PASS` isolation.

```bash
uv run ruff check
uv run pytest -q
uv run python scripts/demo_live_walkthrough.py
```

### 2.3 Competition Docs Gates
- [x] `docs/06-benchmark.md` complete
- [x] `docs/07-release-checklist.md` complete
- [x] `docs/competition/submission_draft.md` has filled Problem/Solution/Demo Flow
- [x] Benchmark artifacts generated under `artifacts/competition/{date}-<run-label>/`

## 3) Versioning and Changelog
- [x] Update `pyproject.toml` version to `0.5.0`
- [x] Create/update `CHANGELOG.md` with key highlights:
  - tool description tightening for `list_spaces`, `recall`, `briefing`, and `forget`
  - clearer `remember.space_id` default-space guidance
  - release-facing docs and pinned examples updated to `0.5.0`

## 4) Tag and Push

```bash
git add .
git commit -m "release: prepare v0.5.6 competition package"
git tag v0.5.6
git push origin main
git push origin v0.5.6
```

## 5) GitHub Release
- [x] Create GitHub release for `v0.5.6`
- [x] Attach changelog summary
- [x] Include benchmark artifact links (or report snapshots)
- [x] Verify release page is publicly accessible

Recommended command:

```bash
gh release create v0.5.6 --title "v0.5.6" --notes-file CHANGELOG.md
```

## 6) Submission Asset Checklist
- [x] Repository URL verified
- [x] Release/tag URL verified
- [ ] Demo video uploaded and playable
- [ ] Short clip uploaded
- [ ] Community wave links collected
- [x] Submission form fields prepared in final draft

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
