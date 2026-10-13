"""CLI: python -m achadinhos [serve|collect|init-db|sources]."""

from __future__ import annotations

import argparse
import json
import logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="achadinhos")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="sobe painel + API + coleta agendada")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    collect = sub.add_parser("collect", help="roda uma coleta agora e sai")
    collect.add_argument("--source", action="append", help="limita a uma fonte (repetível)")
    sub.add_parser("init-db", help="cria as tabelas")
    sub.add_parser("sources", help="mostra o status das fontes")
    args = parser.parse_args()

    if args.cmd in (None, "serve"):
        import uvicorn

        uvicorn.run("achadinhos.app:app", host=getattr(args, "host", "0.0.0.0"), port=getattr(args, "port", 8000))
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .db import create_all

    create_all()
    if args.cmd == "init-db":
        print("tabelas criadas")
    elif args.cmd == "sources":
        from .sources import get_sources

        for s in get_sources():
            print(f"{s.name:12} {s.status():60} feed={s.supports_feed} busca={s.supports_search}")
    elif args.cmd == "collect":
        from .collector import run_collection

        summary = run_collection(args.source)
        print(json.dumps(summary.runs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
