"""R3 extension for Foreman."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import r3

from foreman.slurm import get_slurm


class Job:
    """Extended R3 job."""

    def __init__(self, r3_job: r3.Job) -> None:
        self.r3_job = r3_job
        self.status = self._get_status()

    @property
    def id(self) -> str:
        """Returns the ID of this job."""
        return self.r3_job.id

    @property
    def path(self) -> Path:
        """Returns the path of this job."""
        return self.r3_job.path

    @property
    def timestamp(self) -> datetime:
        """Returns the timestamp of this job."""
        return self.r3_job.timestamp

    @property
    def origin(self) -> Optional[str]:
        """Returns the origin of this job."""
        return self.r3_job.metadata.get("origin", None)

    @property
    def virtual_path(self) -> Optional[str]:
        """Returns the virtual path of this job."""
        return self.r3_job.metadata.get("path", None)

    @property
    def name(self) -> Optional[str]:
        """Returns the name of this job."""
        return self.r3_job.metadata.get("name", None)

    @property
    def description(self) -> Optional[str]:
        """Returns the description of this job."""
        return self.r3_job.metadata.get("description", None)

    @property
    def tags(self) -> list[str]:
        """Returns the tags of this job."""
        return self.r3_job.metadata.get("tags", [])

    @property
    def has_report(self) -> bool:
        """Returns whether this job has a report.html in its output."""
        return (self.path / "output" / "report.html").exists()

    def _get_status(self) -> str:
        if (self.path / "output" / "done").exists():
            with open(self.path / "output" / "done") as file:
                status = file.read().strip()
            if len(status) > 0:
                return status
            else:
                return "done"

        slurm_jobs = get_slurm().get_jobs()
        slurm_status = slurm_jobs.get(self.id, None)
        if slurm_status == "PENDING":
            return "queued"
        if slurm_status == "RUNNING":
            return "running"

        return "ready"


class Repository():
    """Extended R3 repository."""

    def __init__(self, r3_repository: r3.Repository) -> None:
        self.r3_repository = r3_repository

    def jobs(self) -> Iterable[Job]:
        """Returns an iterator over all jobs in this repository."""
        for r3_job in self.r3_repository.jobs():
            yield Job(r3_job)

    def find(self, query: Dict[str, Any], latest: bool = False) -> list[Job]:
        """Returns an iterator over all jobs that match a query."""
        r3_jobs = self.r3_repository.find(query, latest)
        return [Job(r3_job) for r3_job in r3_jobs]

    def find_dependents(self, job: Job, recursive: bool = False) -> list[Job]:
        """Returns the jobs that depend on the given job.

        Direct dependents; pass recursive=True for transitive dependents.
        """
        r3_jobs = self.r3_repository.find_dependents(job.r3_job, recursive=recursive)
        jobs = [Job(r3_job) for r3_job in r3_jobs]
        return sorted(jobs, key=lambda j: (j.virtual_path or "", j.id))

    def find_dependencies(self, job: Job, recursive: bool = False) -> list[Job]:
        """Returns the jobs the given job depends on.

        Direct dependencies; pass recursive=True for transitive dependencies.
        Git dependencies are ignored (this returns jobs only).
        """
        result: Dict[str, Job] = {}

        def visit(current: Job) -> None:
            for dependency in current.r3_job.dependencies:
                if not isinstance(dependency, r3.JobDependency):
                    continue  # skip git dependencies
                if dependency.job in result:
                    continue  # already collected (also dedups diamonds)
                try:
                    dependency_job = self.get(dependency.job)
                except FileNotFoundError:
                    continue  # dependency job no longer in the repo; skip it
                result[dependency.job] = dependency_job
                if recursive:
                    visit(dependency_job)

        visit(job)
        return sorted(result.values(), key=lambda j: (j.virtual_path or "", j.id))

    def get(self, job_id: str) -> Job:
        """Returns a job by its ID."""
        return Job(self.r3_repository._storage.get(job_id))

    @classmethod
    def from_environment(cls) -> "Repository":
        """Creates a repository from the `R3_REPOSITORY` environment variable."""
        if "R3_REPOSITORY" not in os.environ:
            raise ValueError("R3_REPOSITORY environment variable is not set.")
        return cls(r3.Repository(os.environ["R3_REPOSITORY"]))
