"""Command line for the control plane and the evidence tooling.

``chamber serve`` runs the HTTP API; ``chamber register|run|verify|export``
drive and audit experiments without touching HTTP. ``chamber`` with no
arguments still serves, so existing deployments keep working.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from chamber_orchestra.evaluation.suite import default_suite, load_suite
from chamber_orchestra.experiment.flow import FlowError, run_experiment
from chamber_orchestra.experiment.prereg import PreRegistration
from chamber_orchestra.execution.executor import SimulatedExecutor
from chamber_orchestra.harness.registry import HarnessStore
from chamber_orchestra.ledger.export import export_experiment
from chamber_orchestra.ledger.store import Ledger

DEFAULT_ROOT = ".runtime"


def _default_ledger(root: str) -> Path:
    return Path(root) / "ledger.sqlite3"


def _load_prereg(path: str) -> PreRegistration:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return PreRegistration.from_document(document)


def _serve(args: argparse.Namespace) -> int:
    from chamber_orchestra.api.app import create_app

    import uvicorn

    app = create_app(args.root, suite_path=args.suite)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _register(args: argparse.Namespace) -> int:
    prereg = _load_prereg(args.prereg)
    with Ledger(args.ledger) as ledger:
        ledger.register_experiment(prereg)
        record = ledger.get_experiment(prereg.experiment_id) or {}
    print(
        json.dumps(
            {
                "experiment_id": prereg.experiment_id,
                "digest": prereg.digest(),
                "state": record.get("state"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    prereg = _load_prereg(args.prereg)
    suite = load_suite(args.suite) if args.suite else default_suite()
    root = Path(args.root)
    store = HarnessStore(root / "harnesses")
    with Ledger(args.ledger) as ledger:
        outcome = run_experiment(
            ledger=ledger,
            store=store,
            suite=suite,
            executor=SimulatedExecutor(),
            prereg=prereg,
            artifacts_root=root / "artifacts",
        )
    print(json.dumps(outcome.document(), indent=2, sort_keys=True))
    return 0 if outcome.state in ("completed", "rejected") else 1


def _verify(args: argparse.Namespace) -> int:
    with Ledger(args.ledger) as ledger:
        report = ledger.verify()
    print(json.dumps(report.document(), indent=2, sort_keys=True))
    return 0 if report.ok else 1


def _export(args: argparse.Namespace) -> int:
    with Ledger(args.ledger) as ledger:
        export = export_experiment(ledger, args.experiment)
    if args.out:
        Path(args.out).write_text(export.to_json(), encoding="utf-8")
        print(
            json.dumps(
                {"written": args.out, "experiment_id": args.experiment},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        sys.stdout.write(export.to_json())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chamber",
        description="Evidence-gated harness improvement control plane.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="run the HTTP control plane")
    serve.add_argument("--root", default=os.environ.get("CHAMBER_ROOT", DEFAULT_ROOT))
    serve.add_argument("--suite", default=os.environ.get("CHAMBER_SUITE"))
    serve.add_argument(
        "--port", type=int, default=int(os.environ.get("CHAMBER_PORT", "8000"))
    )
    serve.add_argument("--host", default=os.environ.get("CHAMBER_HOST", "127.0.0.1"))
    serve.set_defaults(handler=_serve)

    register = subparsers.add_parser(
        "register", help="store the pre-registration of an experiment"
    )
    register.add_argument("--prereg", required=True)
    register.add_argument("--ledger", default=str(_default_ledger(DEFAULT_ROOT)))
    register.set_defaults(handler=_register)

    run = subparsers.add_parser("run", help="run a pre-registered comparison")
    run.add_argument("--prereg", required=True)
    run.add_argument("--root", default=os.environ.get("CHAMBER_ROOT", DEFAULT_ROOT))
    run.add_argument("--suite", default=os.environ.get("CHAMBER_SUITE"))
    run.add_argument("--ledger", default=None)
    run.set_defaults(handler=_run)

    verify = subparsers.add_parser(
        "verify", help="verify the ledger hash chain and its seals"
    )
    verify.add_argument("--ledger", default=str(_default_ledger(DEFAULT_ROOT)))
    verify.set_defaults(handler=_verify)

    export = subparsers.add_parser(
        "export", help="export an experiment with its evidence"
    )
    export.add_argument("--experiment", required=True)
    export.add_argument("--ledger", default=str(_default_ledger(DEFAULT_ROOT)))
    export.add_argument("--out")
    export.set_defaults(handler=_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "handler", None) is None:
        args = parser.parse_args(["serve", *(argv if argv is not None else sys.argv[1:])])
    if args.command == "run" and args.ledger is None:
        args.ledger = str(_default_ledger(args.root))
    try:
        return args.handler(args)
    except (FlowError, OSError, json.JSONDecodeError) as exc:
        print(f"chamber: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
