#集計ロジック担当
def degree_key(d):
    return (
        (d.get("context") or "").strip().lower(),
        (d.get("name") or "").strip().lower(),
        d.get("price"),
        (d.get("currency") or "").strip().upper(),
        (d.get("course_type") or "general").strip().lower(),
    )


def analyze_degree_duplicates(records):
    groups = {}
    total = 0
    for record in records:
        for d in record.get("degrees", []):
            total += 1
            key = degree_key(d)
            groups[key] = groups.get(key, 0) + 1

    dup_groups = 0
    dup_items = 0
    for count in groups.values():
        if count > 1:
            dup_groups += 1
            dup_items += count

    return {
        "degree_total": total,
        "degree_unique": len(groups),
        "degree_dup_groups": dup_groups,
        "degree_dup_items": dup_items,
    }
