# Foreman

Foreman is a Web UI for browsing and managing the jobs in an R3 repository.


## Installation
```bash
make install
```

Usually, foreman will run on an external server. I found the following alias useful to
start foreman from my local machine:

```bash
# Replace `server` with the hostname of the server running foreman
alias foreman="ssh -t -L ${PORT:-5000}:localhost:${PORT:-5000} ${HOST:-server} python -m foreman.app --port ${PORT:-5000}"
```


## Versioning
Updates to Foreman happen sporadically based on my needs and time. The versioning is
based on the date of the last update in the format `YYYY.MM.DD`.

Have a look at the [HISTORY.md](HISTORY.md) for a list of changes.
