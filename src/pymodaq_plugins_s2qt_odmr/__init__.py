from pathlib import Path
from pint import UnitRegistry
from pymodaq.utils.logger import set_logger  # to be imported by other modules.

with open(str(Path(__file__).parent.joinpath('VERSION')), 'r') as fvers:
    __version__ = fvers.read().strip()

ureg = UnitRegistry()
Q_ = ureg.Quantity
