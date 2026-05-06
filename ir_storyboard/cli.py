"""CLI:  python -m ir_storyboard <command>

Commands:
    init                       create / reset DB and load layer reference data
    seed-accumulator           load the Accumulator pilot dataset
    weekly  <client> <quarter> run the weekly cycle
    event   <client> <subsection_id> "<event text>" [quarter]
    quarterly <client> <quarter> [traversal=inside_out|outside_in]
    outputs <client> <weekly_aid> <event_aid> <quarterly_aid>  -> writes md files
    demo                       end-to-end demo (init + seed + all 3 cycles + outputs)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, matrix, outputs, seed
from .cycles import run_event, run_quarterly, run_weekly


DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def cmd_init(args) -> None:
    db.reset()
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)
    print("Initialised matrix.db with reference layers/subsections.")


def cmd_seed_accumulator(args) -> None:
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)
    seed.load_accumulator(conn)
    print("Loaded Accumulator pilot data.")


def cmd_weekly(args) -> None:
    conn = db.connect()
    res = run_weekly(conn, client_id=args.client, quarter=args.quarter)
    print(res["body"])
    print(f"\n[saved as artifact {res['artifact_id']}]")


def cmd_event(args) -> None:
    conn = db.connect()
    res = run_event(conn, client_id=args.client, event_text=args.event,
                    landed_subsection_id=args.subsection,
                    quarter=args.quarter)
    print(res["body"])
    print(f"\n[saved as artifact {res['artifact_id']}]")


def cmd_quarterly(args) -> None:
    conn = db.connect()
    res = run_quarterly(conn, client_id=args.client, quarter=args.quarter,
                        traversal=args.traversal)
    print(res["body"])
    print(f"\n[saved as artifact {res['artifact_id']}]")


def cmd_outputs(args) -> None:
    conn = db.connect()
    files = outputs.write_all(
        conn, client_id=args.client,
        out_dir=DEFAULT_OUT_DIR,
        weekly_artifact_id=args.weekly,
        event_artifact_id=args.event,
        quarterly_artifact_id=args.quarterly,
    )
    for k, p in files.items():
        print(f"  {k:24s}  {p}")


def cmd_demo(args) -> None:
    print("→ Init...")
    db.reset()
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)

    print("→ Seed Accumulator pilot...")
    seed.load_accumulator(conn)

    quarter = "2026Q2"
    print(f"→ Weekly cycle for {quarter}...")
    weekly = run_weekly(conn, client_id=seed.CLIENT_ID, quarter=quarter,
                        week_label="2026-W18")

    print(f"→ Event cycle (simulated event lands at L8.2)...")
    event = run_event(conn, client_id=seed.CLIENT_ID,
        event_text=("Federal Reserve cuts rates 50bps, secondary market "
                    "transaction volume surges 22% week-over-week."),
        landed_subsection_id="8.2",
        quarter=quarter)

    print(f"→ Quarterly cycle (inside-out traversal)...")
    quarterly = run_quarterly(conn, client_id=seed.CLIENT_ID,
                              quarter=quarter, traversal="inside_out")

    print(f"→ Writing analyst outputs to {DEFAULT_OUT_DIR}/")
    files = outputs.write_all(
        conn, client_id=seed.CLIENT_ID,
        out_dir=DEFAULT_OUT_DIR,
        weekly_artifact_id=weekly["artifact_id"],
        event_artifact_id=event["artifact_id"],
        quarterly_artifact_id=quarterly["artifact_id"],
    )
    print()
    print("Done. Output files:")
    for k, p in files.items():
        print(f"  {k:24s}  {p}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ir_storyboard")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init"); sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("seed-accumulator"); sp.set_defaults(func=cmd_seed_accumulator)

    sp = sub.add_parser("weekly"); sp.add_argument("client"); sp.add_argument("quarter")
    sp.set_defaults(func=cmd_weekly)

    sp = sub.add_parser("event")
    sp.add_argument("client"); sp.add_argument("subsection")
    sp.add_argument("event"); sp.add_argument("--quarter", default=None)
    sp.set_defaults(func=cmd_event)

    sp = sub.add_parser("quarterly")
    sp.add_argument("client"); sp.add_argument("quarter")
    sp.add_argument("--traversal", default="inside_out",
                    choices=["inside_out", "outside_in"])
    sp.set_defaults(func=cmd_quarterly)

    sp = sub.add_parser("outputs")
    sp.add_argument("client"); sp.add_argument("weekly", type=int)
    sp.add_argument("event", type=int); sp.add_argument("quarterly", type=int)
    sp.set_defaults(func=cmd_outputs)

    sp = sub.add_parser("demo"); sp.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
