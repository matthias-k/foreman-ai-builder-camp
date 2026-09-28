"""
Job blueprint.

Displays information about individual jobs.
"""
import base64
from datetime import datetime, timedelta

import r3
from executor import ExternalCommandFailed
from executor.ssh.client import RemoteCommand
from flask import Blueprint, render_template, request, send_from_directory, url_for

from foreman.r3_extension import Repository

SLURM_DATE_FORMAT = r"%Y-%m-%dT%H:%M:%S"

job = Blueprint("job", __name__, url_prefix="/job")


@job.route("/view/<id>")
def view(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    timeline = _get_job_timeline(job.r3_job)
    open_file = request.args.get("file")
    return render_template("job/view.html.jinja", job=job, timeline=timeline, open_file=open_file)


@job.route("/view/<id>/dependencies")
def dependencies(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    return render_template("job/dependencies.html.jinja", job=job)


@job.route("/view/<id>/dependencies/upstream")
def dependencies_upstream(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    recursive = request.args.get("recursive") == "true"
    jobs = repository.find_dependencies(job, recursive=recursive)
    return render_template(
        "job/_dependency_list.html.jinja",
        job=job, jobs=jobs, direction="upstream",
        recursive=recursive, table_id="deps-upstream",
    )


@job.route("/view/<id>/dependencies/downstream")
def dependencies_downstream(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    recursive = request.args.get("recursive") == "true"
    jobs = repository.find_dependents(job, recursive=recursive)
    return render_template(
        "job/_dependency_list.html.jinja",
        job=job, jobs=jobs, direction="downstream",
        recursive=recursive, table_id="deps-downstream",
    )


@job.route("/status/<id>")
def status(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    return render_template("job/status.html.jinja", job=job)


@job.route("/view/<id>/directory/")
@job.route("/view/<id>/directory/<path:path>")
def view_directory(id: str, path: str = ""):
    repository = Repository.from_environment()
    job = repository.get(id)
    complete_path = job.r3_job.path / path

    entries = []

    for child in complete_path.iterdir():
        if child.is_dir():
            url = url_for("job.view_directory", id=id, path=f"{path}/{child.name}")
        else:
            url = url_for("job.view_file", id=id, path=f"{path}/{child.name}")

        entries.append({ "name": child.name, "is_dir": child.is_dir(), "url": url })

    entries = sorted(
        entries,
        key = lambda entry: (not entry["is_dir"], entry["name"].lower())  # type: ignore
    )

    return render_template(
        "job/sidebar_files.html.jinja",
        entries=entries,
        name=complete_path.name,
        is_root = path == "",
    )


@job.route("/view/<id>/file/<path:path>")
def view_file(id: str, path: str = ""):
    repository = Repository.from_environment()
    job = repository.get(id)
    complete_path = job.r3_job.path / path

    if path.endswith(".png"):
        with open(complete_path, "rb") as stream:
            content = base64.b64encode(stream.read()).decode("utf-8")

        return render_template(
            "job/file_image.html.jinja",
            content=content,
            uuid=id,
            path=str(path).replace("/", " / "),
        )

    if path.endswith(".html"):
        return render_template(
            "job/file_website.html.jinja",
            content_path=url_for("job.file_contents", path=f"{id}/{path}"),
            uuid=id,
            path=str(path).replace("/", " / "),
        )

    known_extensions = {
        "csv": "csv",
        "json": "json",
        "log": "log",
        "md": "markdown",
        "qmd": "markdown",
        "py": "python",
        "sh": "shell",
        "yaml": "yaml",
        "yml": "yaml",
    }

    extension = path.rsplit(".", maxsplit=1)[-1]

    if extension not in known_extensions:
        return render_template(
            "job/file_unknown.html.jinja",
            uuid=id,
            path=str(path).replace("/", " / "),
        )

    else:
        with open(complete_path, "r") as stream:
            content = stream.read()

        return render_template(
            "job/file_text.html.jinja",
            content=content,
            language=known_extensions[extension],
            read_only=(path != "metadata.yaml"),
            uuid=id,
            path=str(path).replace("/", " / "),
        )


@job.route("/file_contents/<path:path>")
def file_contents(path):
    repository = Repository.from_environment()
    return send_from_directory(repository.r3_repository.path / "jobs", path)


def _get_job_timeline(job: r3.Job):
    starttime = (job.timestamp.date() - timedelta(days=1)).isoformat()

    events_by_slurm_job = dict()

    for host in ["slurm2", "galvani"]:
        command = RemoteCommand(
            host,
            rf"sacct --name {job.path.name} --starttime {starttime} --duplicate -o 'JobId,State,Submit,Start,End' --parsable2",  # noqa: E501
            capture=True,
        )

        try:
            command.start()
        except ExternalCommandFailed:
            continue

        for line in command.output.split("\n")[1:]:
            if len(line) > 1:
                job_id, state, submit, start, end = line.split("|")

                if "." in job_id:
                    continue

                if job_id not in events_by_slurm_job:
                    events_by_slurm_job[job_id] = [{
                        "status": "queued",
                        "datetime": datetime.strptime(submit, SLURM_DATE_FORMAT),
                        "reason": "submitted",
                    }]

                if state == "PREEMPTED":
                    events_by_slurm_job[job_id].append({
                        "status": "running",
                        "datetime": datetime.strptime(start, SLURM_DATE_FORMAT),
                        "reason": "",
                    })
                    events_by_slurm_job[job_id].append({
                        "status": "queued",
                        "datetime": datetime.strptime(end, SLURM_DATE_FORMAT),
                        "reason": "preempted",
                    })

                elif state == "COMPLETED":
                    events_by_slurm_job[job_id].append({
                        "status": "running",
                        "datetime": datetime.strptime(start, SLURM_DATE_FORMAT),
                        "reason": "",
                    })
                    events_by_slurm_job[job_id].append({
                        "status": "done",
                        "datetime": datetime.strptime(end, SLURM_DATE_FORMAT),
                        "reason": "",
                    })

                elif state == "RUNNING":
                    events_by_slurm_job[job_id].append({
                        "status": "running",
                        "datetime": datetime.strptime(start, SLURM_DATE_FORMAT),
                        "reason": "",
                    })

    timeline = [{
        "status": "ready",
        "datetime": job.timestamp,
        "reason": "committed",
        "slurm_job_id": None,
    }]

    for slurm_job_id, events in events_by_slurm_job.items():
        for event in events:
            timeline.append({
                "status": event["status"],
                "datetime": event["datetime"],
                "reason": event["reason"],
                "slurm_job_id": slurm_job_id,
            })

    # Add durations
    for i in range(len(timeline) - 1):
        timeline[i]["duration"] = timeline[i + 1]["datetime"] - timeline[i]["datetime"]

    return timeline
