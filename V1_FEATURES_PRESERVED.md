# V1 features preserved

The original Calling Campaign App V1 described these core behaviors:
- Add contacts manually
- Import Name,Phone CSV
- Search and status filters
- Tap CALL to open Android phone dialer
- Track attempts
- Mark Completed / Call again / Not reachable
- Add notes
- Export results to CSV
- Clear local data in the original prototype

The cloud version preserves the calling, importing, searching/filtering, attempts, statuses, notes and export workflow while moving shared data to a server database. It does not silently auto-dial; the CALL action hands the number to the device dialer.
