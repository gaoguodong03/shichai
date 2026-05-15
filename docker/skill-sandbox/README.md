# Skill Sandbox Image

This image is an optional standalone runtime for `run_skill_script_*` tools. The default deployment can also reuse the main app image through `SANDBOX_BASE_IMAGE`, while this Dockerfile is useful when you want to publish and evolve the Skill runtime independently.

## Build

```bash
docker build -f docker/skill-sandbox/Dockerfile -t st49-skill-sandbox:latest .
```

## Use

Set the backend environment variable:

```bash
SANDBOX_BASE_IMAGE=st49-skill-sandbox:latest
```

For 1Panel/Compose deployments, either keep the default in `docker-compose.1panel.yml` or override `SANDBOX_BASE_IMAGE` in `.env` with your pushed registry image.

## Playwright image

The standard image tag stays `26.05.12.1-standard`. Browser/crawler-heavy Python packages are baked into the Playwright image only:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.15-playwright \
  -f docker/skill-sandbox/Dockerfile.playwright \
  --push .
```

`docker/skill-sandbox/requirements.playwright.txt` records the additional Playwright/crawler Python stack so user-level requirements do not need to reinstall it at runtime.

## User-level Python dependencies

Per-user Python packages are still supported via:

```text
data/users/<username>/config/sandbox/requirements.txt
```

The sandbox service installs that file inside the user's long-lived sandbox and only reinstalls when the file content changes.
