# 04 — Plugins must be able to change the container image

**Filed:** [lbedner/aegis-stack#1871](https://github.com/lbedner/aegis-stack/issues/1871) - tracker #1872

**Repo:** `aegis-stack` (framework) · **Customers:** `aegis-stack-media`
(ffmpeg), and anything that needs a system tool bigger than a wheel

## Why

A plugin's only packaging lever today is `pyproject_deps`. That is enough
for a Python library and wrong for a system tool: ffmpeg on a slim image,
`poppler-utils`, a 100 MB runtime, a 1 GB model. Bundling those into wheels
is absurd, and `imageio-ffmpeg` (21–27 MB of static binary) is a workaround,
not a design.

The image is built from `Dockerfile.jinja`, whose apt list is a fixed set of
`{% if include_x %}` conditionals. No `_plugins` reference exists in it: a
plugin **cannot** add a package today.

## The trap: do not just loop plugins into the Dockerfile

The obvious change — a `{% for p in _plugins %}` in the apt block — is what
`include_documents` already does for `tesseract-ocr`. It is also a dead end
for plugins, because of how this file is owned:

```jinja
{#- aegis: warn-if-diverged -#}
```

`FilePolicy.WARN_IF_DIVERGED` (`aegis/core/render_diff.py:132`): *"Overwrite
while pristine; once hand-edited, preserve and report rather than merge — the
template only partly owns this file's content (issue #870's Dockerfile: the
htmx css-build stage is template-owned, custom build steps are not, and a
merge could mangle them)."*

So for any project that has ever added a build step — the exact project that
wants ffmpeg, a big runtime, or a model — re-rendering the Dockerfile is
refused, and the plugin's packages would silently never land. A plugin
installed months later cannot depend on a file the user has customized.

## Design: stable hooks, plugin-owned files

Add two hooks **once** to the template Dockerfile, in the template-owned
region above `COPY . /code`. They are fixed text; they never change when a
plugin comes or goes:

```dockerfile
# Packages plugins asked for (docker/apt-packages.txt is assembled from
# the project's plugins). xargs, not sh -c: a package name is never
# interpolated into a shell.
COPY docker/apt-packages.txt /tmp/apt-packages.txt
RUN grep -v '^\s*#' /tmp/apt-packages.txt | xargs -r apt-get install -y --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/apt-packages.txt

# Build steps plugins ship (docker/build.d/<plugin>.sh), in name order.
COPY docker/build.d/ /tmp/build.d/
RUN for step in $(ls /tmp/build.d/*.sh 2>/dev/null | sort); do sh "$step"; done && \
    rm -rf /tmp/build.d
```

Everything a plugin contributes after that is **data**, not a Dockerfile edit:

| file | written by | content |
|---|---|---|
| `docker/apt-packages.txt` | `aegis add`/`remove`, from the answers | `# media` + `ffmpeg`, one per line |
| `docker/build.d/<plugin>.sh` | the plugin's templates (manifest-owned) | e.g. a tarball download + install |

Why this shape:

- **The Dockerfile never diverges again.** A project with custom build steps
  needs the hook pasted in once (the add/remove message prints the snippet and
  why); after that, adding and removing plugins touches only the two hook
  paths.
- **`aegis remove` is clean.** The package list is re-rendered from the
  remaining answers; the script is manifest-owned and deleted.
- **Idempotent and cached.** The package list and scripts sit in their own
  layer above the source copy, so a code change does not reinstall apt
  packages.
- **No shell injection surface.** Apt names are validated
  (`^[a-z0-9][a-z0-9+.-]*$`) and fed through `xargs -a`, never a shell string.
  Scripts are plugin code, which the user already runs at `aegis add` time.

## Spec surface

```python
docker_packages: list[str] = field(default_factory=list)
"""apt packages this plugin needs in the app image (ffmpeg, poppler-utils)."""

docker_steps: list[str] = field(default_factory=list)
"""Build scripts the plugin ships at ``docker/build.d/<name>.sh``, run in
order. For what apt does not have: a tarball, an installer, a downloaded
runtime."""
```

Composer (`aegis/core/plugins/composer.py`) serializes both into the answers
so the two hook files render from them. `aegis plugins info` lists them, and
`aegis remove` reports what it took back out.

## Size tiers (the rule that keeps images sane)

| need | where |
|---|---|
| a Python library | `pyproject_deps` (today) |
| a system tool, tens of MB | `docker_packages` (ffmpeg, poppler, imagemagick) |
| a tool apt does not have, ~100 MB | `docker_steps` + a script |
| 500 MB–1 GB (model, GPU runtime, another language) | **not the app image**: `docker_services` with the plugin's own Dockerfile (`docker/<name>/Dockerfile`), talked to over HTTP or a mounted socket |

The last row matters: `docker_services` already exists and renders arbitrary
compose YAML (`docker-compose.yml.jinja:545`), so a big tool can ship as its
own image today with no framework change. What is missing is the *documented*
path and an example, because the alternative — a 1 GB app image rebuilt for
every code change — is what people do by default.

## Done when

- `aegis add media` on a **pristine** and on a **diverged** Dockerfile both
  end with the plugin's package installed; the diverged case prints the hook
  snippet once with a reason, not a silent skip.
- `aegis add` twice adds the package once (idempotent), and `aegis remove`
  removes exactly the plugin's lines and its script.
- Adding a second plugin that needs the same package does not duplicate it.
- A plugin script that fails the build fails it with the step's name in the
  error.
- `tests/core/test_render_diff_transition_coverage.py` covers the two new
  paths, and a generation test asserts both hooks exist in every stack that
  builds a Dockerfile.
- `docs/plugins/creating.md` gains the fields, the four tiers, and a working
  example of a `docker_steps` script.

## Rejected alternatives

- **Loop `_plugins` into the apt block.** Works only while pristine; fails
  exactly for the projects that need it (see the trap above).
- **Arbitrary `RUN` strings in the spec.** Same divergence problem, plus a
  `RUN` line a plugin injects is unreadable in review and unvalidatable.
- **A plugin's own Dockerfile that the project's `FROM`s.** Would need a
  per-plugin `FROM` line — a Dockerfile edit again — and image chaining
  surprises everyone who reads the project's build.
- **Mounting `/var/run/docker.sock` and installing at runtime.** No reproducible
  image, no cache, and it hands the container the host.

## Migration once this lands

`aegis-stack-media` drops `imageio-ffmpeg` for `docker_packages=["ffmpeg"]`:
`pyproject_deps` becomes `["alembic>=1.13"]`, the app image gains ~60 MB of
apt ffmpeg (shared by anything else that wants it), and the adapter keeps
`shutil.which("ffmpeg")` for dev hosts that have their own. Ticket 23's
Pillow work is unaffected.
