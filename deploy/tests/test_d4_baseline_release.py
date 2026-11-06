import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "d4_baseline_release.py"
spec = importlib.util.spec_from_file_location("d4_baseline_release_test", path)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_parse_alembic_heads():
    assert release.parse_alembic_heads(
        "20261105_0046 (branchpoint)\n20261106_0047 (head)\n"
    ) == {"20261106_0047"}


def test_parse_alembic_heads_supports_multiple_heads():
    assert release.parse_alembic_heads(
        "20261106_0047 (head)\n20261106_0048 (head)\n"
    ) == {"20261106_0047", "20261106_0048"}


def test_parse_alembic_heads_requires_a_head():
    with pytest.raises(AssertionError, match="Unable to determine"):
        release.parse_alembic_heads("No migrations found")
