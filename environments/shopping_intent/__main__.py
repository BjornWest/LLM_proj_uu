"""Run with python3 -m environments.shopping_intent."""
import argparse
import json
from pathlib import Path

from .catalog import catalog
from .generator import MEMORY_MODES, QUERY_PRESETS, generate


def main():
    parser = argparse.ArgumentParser(description="Local structured task and hybrid-memory authoring")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("families", help="Print the declarative family registry")
    sample = sub.add_parser("sample", help="Generate reproducible JSON/JSONL pairs")
    sample.add_argument("--seed", type=int, default=0)
    sample.add_argument("--count", type=int, default=1)
    sample.add_argument("--family", default="random")
    sample.add_argument("--query", choices=["random", *QUERY_PRESETS], default="cheapest")
    sample.add_argument("--memory", choices=MEMORY_MODES, default="auto")
    sample.add_argument("--requirements", type=int, default=3)
    sample.add_argument("--target", choices=("category", "model"), default="category")
    sample.add_argument("--prose-seed", type=int)
    sample.add_argument("--budget-sek", type=int)
    sample.add_argument("--hidden", choices=("auto", "none", "blocker"), default="auto")
    sample.add_argument("--public-only", action="store_true")
    sample.add_argument("--output", type=Path)
    serve = sub.add_parser("serve", help="Local privileged authoring preview (not a policy website)")
    serve.add_argument("--port", type=int, default=8876)
    args = parser.parse_args()
    if args.command == "families":
        print(json.dumps(catalog(), ensure_ascii=False, indent=2))
    elif args.command == "serve":
        from .preview import serve
        serve(args.port)
    else:
        if not 1 <= args.count <= 10000:
            parser.error("--count must be between 1 and 10000")
        rows = []
        for i in range(args.count):
            try:
                result = generate(args.seed + i, args.family, args.query, args.memory,
                                  args.requirements, args.target, args.prose_seed, args.budget_sek, args.hidden)
            except ValueError as e:
                parser.error(str(e))
            rows.append(result["public"] if args.public_only else result)
        value = (json.dumps(rows[0], ensure_ascii=False, indent=2) if args.count == 1 else
                 "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as f:
                f.write(value)
        else:
            print(value, end="")


if __name__ == "__main__":
    main()
