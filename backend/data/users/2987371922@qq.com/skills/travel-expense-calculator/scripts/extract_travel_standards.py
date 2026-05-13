from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import xlrd

_DEFAULT_EXCEL_NAME = "北京邮电大学差旅住宿费标准明细表.xls"
_DEFAULT_EXCEL_DIR = "assets"
_RATE_LABELS = {
    "graduate_or_equivalent": "院士/相当职务人员",
    "senior_or_equivalent": "司局级/相当职务人员",
    "others": "其他人员",
}
_PROVINCE_SUFFIXES = ("省", "市", "自治区", "特别行政区", "回族自治区", "壮族自治区", "维吾尔自治区")
_CITY_SUFFIXES = ("市", "地区", "盟", "自治州", "县")


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


def _strip_place_suffix(name: str) -> str:
    s = _clean_text(name)
    if not s:
        return ""
    for suf in sorted(set(_PROVINCE_SUFFIXES + _CITY_SUFFIXES), key=len, reverse=True):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _read_excel_rows(excel_path: Path) -> list[list[Any]]:
    workbook = xlrd.open_workbook(str(excel_path))
    sheet = workbook.sheet_by_index(0)
    return [sheet.row_values(i) for i in range(sheet.nrows)]


def _find_header_row(rows: list[list[Any]]) -> int:
    for i in range(min(len(rows), 80)):
        row = [_clean_text(x) for x in rows[i]]
        joined = " ".join(row)
        if "序号" in joined and "地区" in joined:
            return i
    return 0


def _extract_records(rows: list[list[Any]]) -> list[dict[str, Any]]:
    header_row = _find_header_row(rows)
    start_row = min(header_row + 1, len(rows))

    serial_idx = 0
    province_idx = 1
    city_idx = 2
    normal_start = 3
    peak_city_idx = 6
    peak_period_idx = 7
    peak_start = 8

    records: list[dict[str, Any]] = []
    current_province = ""

    for i in range(start_row, len(rows)):
        row = list(rows[i])
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


def _place_contains(value: str, needle: str) -> bool:
    v = _clean_text(value)
    n = _clean_text(needle)
    if not v or not n:
        return False
    return n in v or _strip_place_suffix(n) in {_strip_place_suffix(v), v}


def _record_matches_place(record: dict[str, Any], province: str, city: str) -> bool:
    p = _clean_text(province)
    c = _clean_text(city)
    record_province = _clean_text(record.get("province", ""))
    record_city = _clean_text(record.get("city", ""))
    if p and not _place_contains(record_province, p):
        return False
    if c and not _place_contains(record_city, c):
        return False
    return bool(p or c)


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, tuple[tuple[str, int | None], ...]]] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        rates = record.get("rates", {}) if isinstance(record.get("rates"), dict) else {}
        key = (
            _clean_text(record.get("province")),
            _clean_text(record.get("city")),
            _clean_text(record.get("period_type")),
            _clean_text(record.get("period")),
            tuple(sorted((str(k), v if isinstance(v, int) or v is None else _to_amount(v)) for k, v in rates.items())),
        )
        if key not in seen:
            seen.add(key)
            out.append(record)
    return out


def _filter_many_places(records: list[dict[str, Any]], places: list[dict[str, str]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for place in places:
        matched.extend(
            record
            for record in records
            if _record_matches_place(record, place.get("province", ""), place.get("city", ""))
        )
    return _dedupe_records(matched)


def _resolve_excel_path() -> Path:
    skill_root = Path(__file__).resolve().parents[1]
    return skill_root / _DEFAULT_EXCEL_DIR / _DEFAULT_EXCEL_NAME


def _extract_keywords(text: str) -> dict[str, str]:
    raw = _clean_text(text)
    if not raw:
        return {"province": "", "city": "", "person_type": ""}

    province = ""
    city = ""
    person_type = ""

    city_match = re.search(r"([\u4e00-\u9fa5]{2,}(?:市|地区|盟|自治州|县))", raw)
    if city_match:
        city = city_match.group(1)

    province_match = re.search(
        r"([\u4e00-\u9fa5]{2,}(?:省|自治区|特别行政区)|北京|上海|天津|重庆|内蒙古|广西|西藏|宁夏|新疆)",
        raw,
    )
    if province_match:
        province = province_match.group(1)

    if "院士" in raw or "教授级" in raw:
        person_type = "graduate_or_equivalent"
    elif "司局级" in raw or "局级" in raw:
        person_type = "senior_or_equivalent"
    elif "其他" in raw or "普通" in raw or "一般" in raw:
        person_type = "others"

    return {"province": province, "city": city, "person_type": person_type}


def _infer_place_from_records(
    records: list[dict[str, Any]],
    raw_query: str,
    province_hint: str,
    city_hint: str,
) -> tuple[str, str]:
    query = _clean_text(raw_query)
    if not query:
        return _clean_text(province_hint), _clean_text(city_hint)

    province = _clean_text(province_hint)
    city = _clean_text(city_hint)

    province_names: set[str] = set()
    city_names: set[str] = set()
    for r in records:
        p = _clean_text(r.get("province"))
        c = _clean_text(r.get("city"))
        if p:
            province_names.add(p)
            province_names.add(_strip_place_suffix(p))
        if c and c != "全省":
            city_names.add(c)
            city_names.add(_strip_place_suffix(c))

    if not province:
        candidates = [p for p in province_names if p and p in query]
        if candidates:
            province = max(candidates, key=len)
    if not city:
        candidates = [c for c in city_names if c and c in query]
        if candidates:
            city = max(candidates, key=len)

    # 如果只命中了城市，尝试反查省份，减少额外追问。
    if city and not province:
        matched_provinces = {
            _clean_text(r.get("province"))
            for r in records
            if city in {_clean_text(r.get("city")), _strip_place_suffix(_clean_text(r.get("city")))}
        }
        matched_provinces = {x for x in matched_provinces if x}
        if len(matched_provinces) == 1:
            province = next(iter(matched_provinces))

    return province, city


def _known_place_mentions(records: list[dict[str, Any]], query: str) -> list[dict[str, str]]:
    raw = _clean_text(query)
    if not raw:
        return []

    province_aliases: list[tuple[str, str, int]] = []
    city_aliases: list[tuple[str, str, str, int]] = []
    for record in records:
        province = _clean_text(record.get("province"))
        city = _clean_text(record.get("city"))
        if province:
            for alias in {province, _strip_place_suffix(province)}:
                if alias and alias in raw:
                    province_aliases.append((alias, province, raw.find(alias)))
        if city and city != "全省":
            for alias in {city, _strip_place_suffix(city)}:
                if alias and alias in raw:
                    city_aliases.append((alias, province, city, raw.find(alias)))

    places: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for _, province, city, _ in sorted(city_aliases, key=lambda x: (x[3], -len(x[0]))):
        key = (province, city)
        if key not in seen:
            seen.add(key)
            places.append({"province": province, "city": city})

    city_provinces = {place["province"] for place in places if place.get("province")}
    for _, province, _ in sorted(province_aliases, key=lambda x: (x[2], -len(x[0]))):
        key = (province, "")
        if province not in city_provinces and key not in seen:
            seen.add(key)
            places.append({"province": province, "city": ""})

    return places


def _infer_places_from_records(
    records: list[dict[str, Any]],
    raw_query: str,
    province_hint: str,
    city_hint: str,
) -> list[dict[str, str]]:
    province, city = _infer_place_from_records(records, raw_query, province_hint, city_hint)
    if province or city:
        explicit = [{"province": province, "city": city}]
        if _clean_text(province_hint) or _clean_text(city_hint):
            return explicit

    mentioned = _known_place_mentions(records, raw_query)
    if mentioned:
        return mentioned
    return [{"province": province, "city": city}] if province or city else []


def _record_to_sentence(record: dict[str, Any], person_type: str) -> str:
    rates = record.get("rates", {}) if isinstance(record.get("rates"), dict) else {}
    province = _clean_text(record.get("province"))
    city = _clean_text(record.get("city"))
    scope = f"{province}{city}"
    period = _clean_text(record.get("period"))
    if record.get("period_type") == "peak" and period:
        scope = f"{scope}（旺季：{period}）"
    elif record.get("period_type") == "normal":
        scope = f"{scope}（常规时段）"

    if person_type in _RATE_LABELS:
        amount = rates.get(person_type)
        if amount is None:
            return f"{scope}未找到{_RATE_LABELS[person_type]}的住宿费标准。"
        return f"{scope}{_RATE_LABELS[person_type]}住宿费上限为{amount}元/人·天。"

    parts: list[str] = []
    for key in ("graduate_or_equivalent", "senior_or_equivalent", "others"):
        amount = rates.get(key)
        if amount is not None:
            parts.append(f"{_RATE_LABELS[key]}{amount}元/人·天")
    if not parts:
        return f"{scope}未找到可用住宿费标准。"
    return f"{scope}住宿费标准：{'；'.join(parts)}。"


def _build_full_description(records: list[dict[str, Any]], person_type: str) -> str:
    if not records:
        return "未在表格中匹配到对应地区的住宿费标准。"
    return "\n".join(_record_to_sentence(record, person_type) for record in records)


def main() -> int:
    parser = argparse.ArgumentParser(description="从内置差旅标准表中提取省份/城市住宿费标准并输出描述")
    parser.add_argument("--query", default="", help="用户问题原文，用于提取省份/城市/人员类别关键词")
    parser.add_argument("--province", default="", help="可选，显式指定省份")
    parser.add_argument("--city", default="", help="可选，显式指定城市")
    parser.add_argument("--person_type", default="", help="可选，人员类别：graduate_or_equivalent/senior_or_equivalent/others")
    parser.add_argument("--limit", type=int, default=0, help="可选，限制返回记录数；默认 0 表示不截断")
    args = parser.parse_args()

    excel_path = _resolve_excel_path()
    if not excel_path.exists():
        print(json.dumps({"ok": False, "code": "file_not_found", "path": str(excel_path)}, ensure_ascii=False))
        return 2

    try:
        rows = _read_excel_rows(excel_path)
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

    records = _extract_records(rows)
    keywords = _extract_keywords(args.query)
    explicit_province = _clean_text(args.province)
    explicit_city = _clean_text(args.city)
    if explicit_province or explicit_city:
        places = _infer_places_from_records(records, args.query, explicit_province, explicit_city)
    else:
        places = _known_place_mentions(records, args.query)
        if not places:
            places = _infer_places_from_records(records, args.query, keywords["province"], keywords["city"])
    person_type = _clean_text(args.person_type) or keywords["person_type"]
    if person_type not in _RATE_LABELS:
        person_type = ""
    if not places:
        print(
            json.dumps(
                {
                    "ok": True,
                    "query": args.query,
                    "keywords": {"province": "", "city": "", "person_type": person_type},
                    "matched_records": 0,
                    "description": "请在问题中至少提供省份或城市（例如：'河南郑州其他人员住宿标准'）。",
                },
                ensure_ascii=False,
            )
        )
        return 0
    filtered = _filter_many_places(records, places)
    shown = filtered[: args.limit] if args.limit and args.limit > 0 else filtered
    description = _build_full_description(shown, person_type)
    if len(shown) < len(filtered):
        description = f"{description}\n共匹配到{len(filtered)}条记录，当前按 --limit 仅展示{len(shown)}条。"

    result = {
        "ok": True,
        "query": args.query,
        "keywords": {
            "province": places[0].get("province", "") if len(places) == 1 else "",
            "city": places[0].get("city", "") if len(places) == 1 else "",
            "person_type": person_type,
            "places": places,
        },
        "matched_records": len(filtered),
        "description": description,
    }

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
