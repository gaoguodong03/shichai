from __future__ import annotations

import argparse
import json
import sys


def _get_version(pkg: str) -> str:
    try:
        from importlib import metadata as importlib_metadata  # py3.8+
    except Exception:  # pragma: no cover
        import importlib_metadata  # type: ignore

    try:
        return importlib_metadata.version(pkg)
    except Exception:
        return ""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--package", required=True, help="要检查的包名（distribution name），如 pendulum")
    args = p.parse_args()

    pkg = (args.package or "").strip()
    if not pkg:
        print("missing --package", file=sys.stderr)
        return 2

    # 先尝试取 metadata 版本（不会触发 import 副作用）；取不到再尝试 import。
    ver = _get_version(pkg)
    if not ver:
        try:
            __import__(pkg)
        except Exception as e:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "code": "package_not_installed",
                        "package": pkg,
                        "error": f"{type(e).__name__}: {e}",
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 3
        ver = _get_version(pkg) or "unknown"

    print(json.dumps({"ok": True, "package": pkg, "version": ver}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

