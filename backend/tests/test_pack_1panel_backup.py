import os
import shutil
import subprocess
import tarfile
from pathlib import Path


def _copy_pack_inputs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    shutil.copy(repo_root / "pack_1panel_backup.sh", tmp_path / "pack_1panel_backup.sh")
    shutil.copy(repo_root / "docker-compose.1panel.yml", tmp_path / "docker-compose.1panel.yml")


def _read_packaged_env(output_tgz: Path) -> str:
    with tarfile.open(output_tgz, "r:gz") as archive:
        packaged_env = archive.extractfile("1panel-compose-backup/compose_files/.env")
        assert packaged_env is not None
        return packaged_env.read().decode("utf-8")


def test_pack_1panel_backup_allows_missing_env_file(tmp_path: Path) -> None:
    _copy_pack_inputs(tmp_path)

    output_tgz = tmp_path / "backup.tar.gz"
    env = {
        **os.environ,
        "ENV_FILE": "backend/.env",
        "OUT_TGZ": str(output_tgz),
    }

    result = subprocess.run(
        ["bash", "pack_1panel_backup.sh"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    env_text = _read_packaged_env(output_tgz)

    assert "ST49_VERSION=26.05.13" in env_text
    assert (
        "ST49_IMAGE=crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/"
        "free4inno-yuanfang2025/dha:26.05.13"
    ) in env_text
    assert "SANDBOX_PREWARM_ALL_USERS=0" in env_text


def test_pack_1panel_backup_tag_build_path_does_not_require_env_file(
    tmp_path: Path,
) -> None:
    _copy_pack_inputs(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    output_tgz = tmp_path / "backup.tar.gz"
    env = {
        **os.environ,
        "DOCKER_LOG": str(docker_log),
        "ENV_FILE": "backend/.env",
        "OUT_TGZ": str(output_tgz),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash", "pack_1panel_backup.sh", "26.05.99"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "No env file found at backend/.env" in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert (
        "-t crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/"
        "free4inno-yuanfang2025/dha:26.05.99 ."
    ) in docker_calls
    assert (
        "push crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/"
        "free4inno-yuanfang2025/dha:26.05.99"
    ) in docker_calls

    env_text = _read_packaged_env(output_tgz)
    assert "ST49_VERSION=26.05.99" in env_text
    assert (
        "ST49_IMAGE=crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/"
        "free4inno-yuanfang2025/dha:26.05.99"
    ) in env_text
