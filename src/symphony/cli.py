from __future__ import annotations

import argparse
import asyncio
import logging

from .orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Symphony orchestrator")
    parser.add_argument("--workflow", default=None, help="Path to WORKFLOW.md")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    orchestrator = Orchestrator(args.workflow)
    asyncio.run(orchestrator.run_forever())


if __name__ == "__main__":
    main()
