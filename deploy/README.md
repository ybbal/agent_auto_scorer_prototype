# Server deployment

The prototype is deployed to `root@89.127.211.223` as a systemd service. SSH is used only for
administration; the process runs as the unprivileged `auto-value-agent` user.

## Server paths

- Application: `/opt/auto-value-agent`
- Secrets: `/opt/auto-value-agent/.env` (`root:auto-value-agent`, mode `0640`)
- SQLite: `/var/lib/auto-value-agent/agent.db`
- Logs: `/var/log/auto-value-agent/agent.log`
- Unit: `/etc/systemd/system/auto-value-agent.service`

The unit sets absolute `SCORE_CSV_PATH` and `FEATURE_MAPPING_PATH` values because the
application is installed non-editably and packaged modules cannot infer the repository root.

## Operations

```bash
ssh root@89.127.211.223 systemctl status auto-value-agent
ssh root@89.127.211.223 journalctl -u auto-value-agent -f
ssh root@89.127.211.223 tail -f /var/log/auto-value-agent/agent.log
ssh root@89.127.211.223 systemctl restart auto-value-agent
```

Before starting a deployment, run `uv run pytest`, `uv run ruff check .`, and
`uv run mypy src`. Synchronize the repository without `.git`, `.env`, local virtual
environments, caches, build output, or `var/`. Copy `.env` separately and preserve its mode.
Run `/root/.local/bin/uv sync --directory /opt/auto-value-agent --locked --no-dev
--no-editable`, validate the data, then restart the unit.
