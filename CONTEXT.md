# CaberOS Runtime Readiness

Terms used for choosing model offerings and making optional local capabilities
ready without confusing assumptions, estimates, or installed software with facts.

## Language

**Model Offering**:
A model exposed through a particular configured provider, under an exact request
identifier. The same model name through another provider is a different offering.
_Avoid_: Global model identity inferred from a nickname.

**Reported Cost**:
A monetary amount explicitly reported for a model call, distinct from an amount
calculated using a pricing schedule.
_Avoid_: Calling every generated cost estimate an actual charge.

**Estimated Cost**:
A monetary assessment of recorded usage using a specified pricing schedule.
It is not proof of the provider's bill.
_Avoid_: Recovered billing.

**Managed Dependency**:
Optional software whose installation and lifecycle are owned by CaberOS, separate
from software installed and maintained by the operator or operating system.
_Avoid_: System installation.

**Ready Dependency**:
A compatible dependency that supplies the required executables and supporting
resources for a particular capability.
_Avoid_: Downloaded, detected, or installed as synonyms for ready.
