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

import yaml

from . import db, matrix, outputs, seed
from .cycles import run_event, run_quarterly, run_weekly


DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def cmd_init(args) -> None:
    db.reset()
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)
    print("Initialised matrix.db with reference layers/subsections.")


def cmd_add_client(args) -> None:
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)

    if args.from_file:
        data = yaml.safe_load(Path(args.from_file).read_text(encoding="utf-8"))
        c = data.get("client", {})
        client_id = c.get("id", "")
        name = c.get("name", "")
        sector = c.get("sector", "")
        one_liner = c.get("one_liner", "")
        founder_name = data.get("founder_name", "")
        founder_handle = data.get("founder_handle", "")
        aliases = data.get("aliases", [])
        notes = data.get("notes", "")
        seed_facts = data.get("seed_facts", [])
        seed_tracks = data.get("seed_tracks", [])
        initial_quarter = data.get("initial_quarter")
    else:
        client_id = args.id
        name = args.name
        sector = getattr(args, "sector", "") or ""
        one_liner = getattr(args, "one_liner", "") or ""
        founder_name = getattr(args, "founder", "") or ""
        founder_handle = ""
        aliases = []
        notes = ""
        seed_facts = []
        seed_tracks = []
        initial_quarter = None

    if not client_id or not name:
        print("Error: client id and name are required.", file=sys.stderr)
        sys.exit(1)

    existing = matrix.count_client_facts(conn, client_id)
    if existing > 0 and not getattr(args, "force", False):
        print(f"Error: client '{client_id}' already has {existing} facts. Use --force to add more.",
              file=sys.stderr)
        sys.exit(1)

    matrix.upsert_client(conn, client_id, name, sector=sector, one_liner=one_liner,
                         founder_name=founder_name, founder_handle=founder_handle,
                         aliases=aliases, notes=notes)
    matrix.ensure_full_grid(conn, client_id)

    fact_count = source_count = track_count = 0
    for sf in seed_facts:
        src_id = matrix.add_source(conn, channel=sf["channel"],
                                   title=sf.get("source_title", ""),
                                   url=sf.get("source_url", ""))
        matrix.add_fact(conn, client_id=client_id, subsection_id=sf["subsection_id"],
                        text=sf["text"], flag=sf["flag"], source_id=src_id)
        fact_count += 1
        source_count += 1

    if initial_quarter and seed_tracks:
        plan_id = matrix.upsert_plan(conn, client_id, initial_quarter)
        for st in seed_tracks:
            matrix.add_track(conn, plan_id=plan_id, name=st["name"],
                             angle=st.get("angle", ""),
                             target_layer_ids=st.get("target_layer_ids", []),
                             target_subsection_ids=st.get("target_subsection_ids", []),
                             priority=st.get("priority", 1))
            track_count += 1

    print(f"Created client '{client_id}': {fact_count} facts, {source_count} sources, {track_count} tracks.")


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

    sp = sub.add_parser("add-client")
    sp.add_argument("--from", dest="from_file", metavar="YAML", help="path to seed YAML")
    sp.add_argument("--id", default="")
    sp.add_argument("--name", default="")
    sp.add_argument("--sector", default="")
    sp.add_argument("--one-liner", default="")
    sp.add_argument("--founder", default="")
    sp.add_argument("--no-seed-facts", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_add_client)

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
