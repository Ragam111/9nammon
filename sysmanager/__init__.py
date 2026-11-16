"""windows-package system manager.

The system manager is the foundation of the project: before adding hardware,
it tells you *where the real bottleneck is* (CPU, memory, swap, disk I/O, or
network) so the optimizer and the AI engine can act on facts, not guesses.

Layers (see README):
    infrastructure  -> OS, PowerShell, security / API keys
    compute         -> HPC scheduling, CPU optimization, memory management
    communication   -> network protocols, IPC, API
    ai engine       -> CLI, agent controller
    web interface   -> dashboard, monitor, log viewer, job queue

The :mod:`sysmanager.monitor` package is the first building block.
"""

__version__ = "0.1.0"
