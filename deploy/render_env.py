"""Turn the JSON from `aws ssm get-parameters-by-path` into .env lines.

Usage (see deploy.sh):
    aws ssm get-parameters-by-path --path /survey/prod --with-decryption ... \\
        | python3 render_env.py /survey/prod > .env

Each parameter /survey/prod/NAME becomes NAME='value'. Single quotes make Docker
Compose treat the value literally, so a `$` or `#` in a password is not
interpreted. A value that itself contains a single quote or a newline cannot be
written safely, so the script stops instead of producing a broken file. Error
messages name the parameter but never print a value.
"""

import json
import sys


def render(parameters: list[dict], path: str) -> str:
    prefix = path.rstrip("/") + "/"
    lines = []
    for parameter in sorted(parameters, key=lambda p: p["Name"]):
        full_name = parameter["Name"]
        if not full_name.startswith(prefix):
            raise ValueError(f"{full_name} is not under {prefix}")
        name = full_name[len(prefix) :]
        if not name.isidentifier():
            raise ValueError(f"{full_name}: the last part must be a valid variable name")
        value = parameter["Value"]
        if "'" in value or "\n" in value or "\r" in value:
            raise ValueError(f"{full_name}: value contains a single quote or a line break")
        lines.append(f"{name}='{value}'")
    if not lines:
        raise ValueError(f"no parameters found under {prefix}")
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: render_env.py /parameter/path")
    try:
        sys.stdout.write(render(json.load(sys.stdin)["Parameters"], sys.argv[1]))
    except (ValueError, KeyError) as error:
        sys.exit(f"render_env.py: {error}")


if __name__ == "__main__":
    main()
