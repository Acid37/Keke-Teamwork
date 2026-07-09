## Summary

- Add a backend-only parallel researcher orchestration slice.
- Keep delegated researcher execution read-only.
- Add unit coverage for concurrent execution and per-worker timeout handling.

## Testing

- [ ] `python -m unittest -v`

## Safety

- Research workers use read/search/list tools only.
- No automatic file writes, edits, or console execution are enabled in this slice.

## Notes

- Merge synthesis and UI integration are intentionally left for a follow-up change.
