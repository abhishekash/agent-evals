"""Command line for running the eval suite."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_evals.report import render_markdown_table, write_results_json, write_results_md
from agent_evals.runner import run_suite
from agent_evals.tasks import load_tasks


def _selected_model(args) -> str:
    if args.provider == "opencode":
        model = args.model or os.getenv("OPENCODE_MODEL", "mimo-v2.6-pro")
        for prefix in ("opencode-go/", "opencode/"):
            if model.startswith(prefix):
                model = model[len(prefix):]
        return model
    if args.model:
        return args.model
    if args.provider == "anthropic":
        return "claude-sonnet-4-5-20250929"
    return "scripted"


def _with_retries(provider, args):
    # Newer harness versions expose the conservative retry wrapper. Keep the
    # eval runner usable against the published alpha package too.
    try:
        from agent_harness.providers import ResilientProvider, RetryPolicy
    except ImportError:
        return provider
    return ResilientProvider(
        provider,
        policy=RetryPolicy(max_attempts=args.retries + 1),
    )


def _live_provider_factory(args):
    if args.provider == "scripted":
        return None
    model = _selected_model(args)
    if args.provider == "anthropic":
        try:
            from agent_harness.providers.anthropic import AnthropicProvider
        except ImportError as exc:
            raise SystemExit(
                "live Anthropic evals require the optional dependency; "
                "install with `pip install -e '.[anthropic]'`"
            ) from exc

        def factory():
            try:
                provider = AnthropicProvider(
                    model=model,
                    temperature=args.temperature,
                    timeout=args.provider_timeout,
                )
            except TypeError:
                # Compatibility with the published pre-temperature harness.
                provider = AnthropicProvider(model=model, timeout=args.provider_timeout)
            return _with_retries(provider, args)

        return factory
    if args.provider == "opencode":
        try:
            from agent_harness.providers.opencode import OpenCodeProvider
        except ImportError as exc:
            raise SystemExit(
                "OpenCode evals require the optional dependency; "
                "install with `pip install -e '.[opencode]'`"
            ) from exc

        def factory():
            provider = OpenCodeProvider(
                model=model,
                base_url=args.base_url,
                api_key=os.getenv(args.api_key_env),
                temperature=args.temperature,
                timeout=args.provider_timeout,
            )
            return _with_retries(provider, args)

        return factory
    raise SystemExit(f"unsupported provider {args.provider!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-evals",
        description="Run deterministic or live agent tasks through agent-harness and score the traces.",
    )
    parser.add_argument("run", nargs="?", default="run", help="run the task suite")
    parser.add_argument("--tasks", default="tasks", help="directory containing *.yaml tasks")
    parser.add_argument("--out", default="results", help="output directory for traces/results")
    parser.add_argument("--label", help="provider label in reports (default: provider/model)")
    parser.add_argument(
        "--provider",
        choices=["scripted", "anthropic", "opencode"],
        default="scripted",
        help="deterministic fixture or a live Anthropic/OpenCode model",
    )
    parser.add_argument("--model", help="provider model (defaults to the provider's configured model)")
    parser.add_argument("--base-url", help="OpenCode-compatible API base URL")
    parser.add_argument("--api-key-env", default="OPENCODE_API_KEY", help="environment variable containing the OpenCode key")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--provider-timeout", type=float, default=60.0)
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=1, help="repeat every task this many times")
    parser.add_argument("--only", action="append", help="run only this task id (repeatable)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run != "run":
        raise SystemExit(f"unknown command {args.run!r}; use `agent-evals run`")

    tasks = load_tasks(args.tasks)
    if args.only:
        wanted = set(args.only)
        tasks = [t for t in tasks if t.id in wanted]
        missing = wanted - {t.id for t in tasks}
        if missing:
            raise SystemExit(f"unknown task ids: {sorted(missing)}")
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if args.retries < 0:
        raise SystemExit("--retries cannot be negative")
    prices = (args.input_price_per_million, args.output_price_per_million)
    if (prices[0] is None) != (prices[1] is None):
        raise SystemExit("provide both --input-price-per-million and --output-price-per-million")
    model = _selected_model(args)
    cost_table = {model: prices} if prices[0] is not None else None
    out = Path(args.out)
    traces_dir = out / "traces"
    provider_factory = _live_provider_factory(args)
    label = args.label or (
        "agent-harness / scripted"
        if args.provider == "scripted"
        else f"agent-harness / {args.provider}:{model}"
    )
    results = run_suite(
        tasks,
        traces_dir,
        provider_factory=provider_factory,
        repeats=args.repeats,
        cost_table=cost_table,
    )
    write_results_json(results, out / "results.json", label)
    write_results_md(results, out / "RESULTS.md", label)

    print(render_markdown_table(results))
    print(f"\nraw results: {out / 'results.json'}", file=sys.stderr)
    print(f"traces:      {traces_dir}", file=sys.stderr)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
