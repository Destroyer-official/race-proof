# Extending RaceProof

RaceProof is built with a future-proof, modular registry architecture.
You can extend it with new **ingestion adapters**, **custom analysis engines**, or **domain invariant rules** without modifying existing core files.

---

## 1. Creating a Custom Ingestion Adapter

All adapters inherit from `BaseAdapter` and normalize source files into `list[RaceSession]`.

```python
from pathlib import Path
from race_proof.ingestion.base import BaseAdapter
from race_proof.models import RaceSession, RaceRequest, RaceResponse
from race_proof.registry import AdapterRegistry

@AdapterRegistry.register("my_custom_tool")
class MyCustomAdapter(BaseAdapter):
    """Parses exported logs from MyCustomTool."""

    def parse(self, file_path: Path | str) -> list[RaceSession]:
        p = Path(file_path)
        # Parse data from file
        ...
        session = RaceSession(
            id="session_001",
            tool_source="my_custom_tool",
            baseline=baseline_resp,
            race_responses=concurrent_resps,
        )
        return [session]
```

---

## 2. Defining Custom Invariant Rules (YAML)

Custom invariant rules allow organizations to define business constraints evaluated via JMESPath expressions:

```yaml
rules:
  - id: FINTECH_NO_OVERDRAFT
    description: "Account balance must never drop below 0"
    target_field: "body.balance"
    operator: "all_gte"
    threshold: 0
    severity: "CRITICAL"

  - id: COUPON_SINGLE_WINNER
    description: "Coupon redemption must produce at most one 200 OK"
    target_field: "status_code"
    operator: "count_eq"
    threshold: 1
    match_value: 200
    severity: "HIGH"
```

### Supported Operators:
- `single_200_winner`: Ensures exactly one request in the burst returns HTTP 200.
- `all_gte` / `all_lte`: Evaluates inequalities on numeric JSON fields.
- `unique`: Verifies that returned transaction/order tokens are strictly distinct.
- `state_stall`: Detects stale read snapshots (consecutive identical state responses).
- `sum_eq`: Verifies conservation of invariants (e.g. total balance after transfer).

---

## 3. Creating a Custom Analysis Engine

You can plug in custom statistical tests or domain models using `EngineRegistry`:

```python
from race_proof.models import RaceSession, DimensionResult, AnalysisDimension
from race_proof.registry import EngineRegistry

@EngineRegistry.register("my_statistical_engine")
class MyCustomEngine:
    """Custom temporal clustering test."""

    def analyze(self, session: RaceSession) -> DimensionResult:
        # Perform computation...
        return DimensionResult(
            dimension=AnalysisDimension.TEMPORAL_OVERLAP,
            confidence=0.95,
            details="Temporal overlap confirmed across 12 requests within 0.4ms window.",
            raw_metrics={"window_ms": 0.4},
        )
```

