"""Command line interface for :class:`kvstore.core.KVStore`."""

from __future__ import annotations

import argparse
import json
import sys

from kvstore.core import KVStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kvstore",
        description="Simple JSON-backed key-value store CLI.",
    )
    parser.add_argument(
        "--db",
        default=".kvstore.json",
        help="Path to the storage file (default: .kvstore.json).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="Set a key to a value (JSON-parsed if possible).")
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_get = sub.add_parser("get", help="Get the value for a key.")
    p_get.add_argument("key")

    p_del = sub.add_parser("delete", help="Delete a key.")
    p_del.add_argument("key")

    sub.add_parser("list", help="List all keys and values.")
    return parser


def _coerce(value: str) -> object:
    """Try to parse ``value`` as JSON, fall back to the raw string."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = KVStore(args.db)

    if args.command == "set":
        store.set(args.key, _coerce(args.value))
        print(f"set {args.key}")
        return 0

    if args.command == "get":
        try:
            print(json.dumps(store.get(args.key), ensure_ascii=False))
        except KeyError:
            print(f"key not found: {args.key}", file=sys.stderr)
            return 1
        return 0

    if args.command == "delete":
        ok = store.delete(args.key)
        print("deleted" if ok else "not found")
        return 0 if ok else 1

    if args.command == "list":
        print(json.dumps(store.list(), ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
