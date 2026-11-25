"""Evidence owned by one construction trial; no process/request-global cache."""
from copy import deepcopy
from .cad_canonical_json import canonical_json_hash


class ConstructionEvidence:
    def __init__(self):
        self._reports={}

    def measure(self, verifier, *args, **kwargs):
        # Include complete inputs, not object identity: a modified geometry
        # or source must be measured again, even if the same list was reused.
        try:
            # A verifier may consume measurements from this same trial.
            # Its evidence owner is already implicit in this instance; all
            # semantic inputs (and any foreign context) remain in the key.
            key_kwargs={k:v for k,v in kwargs.items() if not (k=='evidence_context' and v is self)}
            input_hash=canonical_json_hash([args,key_kwargs])
        except (TypeError,ValueError,OverflowError,RecursionError):
            # An optional reuse mechanism must not reject input metadata
            # that the verifier itself accepts but JSON cannot encode.
            return deepcopy(verifier(*args,**kwargs))
        key=(verifier,input_hash)
        if key not in self._reports:
            # Exceptions propagate unchanged and are never cached.
            self._reports[key]=deepcopy(verifier(*args,**kwargs))
        return deepcopy(self._reports[key])
