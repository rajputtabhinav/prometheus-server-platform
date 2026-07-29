import asyncio
import argparse

from prometheus_agent.config import AgentSettings
from prometheus_agent.runner import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(prog="prometheus-agent")
    parser.add_argument("--controller-url", dest="controller_url")
    parser.add_argument("--connection-code", dest="connection_code")
    parser.add_argument("--credentials-path", dest="credentials_path")
    parser.add_argument("--server-name", dest="server_name")
    args = parser.parse_args()

    settings = AgentSettings()
    if args.controller_url:
        settings.controller_url = args.controller_url
    if args.connection_code:
        settings.connection_code = args.connection_code
    if args.credentials_path:
        settings.credentials_path = args.credentials_path
    if args.server_name:
        settings.server_name = args.server_name

    asyncio.run(run_agent(settings))


if __name__ == "__main__":
    main()
