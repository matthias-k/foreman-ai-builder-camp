"""Provides additional job information for SLURM jobs."""

from typing import Sequence


class SlurmHost:
    def __init__(self, host: str):
        self.host = host

    def get_status(self, job_id: str | Sequence[str]) -> str:
        if isinstance(job_id, str):
            return self._get_status_for_one_job(job_id)
        else:
            return self._get_status_for_multiple_jobs(job_id)

    def _get_status_for_one_job(self, job_id: str) -> str:
        raise NotImplementedError()


    def _get_status_for_multiple_jobs(self, job_ids: Sequence[str]) -> str:
        raise NotImplementedError()
