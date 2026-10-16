import json
import os
import pathlib
import resource

print(
    json.dumps(
        {
            "environment": {
                k: v for k, v in os.environ.items() if k.startswith("LAB_")
            },
            "fixtures": [p.name for p in pathlib.Path("/fixtures").iterdir()],
            "memory_bytes": pathlib.Path("/sys/fs/cgroup/memory.max")
            .read_text()
            .strip()
            if pathlib.Path("/sys/fs/cgroup/memory.max").exists()
            else str(resource.getrlimit(resource.RLIMIT_AS)),
        }
    )
)
