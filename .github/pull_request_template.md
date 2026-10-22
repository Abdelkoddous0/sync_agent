## What and why


## How it was tested
- [ ] `python -m pytest` passes
- [ ] `build.bat` succeeds on Windows (if packaging, scripts or entry points changed)
- [ ] Native packaged tests (`docs/testing.md`) run, if install/uninstall behaviour changed

## Checklist
- [ ] No new unconditional S3 overwrite/delete or process kill
- [ ] No secrets or exception messages from AWS/credential providers are logged or displayed
- [ ] Documentation and `CHANGELOG.md` updated
