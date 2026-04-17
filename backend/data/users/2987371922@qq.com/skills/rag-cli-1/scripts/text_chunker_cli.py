import argparse
import json
import sys
from pathlib import Path
from urllib import request

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from rag_stdin import has_cli_argv, is_interactive_cli, read_stdin_json_dict
from skill_io import emit_result, env_snapshot, explain_common_path_mistakes, resolve_workspace_path


CONFIG_PATH = Path(__file__).with_name("config.json")
HTTP_TIMEOUT_SEC = 20.0


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rag_service_url = config.get("rag_service_url")
    if not isinstance(rag_service_url, str) or not rag_service_url.strip():
        raise ValueError("配置文件中的 rag_service_url 必须是非空字符串")

    return {"rag_service_url": rag_service_url.rstrip("/")}


def load_input_text(input_path: str) -> str:
    file_path = resolve_workspace_path(input_path)
    if not file_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {file_path}. {explain_common_path_mistakes(file_path)}")
    if not file_path.is_file():
        raise ValueError(f"输入路径不是文件: {file_path}")
    if file_path.suffix.lower() != ".txt":
        raise ValueError("当前文本分块脚本只支持读取 .txt 文件")

    return file_path.read_text(encoding="utf-8")


def chunk_text_via_http(rag_service_url: str, text: str) -> list[str]:
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=f"{rag_service_url}/texts/chunk",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    with request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
        response_body = response.read().decode("utf-8")
        data = json.loads(response_body) if response_body.strip() else {}

    chunks = data.get("chunks")
    if not isinstance(chunks, list) or not all(isinstance(item, str) for item in chunks):
        raise RuntimeError(f"切分服务返回结果不符合预期: {data}")
    return chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 HTTP 调用文本切分服务，将 txt 文件切分为 JSON 文件。"
    )
    parser.add_argument("--input_path", required=True, help="输入 txt 文件路径")
    parser.add_argument("--output_path", required=True, help="输出 JSON 文件路径")
    return parser.parse_args()


def main() -> None:
    try:
        stdin_cfg = read_stdin_json_dict()
        if stdin_cfg and "input_path" in stdin_cfg and "output_path" in stdin_cfg:
            args = argparse.Namespace(
                input_path=str(stdin_cfg["input_path"]),
                output_path=str(stdin_cfg["output_path"]),
            )
        else:
            if has_cli_argv() or is_interactive_cli():
                args = parse_args()
            else:
                emit_result(
                    ok=False,
                    code="missing_args",
                    message=(
                        "非交互且无命令行参数时，请在 stdin 传入 JSON 或用 cli_args_json 传 "
                        "--input_path / --output_path（相对当前工作目录）。"
                    ),
                    debug=env_snapshot(),
                    to_stderr=True,
                )
                raise SystemExit(2)

        config = load_config()
        text = load_input_text(args.input_path)
        chunks = chunk_text_via_http(config["rag_service_url"], text)

        output_path = resolve_workspace_path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

        # 保留原有可读输出
        print(f"处理完成，输出 {len(chunks)} 个文本块到 {output_path}")
        emit_result(
            ok=True,
            code="chunked",
            message="文本已切分并写入 JSON。",
            data={"chunks_count": len(chunks), "output_path": str(output_path)},
            debug=env_snapshot(),
        )
    except SystemExit:
        raise
    except Exception as e:
        emit_result(
            ok=False,
            code="error",
            message=str(e),
            debug=env_snapshot(),
            to_stderr=True,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
