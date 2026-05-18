"""Django management command to start the MCP server."""

import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Start the Kolberg MCP server (stdio transport)"

    def handle(self, *args, **options):
        # Signal that Django is already set up so server.py skips bootstrap.
        os.environ["_DJANGO_SETUP_DONE"] = "1"

        from apps.mcp_server.server import run

        self.stdout.write(self.style.SUCCESS("Starting Kolberg MCP server (stdio)…"))
        run()
