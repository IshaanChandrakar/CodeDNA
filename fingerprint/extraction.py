"""Extract one explicitly identified compiler configuration without averaging."""

from fingerprint.models import Fingerprint, ResponseMatrix, stable_id


def extract_fingerprint(matrix: ResponseMatrix, *, configuration_id=None, source_ids=None, pipeline_ids=None, observation_ids=None) -> Fingerprint:
    data = matrix.to_dict()
    selections = (("source_id", source_ids, "sources"), ("pipeline_id", pipeline_ids, "pipelines"),
                  ("id", observation_ids, "observations"))
    observations = data["observations"]
    for field, identifiers, axis in selections:
        if identifiers is not None:
            selected = set(identifiers)
            available = {item["id"] for item in data[axis]}
            if not selected <= available:
                raise ValueError(f"Unknown {axis} identifiers: {sorted(selected - available)}")
            observations = [item for item in observations if item[field] in selected]
    if configuration_id is not None:
        if configuration_id not in {item["id"] for item in data["configurations"]}:
            raise ValueError("Unknown configuration identifier")
        observations = [item for item in observations if item["configuration_id"] == configuration_id]
    configurations = {item["configuration_id"] for item in observations}
    if len(configurations) != 1:
        raise ValueError("A fingerprint requires exactly one configuration and at least one observation; select a configuration explicitly")
    payload = {key: data[key] for key in ("schema_version", "feature_schema", "feature_definitions", "interpretation")}
    payload.update(kind=Fingerprint.KIND, matrix_id=data["matrix_id"], observations=observations)
    for axis, field in (("sources", "source_id"), ("pipelines", "pipeline_id"), ("configurations", "configuration_id")):
        references = {item[field] for item in observations}
        payload[axis] = [item for item in data[axis] if item["id"] in references]
    return Fingerprint({**payload, "fingerprint_id": stable_id("fingerprint", payload)})
