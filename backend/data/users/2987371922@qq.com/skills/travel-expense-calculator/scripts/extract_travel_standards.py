from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


def _clean_text(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    return re.sub(r"\s+", " ", s)


def _to_amount(v: Any) -> int | None:
    s = _clean_text(v)
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    return int(float(m.group(0)))


def _split_cities(raw: str) -> list[str]:
    s = _clean_text(raw)
    if not s:
        return []
    parts = re.split(r"[、，,；;]\s*", s)
    out: list[str] = []
    for p in parts:
        t = _clean_text(p)
        if t:
            out.append(t)
    return out or [s]


def _find_header_row(df: pd.DataFrame) -> int:
    for i in range(min(len(df), 80)):
        row = [_clean_text(x) for x in df.iloc[i].tolist()]
        joined = " ".join(row)
        if "序号" in joined and "地区" in joined:
            return i
    return 0


def _extract_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    header_row = _find_header_row(df)
    start_row = min(header_row + 1, len(df))

    serial_idx = 0
    province_idx = 1
    city_idx = 2
    normal_start = 3
    peak_city_idx = 6
    peak_period_idx = 7
    peak_start = 8

    records: list[dict[str, Any]] = []
    current_province = ""

    for i in range(start_row, len(df)):
        row = df.iloc[i].tolist()
        if len(row) < 6:
            continue
        row = row + [""] * max(0, peak_start + 3 - len(row))
        province_raw = _clean_text(row[province_idx])
        city_raw = _clean_text(row[city_idx])

        if province_raw:
            current_province = province_raw
        province = current_province

        if not province and not city_raw:
            continue

        normal_rates = {
            "graduate_or_equivalent": _to_amount(row[normal_start]),
            "senior_or_equivalent": _to_amount(row[normal_start + 1]),
            "others": _to_amount(row[normal_start + 2]),
        }
        has_normal = any(v is not None for v in normal_rates.values())
        if has_normal:
            cities = _split_cities(city_raw) or ["全省"]
            for city in cities:
                records.append(
                    {
                        "province": province,
                        "city": city,
                        "period_type": "normal",
                        "period": "",
                        "rates": normal_rates,
                    }
                )

        peak_city = _clean_text(row[peak_city_idx])
        peak_period = _clean_text(row[peak_period_idx])
        peak_rates = {
            "graduate_or_equivalent": _to_amount(row[peak_start]),
            "senior_or_equivalent": _to_amount(row[peak_start + 1]),
            "others": _to_amount(row[peak_start + 2]),
        }
        has_peak = bool(peak_city) and any(v is not None for v in peak_rates.values())
        if has_peak:
            for city in _split_cities(peak_city):
                records.append(
                    {
                        "province": province,
                        "city": city,
                        "period_type": "peak",
                        "period": peak_period,
                        "rates": peak_rates,
                    }
                )
    return records


def _filter_records(records: list[dict[str, Any]], province: str, city: str) -> list[dict[str, Any]]:
    out = records
    p = _clean_text(province)
    c = _clean_text(city)
    if p:
        out = [r for r in out if p in _clean_text(r.get("province", ""))]
    if c:
        out = [r for r in out if c in _clean_text(r.get("city", ""))]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="从差旅标准表中提取省份/城市住宿费标准")
    parser.add_argument("--excel_path", required=True, help="xls/xlsx 文件路径")
    parser.add_argument("--sheet_name", default="", help="可选 sheet 名称")
    parser.add_argument("--province", default="", help="按省份过滤")
    parser.add_argument("--city", default="", help="按城市过滤")
    parser.add_argument("--output_json", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(json.dumps({"ok": False, "code": "file_not_found", "path": str(excel_path)}, ensure_ascii=False))
        return 2

    try:
        read_kwargs: dict[str, Any] = {"header": None, "dtype": str}
        if args.sheet_name:
            read_kwargs["sheet_name"] = args.sheet_name
        df = pd.read_excel(excel_path, **read_kwargs)
    except Exception as e:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "excel_read_failed",
                    "message": str(e),
                    "hint": "若为 .xls，请确认环境已安装 xlrd；若为 .xlsx，请确认 openpyxl 可用。",
                },
                ensure_ascii=False,
            )
        )
        return 3

    records = _extract_records(df)
    filtered = _filter_records(records, args.province, args.city)

    result = {
        "ok": True,
        "total_records": len(records),
        "matched_records": len(filtered),
        "filters": {"province": args.province, "city": args.city},
        "records": filtered,
    }

    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_json"] = str(out)

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
