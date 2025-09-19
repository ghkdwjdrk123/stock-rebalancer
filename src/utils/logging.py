from rich.console import Console
from rich.logging import RichHandler
import logging

_console = Console()

def get_logger(name: str = "app") -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, markup=True)],
    )
    return logging.getLogger(name)
