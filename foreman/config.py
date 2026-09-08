# Default configuration. For machine-specific overrides, create `config_local.py`
# next to this file (gitignored); its UPPERCASE names take precedence. See config_local.example.py.

# SSH host names of the SLURM head nodes.
SLURM_HOSTS = ["galvani"]

# Cache expiration time in seconds.
SLURM_CACHE_EXPIRATION = 5
