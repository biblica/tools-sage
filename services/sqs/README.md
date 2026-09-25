# SAGE Qualification Service (SQS) — local alpha/beta setup

SQS is the service that qualifies which (model, language, capability) routes SAGE can
trust for governed work. This guide gets a **local, loopback-only** instance running
for beta testing, plus the two SSH-based access paths SAGE uses against it:

- **ADMIN console access** — SSH into the machine running SQS and run `sqs-admin`
  there. There is no separate SSH protocol for this: the console is a plain CLI,
  and "SSH-only" just means access is controlled by who can log into the host, not
  by a web login of its own.
- **Client submission upload** — a SAGE host that vets a qualification (via
  `sage sqs submit`) delivers its result over SCP, authenticated by a dedicated
  SSH keypair, not a password.

This guide covers a single-machine beta setup (the SQS service and the SAGE client
on the same computer, talking over `127.0.0.1`). It does **not** cover a real
production deployment (separate server, TLS, the dedicated `sqs-uploader` system
account, bundle signing) — see [`deploy/systemd/`](deploy/systemd/) and
[`app/docs/superpowers/plans/2026-09-18-SQS-INTEGRATION-PLAN.md`](../../app/docs/superpowers/plans/2026-09-18-SQS-INTEGRATION-PLAN.md)'s
Task 7 for that checklist.

## 1. Prerequisites

- Python 3.12+
- A checkout of this repository (`services/sqs/` and `app/` as siblings — SAGE's
  Codex-workspace bridge depends on that layout; see the module docstring of
  `app/system/src/sage/sqs_provider_bridge.py`)

## 2. Install SQS into its own virtual environment

```sh
cd services/sqs
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 3. Prepare local state directories

SQS never writes inside its own source checkout. Pick a state directory outside the
repo (this guide uses `~/sage-sqs-alpha`):

```sh
mkdir -p ~/sage-sqs-alpha/var/lib/sage-sqs/public
mkdir -p ~/sage-sqs-alpha/var/lib/sage-sqs/incoming
mkdir -p ~/sage-sqs-alpha/var/lib/sage-sqs/incoming-processed
mkdir -p ~/sage-sqs-alpha/var/lib/sage-sqs/incoming-rejected
```

## 4. Start the API server

The server auto-bootstraps its database from `services/sqs/seed/` (language
profiles and the OpenAI model catalog) the first time it starts — nothing else to
run first.

```sh
cd services/sqs
export SQS_DB_PATH=~/sage-sqs-alpha/var/lib/sage-sqs/sqs.db
export SQS_CONFIG_ROOT=$(pwd)/seed
export SQS_BUNDLE_PATH=~/sage-sqs-alpha/var/lib/sage-sqs/public/bundle.json
export SQS_AUTHORITY_ID=biblica-sqs-production
export SQS_PUBLICATION_EPOCH=1
.venv/bin/uvicorn sage_sqs.runtime:create_app_from_env --factory --host 127.0.0.1 --port 8842
```

Leave this running (or launch it in the background with `nohup ... &`). Confirm it
came up:

```sh
curl http://127.0.0.1:8842/health
# {"status":"DEGRADED","service_version":"0.02a1","bundle_revision":0}
```

`DEGRADED` is expected here — nothing has been published yet. That's the next step,
done from the ADMIN console.

## 5. Enable SSH so you can reach the ADMIN console

On macOS: **System Settings → General → Sharing → Remote Login**, toggle on. (Or,
from Terminal: `sudo systemsetup -setremotelogin on` — this needs an interactive
password prompt, so it can't be run for you by an agent.)

Confirm it's listening:

```sh
nc -z -w2 127.0.0.1 22 && echo "SSH is up"
```

## 6. Use the ADMIN console

SSH into the machine running SQS (for this single-machine setup, that's just your
own account on `127.0.0.1`), then run the console with the same environment
variables used to start the server:

```sh
ssh <your-username>@127.0.0.1

# once logged in:
cd path/to/services/sqs
export SQS_DB_PATH=~/sage-sqs-alpha/var/lib/sage-sqs/sqs.db
export SQS_BUNDLE_PATH=~/sage-sqs-alpha/var/lib/sage-sqs/public/bundle.json
export SQS_AUTHORITY_ID=biblica-sqs-production
export SQS_PUBLICATION_EPOCH=1
.venv/bin/sqs-admin
```

From the console's numbered menu you can review attention items, approve language
profiles/models, queue and review evaluations, and publish a bundle (menu item 7 —
required before any qualification is visible to a SAGE client; publishing is
always a separate, explicit step from approving).

## 7. Connect a SAGE host to this SQS instance

On the SAGE side (`app/`), point it at this server:

```sh
export SAGE_SQS_URL=http://127.0.0.1:8842
sage model sqs-sync   # fetches and validates the published bundle
```

To generate the SAGE-side submission keypair (needed before `sage sqs submit` can
upload a result): in the interactive menu, **SAGE MAINTENANCE → SQS submission
key**, or non-interactively:

```python
from pathlib import Path
from sage.sqs_submission_key import generate_submission_keypair
status = generate_submission_keypair(Path("<your SAGE localdata>/state/sqs"))
print(status.public_key)
```

Hand that public key line to whoever runs the SQS server. For this single-machine
setup, that's just appending it to your own `~/.ssh/authorized_keys`:

```sh
cat <path-to-generated>.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

(A real deployment appends it to a dedicated, restricted `sqs-uploader` account's
`authorized_keys` instead — never a personal account. See Task 7 in the
integration plan linked above.)

Configure the upload target in SAGE's `system/config/sqs.yml`:

```yaml
submission:
  ssh_host: 127.0.0.1
  ssh_port: 22
  ssh_user: <your-username>
  remote_incoming_dir: ~/sage-sqs-alpha/var/lib/sage-sqs/incoming
```

## 8. Try the full loop

```sh
sage sqs list                       # what work is pending?
sage sqs submit --run-id <id>       # run it through Codex, SCP the result
```

Then, back at the ADMIN console: menu item 6 (host discoveries) or the attention
queue shows the staged `QUALIFICATION_SUBMISSION`; approving it publishes the
result on the next bundle publish (menu item 7).

## What's not covered here

- Production deployment: a separate server, the systemd units in
  [`deploy/systemd/`](deploy/systemd/), TLS via [`deploy/caddy/`](deploy/caddy/),
  and the dedicated `sqs-uploader` account scoped only to `incoming/`.
- Bundle signing (`require_signature: true` in SAGE's `sqs.yml`) — off by default.
- Authoring new language evaluation packs or seed profiles — that's real
  linguistic work, tracked separately, not a setup step.
