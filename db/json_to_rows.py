from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse


def extract_university_name(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    domain_map = {
        "study.ed.ac.uk": "University of Edinburgh",
        "ed.ac.uk": "University of Edinburgh",
        "athabascau.ca": "Athabasca University",
        "open.ac.uk": "The Open University",
        "london.ac.uk": "University of London",
        "ignou.ac.in": "Indira Gandhi National Open University",
    }

    for domain_pattern, name in domain_map.items():
        if domain_pattern in domain:
            return name

    parts = domain.split(".")
    skip_prefixes = {"www", "study", "apply", "admissions", "courses", "portal"}
    for part in parts:
        if part not in skip_prefixes and part:
            return part.title()
    return domain.title()


def extract_program_name(title: str) -> str:
    if " - " in title:
        return title.split(" - ")[0].strip()
    return title.strip()


def parse_timestamp(iso_string: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_string


def normalize_degree_level(raw_degree_name: str) -> str:
    if not raw_degree_name:
        return "Other"

    name_lower = raw_degree_name.lower().strip()
    if "phd" in name_lower or "doctorate" in name_lower or "博士" in name_lower:
        return "PhD"
    if any(k in name_lower for k in ["bachelor", "undergraduate", "bsc", "beng", "ba ", "学士"]):
        return "Bachelor"
    if any(k in name_lower for k in ["master", "postgraduate", "graduate", "msc", "meng", "ma ", "修士"]):
        return "Master"
    return "Other"


def as_nullable_text(value):
    if value is None:
        return ""
    return str(value)


def transform_records_to_rows(records: list[dict]) -> dict[str, list[dict]]:
    universities = {}
    programs = []
    patterns = {}
    program_tuition_map = []

    program_id_counter = 1
    university_id_counter = 1
    pattern_id_counter = 1
    created_at_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for record in records:
        url = record.get("url", "")
        title = record.get("title", "")
        country = record.get("country", "")
        timestamp = record.get("timestamp", "")

        uni_name = extract_university_name(url)
        if uni_name not in universities:
            universities[uni_name] = {
                "id": university_id_counter,
                "url": url,
                "country": country,
            }
            university_id_counter += 1

        program_name = extract_program_name(title)
        degrees = record.get("degrees", [])
        if not degrees:
            degrees = [
                {
                    "name": program_name,
                    "course_type": "general",
                    "is_online": False,
                    "price": "",
                    "currency": "",
                    "tuition_type": "unknown",
                    "amount_min": "",
                    "amount_max": "",
                    "normalized_monthly_amount": "",
                    "normalization_note": "unknown_not_normalized",
                }
            ]

        for degree in degrees:
            course_type = degree.get("course_type", "general")
            amount_preview = degree.get("price", "")
            currency_preview = degree.get("currency", "")
            quality_flag = (
                "low"
                if (
                    course_type == "general"
                    or amount_preview in ("", None)
                    or currency_preview in ("", None)
                )
                else "high"
            )

            programs.append(
                {
                    "id": program_id_counter,
                    "university_id": universities[uni_name]["id"],
                    "program_name": program_name,
                    "course_type": course_type,
                    "is_online": 1 if degree.get("is_online") else 0,
                    "source_url": url,
                    "last_seen": parse_timestamp(timestamp),
                    "quality_flag": quality_flag,
                }
            )

            degree_level = normalize_degree_level(degree.get("name", ""))
            amount = degree.get("price", "")
            currency = degree.get("currency", "")
            fee_type = "tuition"
            tuition_type = degree.get("tuition_type", "unknown")
            amount_min = degree.get("amount_min", "")
            amount_max = degree.get("amount_max", "")
            normalized_monthly_amount = degree.get("normalized_monthly_amount", "")
            normalization_note = degree.get("normalization_note", "unknown_not_normalized")

            if amount in ("", None) or currency in ("", None):
                program_id_counter += 1
                continue

            pattern_key = (
                degree_level,
                as_nullable_text(amount),
                currency,
                fee_type,
                tuition_type,
                as_nullable_text(amount_min),
                as_nullable_text(amount_max),
                as_nullable_text(normalized_monthly_amount),
                normalization_note,
            )

            if pattern_key not in patterns:
                patterns[pattern_key] = pattern_id_counter
                pattern_id_counter += 1

            program_tuition_map.append(
                {
                    "degree_program_id": program_id_counter,
                    "tuition_pattern_id": patterns[pattern_key],
                }
            )

            program_id_counter += 1

    university_rows = []
    for uni_name, info in universities.items():
        university_rows.append(
            {
                "id": info["id"],
                "name": uni_name,
                "country": info["country"],
                "url": info["url"],
                "created_at": created_at_now,
            }
        )

    pattern_rows = []
    for (
        degree_level,
        amount,
        currency,
        fee_type,
        tuition_type,
        amount_min,
        amount_max,
        normalized_monthly_amount,
        normalization_note,
    ), pid in patterns.items():
        pattern_rows.append(
            {
                "id": pid,
                "degree_level": degree_level,
                "amount": amount,
                "currency": currency,
                "fee_type": fee_type,
                "tuition_type": tuition_type,
                "amount_min": amount_min,
                "amount_max": amount_max,
                "normalized_monthly_amount": normalized_monthly_amount,
                "normalization_note": normalization_note,
            }
        )

    return {
        "universities": university_rows,
        "degree_programs": programs,
        "tuition_patterns": pattern_rows,
        "program_tuition_map": program_tuition_map,
    }
