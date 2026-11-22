"""XLine Rover backend package.

Integration verification profile admission must run before any application
submodule is imported.  The profile is opt-in, so ordinary production startup
keeps its existing behaviour when the variable is absent.
"""
from .integration_profile import enforce_integration_profile

enforce_integration_profile()
