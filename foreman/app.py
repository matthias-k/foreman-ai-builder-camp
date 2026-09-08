import logging
import os
from pathlib import Path

import click
import tensorboard
from flask import Flask, redirect, url_for
from tensorboard.backend import application
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

from foreman.job import job
from foreman.job_list import job_list
from foreman.job_tree import job_tree
from foreman.search import search

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
app.register_blueprint(search)

joint_app = DispatcherMiddleware(app)

app.config.from_object("foreman.config")
# Optional machine-specific overrides in foreman/config_local.py (gitignored).
app.config.from_pyfile("config_local.py", silent=True)


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


if __name__ == "__main__":
    main()
