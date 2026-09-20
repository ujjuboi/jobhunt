"""
Custom command-palette provider for JobHunt.

Provides a ``Provider`` that yields the app's system commands in a
deterministic, hand-picked order (no alphabetical sorting) so that the
"Quit" action stays at the bottom and the Maximize/Minimize command is
omitted entirely.
"""
from textual.command import DiscoveryHit, Hit, Hits
from textual.system_commands import SystemCommandsProvider


class JobHuntCommandsProvider(SystemCommandsProvider):
    """A command-palette provider that preserves the app's command order.

    Mirrors :class:`~textual.system_commands.SystemCommandsProvider`'s
    ``discover``/``search`` logic but yields ``get_system_commands``
    results **without** sorting so the order set on
    :meth:`~jobhunt.app.JobHuntApp.get_system_commands` is the order
    the user sees.
    """

    async def discover(self) -> Hits:
        """Handle a request for the discovery commands for this provider.

        Yields:
            Commands that can be discovered (not alphabetically sorted).
        """
        for name, help_text, callback, discover in self.app.get_system_commands(
            self.screen
        ):
            if discover:
                yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        """Handle a request to search for system commands that match the query.

        Args:
            query: The user input to be matched.

        Yields:
            Command hits for use in the command palette.
        """
        matcher = self.matcher(query)

        for name, help_text, callback, *_ in self.app.get_system_commands(
            self.screen
        ):
            if (match := matcher.match(name)) > 0:
                yield Hit(
                    match,
                    matcher.highlight(name),
                    callback,
                    help=help_text,
                )
