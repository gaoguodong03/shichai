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


def load_documents(input_text: str | None, input_path: str | None) -> list[str]:
    if input_text is not None:
        return [input_text]

    if input_path is None:
        raise ValueError("必须提供 --input_text 或 --input_path")

    file_path = Path(input_path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"输入路径不是文件: {file_path}")
    if file_path.suffix.lower() != ".json":
        raise ValueError("当前仅支持读取 list[str] 格式的 .json 文件")

    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("输入 JSON 文件内容必须是 list[str]")

    return data


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    qa_engine_url = config.get("qa_engine_url")
    app_id = config.get("app_id")
    api_key = config.get("api_key")

    if not isinstance(qa_engine_url, str) or not qa_engine_url.strip():
        raise ValueError("配置文件中的 qa_engine_url 必须是非空字符串")
    api_key_empty = not isinstance(api_key, str) or not api_key.strip()
    app_id_empty = not isinstance(app_id, (str, int)) or not str(app_id).strip()
    if api_key_empty or app_id_empty:
        print("配置文件中的api_key和app_id为空，请让用户提供并填入")
        return {}

    return {
        "qa_engine_url": qa_engine_url.rstrip("/"),
        "app_id": str(app_id),
        "api_key": api_key,
    }


def normalize_authorization(authorization: str) -> str:
    if authorization.startswith("Bearer "):
        return authorization
    return f"Bearer {authorization}"


def store_documents(
    qa_engine_url: str,
    authorization: str,
    app_id: str,
    documents: list[str],
) -> dict:
    payload = json.dumps(
        {
            "documents": documents,
            "app_id": app_id,
        }
    ).encode("utf-8")

    req = request.Request(
        url=f"{qa_engine_url}/document",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": normalize_authorization(authorization),
        },
    )

    with request.urlopen(req) as response:
        body = response.read().decode("utf-8")
        if not body.strip():
            return {}
        return json.loads(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="调用知识库文档添加 API，将字符串或 list[str] JSON 文件存储到向量知识库。"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input_text", help="直接存储的单条字符串")
    input_group.add_argument("--input_path", help="输入 JSON 文件路径，内容必须是 list[str]")
    return parser.parse_args()


def print_response(documents: list[str], response: dict) -> None:
    code = response.get("code")
    message = response.get("message")
    data = response.get("data")

    print(f"存储文档数: {len(documents)}")
    if code is not None or message is not None:
        print(f"状态: code={code}, message={message}")

    if isinstance(data, dict) or data is None:
        print("存储完成。")
        return

    print("返回结果结构不符合预期，原始响应如下：")
    print(json.dumps(response, ensure_ascii=False, indent=2))


def main() -> None:
    stdin_cfg = read_stdin_json_dict()
    if stdin_cfg:
        has_text = "input_text" in stdin_cfg and str(stdin_cfg.get("input_text", "")).strip() != ""
        has_path = "input_path" in stdin_cfg and str(stdin_cfg.get("input_path", "")).strip() != ""
        if has_text and not has_path:
            args = argparse.Namespace(input_text=str(stdin_cfg["input_text"]), input_path=None)
        elif has_path and not has_text:
            args = argparse.Namespace(input_text=None, input_path=str(stdin_cfg["input_path"]).strip())
        elif has_text and has_path:
            args = argparse.Namespace(input_text=str(stdin_cfg["input_text"]), input_path=None)
        else:
            args = parse_args()
    else:
        args = parse_args()

    config = load_config()
    if not config:
        return
    documents = load_documents(args.input_text, args.input_path)
    response = store_documents(
        qa_engine_url=config["qa_engine_url"],
        authorization=config["api_key"],
        app_id=config["app_id"],
        documents=documents,
    )

    print_response(documents, response)


if __name__ == "__main__":
    main()
