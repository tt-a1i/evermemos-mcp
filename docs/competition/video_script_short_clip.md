# Short Clip Script (ZH/EN, 30-45 sec)

## Chinese (30-45s)
台词（三段式）：
1. “痛点：AI 会话切换后容易丢上下文。”  
2. “方案：我们用 `space_id` 做隔离，用 `request_status + recall/briefing + fetch_history/forget` 构成可核验的记忆闭环。”  
3. “结果：real-data 四项门禁全 pass，原始 runs 公开可审计。”  

画面顺序：
1. `list_spaces` + `recall/briefing`（能力，8-12s）
2. `benchmark_summary.json`（结果，12-15s）
3. evidence release + `runs.jsonl` asset（审计，8-12s）

## English (30-45s)
Narration (3 blocks):
1. "Problem: AI tools lose context across sessions."  
2. "Solution: we isolate memory by `space_id`, and use `request_status + recall/briefing + fetch_history/forget` as a verifiable memory loop."  
3. "Result: all real-data gates passed, with raw runs published for auditability."  

Shot order:
1. `list_spaces` + `recall/briefing` (capability, 8-12s)
2. `benchmark_summary.json` (metrics, 12-15s)
3. evidence release + `runs.jsonl` asset (audit, 8-12s)
