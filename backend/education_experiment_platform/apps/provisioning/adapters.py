from dataclasses import dataclass, field

from .ports import RuntimeAdapter, RuntimeInventoryItem, RuntimeResult, RuntimeSpec


class FakeRuntimeFailure(RuntimeError):
    def __init__(
        self, code: str, *, partial: bool = False, result: RuntimeResult | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.partial = partial
        self.result = result


@dataclass
class FakeRuntimeAdapter:
    """Deterministic local adapter used by P07 tests and local Compose."""

    failures: dict[str, str] = field(default_factory=dict)
    timeouts: set[str] = field(default_factory=set)
    partial_success: set[str] = field(default_factory=set)
    instances: dict[str, RuntimeResult] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def _step(self, stage: str) -> FakeRuntimeFailure | None:
        self.calls.append((stage, "call"))
        if stage in self.timeouts:
            raise TimeoutError(f"FAKE_{stage}_TIMEOUT")
        if stage in self.failures:
            failure = FakeRuntimeFailure(
                self.failures[stage], partial=stage in self.partial_success
            )
            if failure.partial:
                return failure
            raise failure
        return None

    def preflight(self, spec: RuntimeSpec) -> RuntimeResult:
        failure = self._step("QUOTA_CHECK")
        if failure:
            raise failure
        return RuntimeResult(external_id=f"fake-preflight:{spec.task_id}")

    def prepare_image(self, spec: RuntimeSpec) -> None:
        failure = self._step("IMAGE_PREPARE")
        if failure:
            raise failure

    def attach_network(self, spec: RuntimeSpec) -> None:
        failure = self._step("NETWORK_ATTACH")
        if failure:
            raise failure

    def create(self, spec: RuntimeSpec, idempotency_key: str) -> RuntimeResult:
        failure = self._step("CREATE")
        existing = self.instances.get(idempotency_key)
        if existing is not None:
            if failure:
                raise failure
            return existing
        result = RuntimeResult(
            external_id=f"fake-instance:{spec.task_id}:{idempotency_key[:12]}",
            endpoint=f"http://fake-runtime.local/{spec.task_id}",
            metadata={"driver": "FAKE", "idempotency_key": idempotency_key},
        )
        self.instances[idempotency_key] = result
        if failure:
            raise FakeRuntimeFailure(failure.code, partial=True, result=result)
        return result

    def status(self, external_id: str) -> str:
        failure = self._step("BOOT_PROBE")
        if failure:
            raise failure
        return (
            "READY"
            if any(item.external_id == external_id for item in self.instances.values())
            else "ABSENT"
        )

    def endpoint(self, external_id: str) -> str:
        failure = self._step("WORKSPACE_READY")
        if failure:
            raise failure
        for result in self.instances.values():
            if result.external_id == external_id:
                return result.endpoint
        return ""

    def snapshot(self, external_id: str) -> str:
        failure = self._step("OPTIONAL_SNAPSHOT")
        if failure:
            raise failure
        return f"fake-snapshot:{external_id}"

    def destroy(self, external_id: str, idempotency_key: str) -> None:
        failure = self._step("DESTROY_RUNTIME")
        if failure:
            raise failure
        for key, result in list(self.instances.items()):
            if result.external_id == external_id:
                self.instances.pop(key, None)
                break

    def inventory(self) -> list[RuntimeInventoryItem]:
        return [
            RuntimeInventoryItem(
                external_id=item.external_id,
                status="READY",
                metadata=dict(item.metadata),
            )
            for item in self.instances.values()
        ]


_fake_runtime = FakeRuntimeAdapter()


def fake_runtime() -> FakeRuntimeAdapter:
    return _fake_runtime


def reset_fake_runtime() -> None:
    _fake_runtime.failures.clear()
    _fake_runtime.timeouts.clear()
    _fake_runtime.partial_success.clear()
    _fake_runtime.instances.clear()
    _fake_runtime.calls.clear()


def runtime_for_driver(driver: str) -> RuntimeAdapter:
    if driver == "FAKE":
        return _fake_runtime
    raise RuntimeError("RUNTIME_ADAPTER_NOT_IMPLEMENTED")
