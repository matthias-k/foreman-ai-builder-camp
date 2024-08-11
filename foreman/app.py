import json
import logging
import os
from collections import Counter
from io import StringIO
from pathlib import Path

import click
import pandas as pd
import tensorboard
from executor.ssh.client import RemoteCommand
from flask import Flask, redirect, render_template, request, url_for
from tensorboard.backend import application
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

from foreman.job import job
from foreman.job_list import job_list
from foreman.job_tree import job_tree
from foreman.r3_extension import Repository

R3_REPOSITORY = Path(os.environ["R3_REPOSITORY"])

logging.basicConfig(level=logging.INFO)

app = Flask(
    "app",
    template_folder=Path(__file__).parent / "templates",
    static_folder=Path(__file__).parent / "static",
)
app.register_blueprint(job)
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
