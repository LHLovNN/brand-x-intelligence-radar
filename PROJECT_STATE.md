# Project State

## Objective

Maintain a reliable Chinese-first intelligence station with two product areas:

- `谛听-情报库`: Xiaohongshu platform-change research plus AI and Telegram daily digests.
- `品牌-舆情监控`: prioritized, complete and daily views of public brand discussion.

## Current Status

- The default route is `小红书`; `舆情焦点` has its own `#/overview` route.
- Page, date, conversation-context and Telegram-comment data are loaded on demand.
- Historical conversation contexts and Telegram replies have been migrated to separate JSON files.
- Content filtering is centralized across brand posts, X conversation context, Xiaohongshu items, Telegram entries and Telegram comments.
- Xiaohongshu relevance includes growth, monetization, risk control, account acquisition, platform rules, account matrices, reverse engineering and device modification.
- Semantic review uses stable reason codes and bounded input size; deterministic rules remain the fallback.
- Xiaohongshu candidates that pass the metric gate but are not finally collected are retained in a private local audit for seven calendar days, with rule/model rejection reasons; audit files are never published or committed.
- Data loads retry automatically and expose an explicit retry state after repeated failure.
- Daily publishers use module-specific commits, a shared publication lock, publish-only retry and post-publication date verification.
- Browser QA is required in CI and cannot silently skip.

## Daily Timeline

- `08:00`: brand and Xiaohongshu collection, generation, validation and publication.
- `08:30`: AI and Telegram digest synchronization, validation and publication.
- `08:45`: read-only update audit and user notification; it must not consume source or model quota.

## Operational Boundaries

- Generated module data can be resumed without treating its own lazy payloads as source-code changes.
- The two publishers may overlap in generation, but shared publication is serialized.
- A failed push retries only synchronization, asset rebuild and publication; collection is not repeated.
- The published date is polled after push so a successful Git command is not mistaken for a completed Pages update.

## Next

- Observe several scheduled runs for upstream freshness, recovery behavior and notification quality.
- Continue case-based content-policy tuning without weakening relevance requirements.
- Reassess media hosting separately if upstream static-file throughput remains a bottleneck.
