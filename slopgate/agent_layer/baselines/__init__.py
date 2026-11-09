"""Register SlopGate benchmark systems."""

from .base import REGISTRY, Skipped, System, build, register  # noqa: F401

from . import b0_grep    # noqa: F401
from . import b1_rules   # noqa: F401
from . import b2_single  # noqa: F401
from . import b3_fixed   # noqa: F401

from .. import agent     # noqa: F401