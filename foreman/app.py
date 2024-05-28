import base64
import json
import os
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import click
import pandas as pd
import r3
import tensorboard
from executor import ExternalCommandFailed
from executor.ssh.client import RemoteCommand
from flask import Flask, redirect, render_template, request, send_from_directory
from tensorboard.backend import application
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

R3_REPOSITORY = Path(os.environ["R3_REPOSITORY"])
DATE_FORMAT = r"%Y-%m-%d %H:%M:%S"
SLURM_DATE_FORMAT = r"%Y-%m-%dT%H:%M:%S"

app = Flask("app", template_folder=Path(__file__).parent / "templates")
joint_app = DispatcherMiddleware(app)


@click.command()
@click.option("--host", type=str, default="localhost")
@click.option("--port", type=int, default=5000)
@click.option("--debug", type=bool, default=False)
def main(host, port, debug):
    run_simple(
        host,
        port,
        joint_app,
        use_reloader=debug,
        use_debugger=debug,
        use_evalex=debug,
    )


@app.route("/")
def index():
    repository = r3.Repository(R3_REPOSITORY)

    jobs = {}
    for job in repository.jobs():
        jobs[job.id] = {
            "id": job.id,
            "timestamp": job.timestamp,
            "name": job.metadata.get("name", ""),
            "tags": job.metadata.get("tags", []),
            "path": str(repository.path / "jobs" / job.id),
            "virtual_path": job.metadata.get("path", ""),
        }

    _add_status_information(jobs)

    sorted_uuids = sorted(
        jobs.keys(), key=lambda uuid: jobs[uuid]["timestamp"], reverse=True
    )
    jobs = OrderedDict((uuid, jobs[uuid]) for uuid in sorted_uuids)

    return render_template("jobs.html", r3_repository=R3_REPOSITORY, index=jobs)


def _add_status_information(jobs):
    for host in ["slurm2", "galvani"]:
        command = RemoteCommand(host, r"squeue --me -o '%j %T %r'", capture=True)
        try:
            command.start()
        except ExternalCommandFailed:
            continue

        active_jobs = dict()
        for line in command.output.split("\n")[1:]:
            if len(line) > 1:
                name, state, reason = line.split(" ", maxsplit=2)
                active_jobs[name] = (state, reason)

        for uuid in jobs.keys():
            done_file = R3_REPOSITORY / "jobs" / uuid / "output" / "done"
            if done_file.exists():
                jobs[uuid]["status"] = "done"

            elif uuid in active_jobs:
                status, reason = active_jobs[uuid]
                if status.lower() == "running":
                    jobs[uuid]["status"] = "running"
                else:
                    jobs[uuid]["status"] = status
                    jobs[uuid]["reason"] = reason

            else:
                jobs[uuid]["status"] = "unknown"


def _add_status_information_2(jobs):
    for host in ["slurm2", "galvani"]:
        command = RemoteCommand(host, r"squeue --me -o '%j %T %r'", capture=True)
        try:
            command.start()
        except ExternalCommandFailed:
            continue

        active_jobs = dict()
        for line in command.output.split("\n")[1:]:
            if len(line) > 1:
                name, state, reason = line.split(" ", maxsplit=2)
                active_jobs[name] = (state, reason)

        for revisions in jobs.values():
            for job in revisions:
                done_file = R3_REPOSITORY / "jobs" / job["id"] / "output" / "done"
                if done_file.exists():
                    job["status"] = "done"

                elif job["id"] in active_jobs:
                    status, reason = active_jobs[job["id"]]
                    if status.lower() == "running":
                        job["status"] = "running"
                    else:
                        job["status"] = status
                        job["reason"] = reason

                else:
                    job["status"] = "unknown"


def _get_job_status_and_reason(job):
    done_file = job.path / "output" / "done"
    if done_file.exists():
        return "done", None

    for host in ["slurm2", "galvani"]:
        command = RemoteCommand(host, r"squeue --me -o '%j %T %r'", capture=True)
        try:
            command.start()
        except ExternalCommandFailed:
            continue

        active_jobs = dict()
        for line in command.output.split("\n")[1:]:
            if len(line) > 1:
                name, state, reason = line.split(" ", maxsplit=2)
                active_jobs[name] = (state, reason)
 
        if job.id in active_jobs:
            status, reason = active_jobs[job.id]
            if status.lower() == "running":
                return "running", None
            else:
                return status, reason

    return "unknown", None


@app.route("/tensorboard/open/<uuid>")
def open_in_tensorboard(uuid):
    keys_to_delete = [
        key for key in joint_app.mounts.keys() if key.startswith("/tensorboard")
    ]
    for key in keys_to_delete:
        del joint_app.mounts[key]

    program = tensorboard.program.TensorBoard()
    program.configure(logdir=str(R3_REPOSITORY / "jobs" / uuid))
    (data_provider, deprecated_multiplexer) = program._make_data_provider()
    tensorboard_app = application.TensorBoardWSGIApp(
        program.flags,
        program.plugin_loaders,
        data_provider,
        program.assets_zip_provider,
        deprecated_multiplexer,
    )

    joint_app.mounts[f"/tensorboard/{uuid}"] = tensorboard_app
    return redirect(f"/tensorboard/{uuid}")


@app.route("/fairshare")
def fairshare():
    """Adapted from Matthias K."""
    current_users, current_user_gpus = get_users_and_state()

    command = RemoteCommand("slurm2", r"sshare -a --parsable2", capture=True)
    command.start()

    share_data = pd.read_csv(StringIO(command.output), sep="|")

    share_data['user_id'] = share_data['User'].str.strip()

    for user, user_state in current_users.items():
        share_data.loc[share_data['user_id'] == user, 'active'] = True
        for state, count in user_state.items():
            share_data.loc[share_data['user_id'] == user, state] = count

    for user, user_state in current_user_gpus.items():
        share_data.loc[share_data['user_id'] == user, 'active'] = True
        for state, count in user_state.items():
            share_data.loc[share_data['user_id'] == user, 'GPU_'+state] = count

    for column in ['RUNNING', 'PENDING', 'GPU_RUNNING', 'GPU_PENDING']:
        if column not in share_data.columns:
            share_data[column] = 0
        share_data[column] = share_data[column].fillna(0).astype(int)

    share_data['active'].fillna(False, inplace=True)
    share_data.sort_values('FairShare', inplace=True, ascending=False)

    data = list(enumerate(share_data[share_data['active']].itertuples()))
    return render_template("fairshare.html", data=data)


def get_users_and_state():
    """Adapted from Matthias K."""
    command = RemoteCommand(
        "slurm2", r"squeue --format='%u %T %b %D' --noheader",
        capture=True,
    )
    command.start()

    squeue_lines = [line for line in command.output.split("\n") if len(line) > 0]
    user_jobs = {}
    user_gpus = {}
    for line in squeue_lines:
        user, state, resources, nodes = line.split()
        if 'gpu' in resources:
            gpus = int(resources.rsplit(':', 1)[1])
            # https://bugs.schedmd.com/show_bug.cgi?id=3969
            # nodes = int(nodes)
            # gpus *= nodes
        else:
            gpus = 0
        user_jobs.setdefault(user, []).append(state)
        for _ in range(gpus):
            user_gpus.setdefault(user, []).append(state)

    user_state = {user: Counter(job_states) for user, job_states in user_jobs.items()}
    user_gpus = {user: Counter(gpu_states) for user, gpu_states in user_gpus.items()}
    return user_state, user_gpus


@app.route("/jobs/<uuid>")
def job_details(uuid: str):
    repository = r3.Repository(R3_REPOSITORY)
    job = r3.Job(repository.path / "jobs" / uuid, uuid)
    short_id = uuid.split("-")[0]

    status, reason = _get_job_status_and_reason(job)
    timeline = _get_job_timeline(job)

    return render_template(
        "job_details.html",
        job=job,
        short_id=short_id,
        status=status,
        reason=reason,
        timeline=timeline,
    )


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
                        "status": "pending",
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
                        "status": "pending",
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


@app.route("/jobs/<uuid>/directory_listing/")
@app.route("/jobs/<uuid>/directory_listing/<path:path>")
def directory_listing(uuid: str, path: str = ""):
    complete_path = R3_REPOSITORY / "jobs" / uuid / path

    entries = []

    for child in complete_path.iterdir():
        if child.is_dir():
            url = f"/jobs/{uuid}/directory_listing/{path}/{child.name}"
        else:
            url = f"/jobs/{uuid}/files/{path}/{child.name}"

        entries.append({ "name": child.name, "is_dir": child.is_dir(), "url": url })

    entries = sorted(
        entries,
        key = lambda entry: (not entry["is_dir"], entry["name"].lower())  # type: ignore
    )

    return render_template(
        "directory_listing.html",
        entries=entries,
        name=complete_path.name,
        is_root = path == "",
    )


@app.route("/jobs/<uuid>/files/<path:path>")
def files(uuid: str, path: str = ""):
    complete_path = R3_REPOSITORY / "jobs" / uuid / path

    if path.endswith(".png"):
        with open(complete_path, "rb") as stream:
            content = base64.b64encode(stream.read()).decode("utf-8")

        return render_template(
            "file_image.html",
            content=content,
            uuid=uuid,
            path=str(path).replace("/", " / "),
        )

    if path.endswith(".html"):
        return render_template(
            "file_website.html",
            content_path=f"/static_job_files/{uuid}/{path}",
            uuid=uuid,
            path=str(path).replace("/", " / "),
        )

    known_extensions = {
        "csv": "csv",
        "log": "log",
        "md": "markdown",
        "py": "python",
        "sh": "shell",
        "yaml": "yaml",
        "yml": "yaml",
    }

    extension = path.rsplit(".", maxsplit=1)[-1]

    if extension not in known_extensions:
        return render_template(
            "file_unknown.html",
            uuid=uuid,
            path=str(path).replace("/", " / "),
        )

    else:
        with open(complete_path, "r") as stream:
            content = stream.read()

        return render_template(
            "file.html",
            content=content,
            language=known_extensions[extension],
            read_only=(path != "metadata.yaml"),
            uuid=uuid,
            path=str(path).replace("/", " / "),
        )


@app.route("/static_job_files/<path:path>")
def static_job_files(path):
    return send_from_directory(R3_REPOSITORY / "jobs", path)


@app.route("/search", methods=["GET"])
def search():
    return render_template("search.html")


@app.route("/search", methods=["POST"])
def search_post():
    query_str = request.form["query"]
    try:
        query = json.loads(query_str)
    except json.JSONDecodeError as error:
        return f"Invalid query: {query_str}, {error}"

    repository = r3.Repository(R3_REPOSITORY)
    jobs = repository.find(query)

    results = {}
    for job in jobs:
        results[job.id] = {
            "id": job.id,
            "timestamp": job.timestamp,
            "name": job.metadata.get("name", ""),
            "tags": job.metadata.get("tags", []),
            "path": str(repository.path / "jobs" / job.id),
        }

    _add_status_information(results)

    sorted_uuids = sorted(
        results.keys(), key=lambda uuid: results[uuid]["timestamp"], reverse=True
    )
    jobs = OrderedDict((uuid, results[uuid]) for uuid in sorted_uuids)

    return render_template("search_results.html", results=results)


@app.route("/browse", defaults={"path": ""})
@app.route("/browse/<path:path>")
def browse(path):
    repository = r3.Repository(R3_REPOSITORY)

    if len(path) > 0 and path[-1] != "/":
        path += "/"

    all_jobs = repository.find({ "path": { "$glob": path + "*" } })

    directories = dict()
    jobs = defaultdict(list)

    for job in all_jobs:
        job_path = job.metadata["path"][len(path):]
        if "/" in job_path:
            name = job_path.split("/")[0]
            directories[name] = path + name
        else:
            jobs[job_path].append({
                "id": job.id,
                "timestamp": job.timestamp,
                "name": job.metadata.get("name", ""),
                "tags": job.metadata.get("tags", []),
                "path": str(repository.path / "jobs" / job.id),
            })

    for name in jobs.keys():
        jobs[name] = sorted(jobs[name], key=lambda job: job["timestamp"], reverse=True)

    _add_status_information_2(jobs)
    
    jobs = { key: value for key, value in sorted(jobs.items()) }
    directories = { key: value for key, value in sorted(directories.items()) }

    breadcrumbs = dict()
    if path != "":
        full_path = ""
        for name in path.split("/"):
            if name == "":
                continue
            full_path += name + "/"
            breadcrumbs[name] = full_path

    return render_template(
        "browse.html",
        breadcrumbs=breadcrumbs,
        jobs=jobs,
        directories=directories,
        path=path,
    )


@app.route("/browse_revisions/<path:path>")
def browse_revisions(path: str):
    repository = r3.Repository(R3_REPOSITORY)
    jobs = repository.find({ "path": path })
    jobs = sorted(jobs, key=lambda revision: revision.timestamp, reverse=True)

    revisions = []
    for job in jobs:
        revisions.append({
            "id": job.id,
            "timestamp": job.timestamp,
            "name": job.metadata.get("name", ""),
            "tags": job.metadata.get("tags", []),
            "path": str(repository.path / "jobs" / job.id),
        })

    _add_status_information_2({ "job": revisions })

    breadcrumbs = dict()
    if path != "":
        full_path = ""
        for name in path.split("/"):
            if name == "":
                continue
            full_path += name + "/"
            breadcrumbs[name] = full_path

    return render_template(
        "browse_revisions.html", breadcrumbs=breadcrumbs, revisions=revisions
    )


if __name__ == "__main__":
    main()
