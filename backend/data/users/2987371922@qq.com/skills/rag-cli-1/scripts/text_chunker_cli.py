import argparse
import json
import sys
from pathlib import Path
from urllib import request

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from rag_stdin import read_stdin_json_dict


CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rag_service_url = config.get("rag_service_url")
    if not isinstance(rag_service_url, str) or not rag_service_url.strip():
        raise ValueError("配置文件中的 rag_service_url 必须是非空字符串")

    return {"rag_service_url": rag_service_url.rstrip("/")}


def load_input_text(input_path: str) -> str:
    file_path = Path(input_path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {file_path}")
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

    with request.urlopen(req) as response:
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
    stdin_cfg = read_stdin_json_dict()
    if stdin_cfg and "input_path" in stdin_cfg and "output_path" in stdin_cfg:
        args = argparse.Namespace(
            input_path=str(stdin_cfg["input_path"]),
            output_path=str(stdin_cfg["output_path"]),
        )
    else:
        args = parse_args()

    config = load_config()
    text = load_input_text(args.input_path)
    chunks = chunk_text_via_http(config["rag_service_url"], text)

    output_path = Path(args.output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"处理完成，输出 {len(chunks)} 个文本块到 {output_path}")


if __name__ == "__main__":
    main()
