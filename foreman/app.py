import base64
import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import click
import pandas as pd
import r3
import tensorboard
from executor import ExternalCommandFailed
from executor.ssh.client import RemoteCommand
from flask import Flask, redirect, render_template, request, send_from_directory, url_for
from tensorboard.backend import application
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

from foreman.job_list import job_list
from foreman.job_tree import job_tree
from foreman.r3_extension import Repository

R3_REPOSITORY = Path(os.environ["R3_REPOSITORY"])
SLURM_DATE_FORMAT = r"%Y-%m-%dT%H:%M:%S"

logging.basicConfig(level=logging.INFO)

app = Flask(
    "app",
    template_folder=Path(__file__).parent / "templates",
    static_folder=Path(__file__).parent / "static",
)
app.register_blueprint(job_list)
app.register_blueprint(job_tree)

joint_app = DispatcherMiddleware(app)

app.config.from_object("foreman.config")


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
    return redirect(url_for("job_list.view"))


@app.route("/jobs/<id>")
def job_details(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    timeline = _get_job_timeline(job.r3_job)
    return render_template("job_details.html", job=job, timeline=timeline)


@app.route("/jobs/<id>/status")
def job_status(id: str):
    repository = Repository.from_environment()
    job = repository.get(id)
    return render_template("job_status.html.jinja", job=job)


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

    repository = Repository.from_environment()
    jobs = sorted(repository.find(query), key=lambda job: job.timestamp, reverse=True)

    return render_template("search_results.html", jobs=jobs)


if __name__ == "__main__":
    main()
