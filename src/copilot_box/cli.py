from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from copilot_box import __version__
from copilot_box.agent import AgentService, PromptRequest
from copilot_box.blob_storage import AzureBlobStorage
from copilot_box.config import load_settings
from copilot_box.requests import StorageRequestProcessor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copilot-box",
        description="Copilot Box CLI and Windows Service entry point.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("version", help="Print the package version.")

    service_parser = subparsers.add_parser("service", help="Run service commands.")
    service_subparsers = service_parser.add_subparsers(dest="service_command")

    run_parser = service_subparsers.add_parser("run", help="Run the long-lived service loop.")
    run_parser.add_argument(
        "--config", required=True, type=Path, help="Path to the TOML config file."
    )
    run_parser.add_argument(
        "--max-iterations",
        type=int,
        help="Stop after this many polling iterations. Omit for normal long-running service mode.",
    )

    once_parser = service_subparsers.add_parser("once", help="Process one polling iteration.")
    once_parser.add_argument(
        "--config", required=True, type=Path, help="Path to the TOML config file."
    )

    prompt_parser = service_subparsers.add_parser(
        "prompt",
        help="Send one prompt through the configured Copilot agent service.",
    )
    prompt_parser.add_argument(
        "--config", required=True, type=Path, help="Path to the TOML config file."
    )
    prompt_parser.add_argument(
        "--work-dir", required=True, type=Path, help="Agent working directory."
    )
    prompt_parser.add_argument("--prompt", required=True, help="User prompt to send to the agent.")
    prompt_parser.add_argument(
        "--session-mode",
        choices=["auto", "new", "continue"],
        default="auto",
        help="Whether to create a new session, continue a known session, or decide automatically.",
    )
    prompt_parser.add_argument("--session-id", help="Existing or requested session id.")
    prompt_parser.add_argument("--model", help="Override the configured model.")
    prompt_parser.add_argument("--timeout", type=float, help="Prompt timeout in seconds.")
    prompt_parser.add_argument("--json", action="store_true", help="Print a JSON result envelope.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "service":
        if args.service_command == "prompt":
            result = asyncio.run(_run_prompt(args))
            if args.json:
                print(
                    json.dumps(
                        {
                            "sessionId": result.session_id,
                            "createdSession": result.created_session,
                            "workDir": str(result.work_dir),
                            "output": result.output,
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                print(f"session_id={result.session_id}")
                print(f"created_session={str(result.created_session).lower()}")
                print(result.output)
            return 0

        if args.service_command == "once":
            results = asyncio.run(_run_once(args))
            print(json.dumps([result.__dict__ for result in results], ensure_ascii=False))
            return 0

        if args.service_command == "run":
            asyncio.run(_run_loop(args))
            return 0

    parser.print_help()
    return 0


async def _run_prompt(args: argparse.Namespace):
    settings = load_settings(args.config)
    service = AgentService(settings=settings)
    return await service.handle_prompt(
        PromptRequest(
            prompt=args.prompt,
            work_dir=args.work_dir,
            session_mode=args.session_mode,
            session_id=args.session_id,
            timeout_seconds=args.timeout,
            model=args.model,
        )
    )


async def _run_once(args: argparse.Namespace):
    settings = load_settings(args.config)
    processor = StorageRequestProcessor(
        settings=settings,
        blob_storage=AzureBlobStorage(settings.storage),
    )
    return await processor.process_once()


async def _run_loop(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    processor = StorageRequestProcessor(
        settings=settings,
        blob_storage=AzureBlobStorage(settings.storage),
    )
    iterations = 0
    while True:
        results = await processor.process_once()
        if results:
            print(json.dumps([result.__dict__ for result in results], ensure_ascii=False))
        iterations += 1
        if args.max_iterations is not None and iterations >= args.max_iterations:
            return
        await asyncio.sleep(settings.storage.poll_interval_seconds)
