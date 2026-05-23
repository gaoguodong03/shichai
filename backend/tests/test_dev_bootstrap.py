from pathlib import Path


def test_resolve_opensandbox_compose_does_not_fallback_to_1panel(tmp_path, monkeypatch):
    from app.core import dev_bootstrap

    (tmp_path / "docker-compose.1panel.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.delenv("OPENSANDBOX_COMPOSE_FILE", raising=False)

    assert dev_bootstrap.resolve_opensandbox_compose_path(tmp_path) is None


def test_resolve_opensandbox_compose_uses_explicit_path(tmp_path, monkeypatch):
    from app.core import dev_bootstrap

    explicit = tmp_path / "docker-compose.1panel.yml"
    explicit.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setenv("OPENSANDBOX_COMPOSE_FILE", str(explicit))

    assert dev_bootstrap.resolve_opensandbox_compose_path(tmp_path) == explicit.resolve()


def test_resolve_opensandbox_compose_uses_local_compose(tmp_path, monkeypatch):
    from app.core import dev_bootstrap

    local = tmp_path / "docker-compose.yml"
    local.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.delenv("OPENSANDBOX_COMPOSE_FILE", raising=False)

    assert dev_bootstrap.resolve_opensandbox_compose_path(Path(tmp_path)) == local.resolve()
