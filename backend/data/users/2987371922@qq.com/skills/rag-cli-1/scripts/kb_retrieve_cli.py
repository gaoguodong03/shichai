import argparse
import json
import sys
from pathlib import Path
from urllib import request

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from rag_stdin import has_cli_argv, is_interactive_cli, read_stdin_json_dict


CONFIG_PATH = Path(__file__).with_name("config.json")


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
        "app_id": int(app_id),
        "api_key": api_key,
    }


def normalize_authorization(authorization: str) -> str:
    if authorization.startswith("Bearer "):
        return authorization
    return f"Bearer {authorization}"


def retrieve_documents(
    qa_engine_url: str,
    authorization: str,
    app_id: int,
    query: str,
) -> dict:
    payload = json.dumps(
        {
            "app_id": app_id,
            "query": query,
        }
    ).encode("utf-8")

    req = request.Request(
        url=f"{qa_engine_url}/chat/retrieve",
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
        description="调用相似度检索 API，根据 query 从向量知识库中检索内容。"
    )
    parser.add_argument("--query", required=True, help="检索问题")
    return parser.parse_args()


def print_response(query: str, response: dict) -> None:
    code = response.get("code")
    message = response.get("message")
    data = response.get("data")
    documents = data.get("documents") if isinstance(data, dict) else None

    print(f"查询: {query}")
    if code is not None or message is not None:
        print(f"状态: code={code}, message={message}")

    if isinstance(documents, list):
        print(f"命中文档数: {len(documents)}")
        if not documents:
            print("未检索到文档。")
            return

        print("检索结果:")
        for index, document in enumerate(documents, 1):
            print(f"{index}. {document}")
        return

    print("返回结果结构不符合预期，原始响应如下：")
    print(json.dumps(response, ensure_ascii=False, indent=2))


def main() -> None:
    stdin_cfg = read_stdin_json_dict()
    if stdin_cfg and "query" in stdin_cfg and str(stdin_cfg.get("query", "")).strip():
        args = argparse.Namespace(query=str(stdin_cfg["query"]).strip())
    else:
        if has_cli_argv() or is_interactive_cli():
            args = parse_args()
        else:
            print(
                "非交互且无命令行参数时，请在 stdin 传入 JSON："
                '{"query": "..."}；或使用 cli_args_json：[\"--query\",\"问题\"]。',
                file=sys.stderr,
            )
            sys.exit(2)

    config = load_config()
    if not config:
        return
    response = retrieve_documents(
        qa_engine_url=config["qa_engine_url"],
        authorization=config["api_key"],
        app_id=config["app_id"],
        query=args.query,
    )

    print_response(args.query, response)


if __name__ == "__main__":
    main()
