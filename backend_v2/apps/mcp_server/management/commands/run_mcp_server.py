"""Django management command to start the MCP server."""

import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Start the Kolberg MCP server (stdio transport)"

    def handle(self, *args, **options):
        if not os.environ.get("KOLBERG_JWT_TOKEN", "").strip():
            raise CommandError(
                "KOLBERG_JWT_TOKEN environment variable is not set.\n"
                "Usage: KOLBERG_JWT_TOKEN=<jwt_access_token> python manage.py run_mcp_server"
            )

        from apps.mcp_server.server import run

        self.stdout.write(self.style.SUCCESS("Starting Kolberg MCP server (stdio)…"))
        run()
