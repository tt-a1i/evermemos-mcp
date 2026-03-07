# Lifecycle Appendix Notes

- Generated at: 2026-03-07T11:28:10.870186+08:00
- Artifact dir: `artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e`
- Prefix: `appendix-dec0612e`

| Check | Definition | Sample size | Result | Status |
| --- | --- | --- | --- | --- |
| Remember success rate | successful remember acknowledgements / total remember calls | `9` | `9/9` (100.00%) | `PASS` |
| Time-to-searchable P50/P95 | time from first remember ack in each demo space to first recall hit | `3` | `P50=69.07s, P95=69.07s` | `PASS` |
| Space isolation correctness | cross-space false hits / cross-space queries | `6` | `0/6` | `PASS` |
| Forget effectiveness | deleted item still recalled / delete attempts | `1` | `1/1` | `WARN` |

## Per-space searchable latency

- `coding:appendix-dec0612e-app`: `69.07s`
- `chat:appendix-dec0612e-daily`: `37.82s`
- `study:appendix-dec0612e-ml-notes`: `91.48s`

## Notes

- This appendix is supplemental evidence and does not change the primary benchmark gates.
- Raw execution logs are stored in `raw_logs.txt` alongside this file.
