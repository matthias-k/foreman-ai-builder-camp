"""Provides additional job information for SLURM jobs."""

from typing import Dict, Optional

from executor.ssh.client import ExternalCommandFailed, RemoteCommand

_SLURM_HOSTS = ["slurm2", "galvani"]
_SLURM_CACHE: Optional[Dict[str, str]] = None


def get_slurm_jobs() -> Dict[str, str]:
    """Returns a dictionary of slurm jobs."""
    global _SLURM_CACHE

    if _SLURM_CACHE is None:
        _SLURM_CACHE = {}
        for host in _SLURM_HOSTS:
            _SLURM_CACHE.update(_get_slurm_jobs_from_host(host))
            
    return _SLURM_CACHE


def _get_slurm_jobs_from_host(host: str) -> Dict[str, str]:
    """Returns a dictionary of slurm jobs from a host."""
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
