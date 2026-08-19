"""
Integration test against the real Greenhouse public API.

Opt-in: run with `JOBHUNT_INTEGRATION=1 uv run pytest -m integration`.
By default it is skipped so the offline suite stays hermetic.
GREENHOUSE_ORG selects the board (default: a large public Greenhouse customer).
"""
import os

import pytest

from jobhunt.sources.greenhouse import GreenhouseAdapter

pytestmark = pytest.mark.integration

REQUIRE_INTEGRATION = os.environ.get("JOBHUNT_INTEGRATION") == "1"
ORG = os.environ.get("GREENHOUSE_ORG", "stripe")


@pytest.mark.skipif(not REQUIRE_INTEGRATION, reason="set JOBHUNT_INTEGRATION=1 to run")
def test_real_greenhouse_board_returns_jobs():
    adapter = GreenhouseAdapter()
    jobs = adapter.get_jobs(ORG, limit=10)

    assert isinstance(jobs, list)
    assert len(jobs) > 0, f"no jobs returned for Greenhouse org '{ORG}'"

    for job in jobs:
        assert job.id
        assert job.title
        assert job.company
        assert job.source == "greenhouse"
        # Greenhouse always provides a board URL.
        assert job.url and ORG in job.url