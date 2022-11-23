from pathlib import Path
from pint import UnitRegistry

with open(str(Path(__file__).parent.joinpath('VERSION')), 'r') as fvers:
    __version__ = fvers.read().strip()

ureg = UnitRegistry()
Q_ = ureg.Quantity
