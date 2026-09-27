#!/usr/bin/env python3
"""Собирает openapi/openapi.yaml из openapi/base.yaml и openapi/fragments/*.yaml.

Фрагмент содержит только ключи `paths` и/или `components` (schemas, parameters, responses,
headers, securitySchemes). Один ключ может быть определён ровно в одном файле: дубликат —
ошибка с именами обоих файлов. После сборки проверяются висячие локальные $ref.

    python3 scripts/bundle.py            # собрать и проверить
    python3 scripts/bundle.py --check    # проверить, что openapi.yaml совпадает со сборкой
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "openapi" / "base.yaml"
FRAGMENTS = ROOT / "openapi" / "fragments"
OUT = ROOT / "openapi" / "openapi.yaml"
HEADER = "# СГЕНЕРИРОВАНО scripts/bundle.py — не править руками; правки во openapi/base.yaml и openapi/fragments/\n"


def load(path):
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: корень должен быть объектом")
    return data


def merge_map(target, source, owners, section, origin, errors):
    for key, value in (source or {}).items():
        slot = f"{section}/{key}"
        if key in target:
            errors.append(f"дубликат {slot}: {owners[slot]} и {origin}")
            continue
        target[key] = value
        owners[slot] = origin


def collect_refs(node, out):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            out.add(ref)
        for value in node.values():
            collect_refs(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_refs(value, out)


def resolve(doc, ref):
    node = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def build():
    doc = load(BASE)
    doc.setdefault("paths", {})
    doc.setdefault("components", {})
    owners, errors = {}, []
    for section, value in list(doc["components"].items()):
        for key in value or {}:
            owners[f"components/{section}/{key}"] = BASE.name
    for key in doc["paths"]:
        owners[f"paths/{key}"] = BASE.name

    for frag in sorted(FRAGMENTS.glob("*.yaml")):
        data = load(frag)
        extra = set(data) - {"paths", "components"}
        if extra:
            errors.append(f"{frag.name}: недопустимые ключи верхнего уровня {sorted(extra)}")
        merge_map(doc["paths"], data.get("paths"), owners, "paths", frag.name, errors)
        for section, value in (data.get("components") or {}).items():
            merge_map(doc["components"].setdefault(section, {}), value, owners, f"components/{section}", frag.name, errors)

    doc["paths"] = dict(sorted(doc["paths"].items()))
    for section in doc["components"]:
        doc["components"][section] = dict(sorted((doc["components"][section] or {}).items()))

    refs = set()
    collect_refs(doc, refs)
    for ref in sorted(refs):
        if not resolve(doc, ref):
            errors.append(f"висячий $ref {ref}")
    return doc, errors


def main():
    doc, errors = build()
    text = HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            raise SystemExit("openapi/openapi.yaml устарел: запустите python3 scripts/bundle.py")
        print("ok: openapi.yaml актуален")
        return
    OUT.write_text(text, encoding="utf-8")
    print(f"ok: {len(doc['paths'])} путей, {len(doc['components'].get('schemas', {}))} схем -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
