# Contributing

Keep changes focused and describe the user-visible behavior they improve. Preserve format validation, unrelated fields, verified backups, stale-file checks, and restoration behavior.

Run the portable tests listed in `docs/DEVELOPMENT.md`. Game-data integration tests need local fixtures; say which tests you ran and which you could not run. For visual or gameplay changes, distinguish offline checks from a fresh game boot and normal save load.

Please include the tool/version, supported game ID/revision, steps to reproduce, expected behavior, and actual behavior in a bug report. Report unsupported inputs without attaching the game itself.

Do not submit game ISOs, decrypted executables, extracted fonts/artwork/movies, complete dialogue corpora, personal saves, authentication tokens, emulator logs containing private details, or local path settings. Use synthetic test fixtures where possible.

Contributions to project code are submitted under the project's GPLv3 license. Preserve upstream notices and identify third-party code and its license. Large features are easier to review if their design is discussed in an issue first.
