import json
from pathlib import Path

import pytest

from cad_copilot.samples import generate


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("samples")
    generate(out, plans=4, parts=2, boards=4, circuits=2)
    return out


@pytest.fixture(scope="session")
def manifests(samples):
    return {p.stem: json.loads(p.read_text()) for p in samples.glob("*.json")}
