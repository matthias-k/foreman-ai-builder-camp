# History

## 2025.08.06
- JavaScript and CSS dependencies are now managed locally by `npm`. Use `make install`
  to install them before running foreman.
- Several improvements regarding the handling of job statuses:
    - Differentiate between failed and completed jobs (before: only "done").
    - Automatically refresh the job status in the virtual browser.
    - Improved styling of the job status badges.
    - Use a config file to define Slurm hosts.
- Internal: Use R3 extension for handling standard job metadata.

## 2024.05.28
The current version of Foreman, separated into its own repository.
