import argparse
import json
import logging
import mimetypes
import sys
import uuid
from pathlib import Path
from urllib import request

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from rag_stdin import read_stdin_json_dict


CONFIG_PATH = Path(__file__).with_name("config.json")
logger = logging.getLogger("document_parser_cli")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rag_service_url = config.get("rag_service_url")
    if not isinstance(rag_service_url, str) or not rag_service_url.strip():
        raise ValueError("配置文件中的 rag_service_url 必须是非空字符串")

    return {"rag_service_url": rag_service_url.rstrip("/")}


def build_multipart_body(file_path: Path) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()

    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return body, boundary


def parse_document_via_http(rag_service_url: str, input_path: Path) -> str:
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"输入路径不是文件: {input_path}")

    body, boundary = build_multipart_body(input_path)
    req = request.Request(
        url=f"{rag_service_url}/documents/parse",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    with request.urlopen(req) as response:
        response_body = response.read().decode("utf-8")
        payload = json.loads(response_body) if response_body.strip() else {}

    text = payload.get("text")
    if not isinstance(text, str):
        raise RuntimeError(f"解析服务返回结果不符合预期: {payload}")
    return text


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过 HTTP 调用文档解析服务，并输出解析后的 txt 文件。"
    )
    parser.add_argument("--input_path", required=True, help="原始文档路径")
    parser.add_argument("--output_path", required=True, help="输出 txt 文件路径")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    stdin_cfg = read_stdin_json_dict()
    if stdin_cfg and "input_path" in stdin_cfg and "output_path" in stdin_cfg:
        args = argparse.Namespace(
            input_path=str(stdin_cfg["input_path"]),
            output_path=str(stdin_cfg["output_path"]),
        )
    else:
        args = build_arg_parser().parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    output_path = Path(args.output_path).expanduser().resolve()

    try:
        config = load_config()
        content = parse_document_via_http(config["rag_service_url"], input_path)
    except Exception as exc:
        logger.error("%s", exc)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8", newline="\n")
    logger.info("已生成文本文件: %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
