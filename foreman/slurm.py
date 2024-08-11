"""Provides additional job information for SLURM jobs."""

import logging
from typing import Dict

import flask
from diskcache import Cache
from executor.ssh.client import ExternalCommandFailed, RemoteCommand

LOGGER = logging.getLogger(__name__)

CACHE = Cache()


def get_slurm():
    if "slurm" not in flask.g:
        flask.g.slurm = Slurm(
            flask.current_app.config["SLURM_HOSTS"],
            cache_experiation=flask.current_app.config["SLURM_CACHE_EXPIRATION"],
        )

    return flask.g.slurm


class Slurm:
    """Provides additional information from SLURM."""

    def __init__(self, hosts: list[str], cache_experiation: int = 5) -> None:
        self.hosts = hosts
        self._cache_expiration = cache_experiation

        if cache_experiation > 0:
            memoize = CACHE.memoize(expire=cache_experiation)
            self._get_jobs_from_host = memoize(self._get_jobs_from_host)  # type: ignore

    @property
    def cache_experation(self) -> int:
        return self._cache_expiration

    def get_jobs(self) -> Dict[str, str]:
        jobs = {}
        for host in self.hosts:
            jobs.update(self._get_jobs_from_host(host))
        return jobs

    def _get_jobs_from_host(self, host: str) -> Dict[str, str]:
        """Returns a dictionary of slurm jobs from a host."""
        LOGGER.info("Getting slurm jobs from %s.", host)

        command = RemoteCommand(host, r"squeue --me -o '%j %T'", capture=True)

        try:
            command.start()
        except ExternalCommandFailed:
            return {}

        jobs = {}
        for line in command.output.splitlines()[1:]:
            job_id, status = line.split()
            jobs[job_id] = status

        return jobs
