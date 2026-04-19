The user is wrapping up this session. Work through the following, in order:

1. **Loose ends check** — scan the conversation for anything mentioned but not completed: unfinished tasks, "we'll do that later", known issues, or things that were promised but not delivered.

2. **Doc sync** — run `git diff HEAD` and `git status` in /opt/docs. If peachhouse-server-docs.md has uncommitted changes or anything was changed on the system this session that isn't reflected in the doc, update and commit now.

3. **Backup sync** — check whether any new scripts were added to /usr/local/bin/ or any new service config extras were created that aren't covered by backup-config's automatic scope (compose files and /usr/local/bin/ are automatic; service-specific config dirs need explicit lines). If so, update backup-config and re-run it.

4. **Memory** — review what was learned or decided this session. Update or create memory files for anything worth carrying forward: user preferences, project decisions, new system facts, feedback on your behaviour. Remove or update anything stale.

5. **Report** — give a concise summary: what was done, any loose ends left open (with a reason), and anything the user should be aware of before closing.

Keep the report tight. Don't pad it.
