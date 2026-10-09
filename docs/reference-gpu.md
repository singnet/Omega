# Reference - GPU Support (Experimental)

> **Experimental.** GPU support is under testing and is not included in Omega
> releases yet; it is planned for a future release. Released images and
> `scripts/omega start` do not give the agent GPU access. To try it, build the
> image from the `devices-landlock-fix` branch and start the container with
> your own `docker run` command, as described below.

## Host setup

### Native Linux

1. Install the NVIDIA driver for your distribution and reboot. `nvidia-smi -L`
   on the host must list your GPUs.
2. Install the
   [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
3. Register the toolkit with Docker and restart Docker:

   ```sh
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

4. Check that CDI is enabled in Docker: `docker info --format '{{json .CDISpecDirs}}'`
   must print a non-empty list. If it does not, enable it and restart Docker:

   ```sh
   sudo nvidia-ctk runtime configure --runtime=docker --cdi.enabled=true
   sudo systemctl restart docker
   ```

5. Check the CDI specification: `nvidia-ctk cdi list` must print
   `nvidia.com/gpu=...` entries. Recent toolkit versions keep it up to date with
   `nvidia-cdi-refresh.service`; otherwise generate it:

   ```sh
   sudo nvidia-ctk cdi generate --output=/var/run/cdi/nvidia.yaml
   ```

   Regenerate the specification after every driver update.

### Windows with WSL2

1. Install the NVIDIA driver on Windows. Do not install a Linux NVIDIA driver
   inside the WSL distribution: WSL exposes the Windows driver as `/dev/dxg`
   and the libraries in `/usr/lib/wsl/lib`.
2. Install Docker Engine and the NVIDIA Container Toolkit inside the WSL
   distribution and follow steps 2-5 of the native Linux setup.

### SELinux (Fedora, RHEL and derivatives)

When Docker runs with SELinux labeling, containers may be denied access to the
GPU device nodes even though the nodes exist, and `nvidia-smi` fails inside the
container. Allow containers to use devices:

```sh
sudo setsebool -P container_use_devices on
```

### Other setups

- **Rootless Docker** needs extra toolkit configuration, see the rootless mode
  section of the NVIDIA Container Toolkit install guide.
- **Docker Desktop** and **Podman** are not covered by these instructions.

## Build the image

Build the image from the `devices-landlock-fix` branch. Its security policy
allows the agent to use the GPU; images built from other branches do not.

```sh
git clone https://github.com/singnet/Omega.git
cd Omega
git checkout devices-landlock-fix
docker build -t omega:gpu .
```

## Start the container

Start the container with your own command and pass the GPUs with
`--device nvidia.com/gpu=all`, or a single GPU by its CDI name from
`nvidia-ctk cdi list`, for example `--device nvidia.com/gpu=0`. The other
options match the ones `scripts/omega` uses. Example for Telegram and OpenAI,
with `OPENAI_API_KEY`, `TG_BOT_TOKEN` and `OMEGA_AUTH_SECRET` exported in your
shell:

```sh
docker rm -f omega
docker run -d -it \
  --name omega \
  --init \
  --security-opt no-new-privileges:true \
  --add-host=host.docker.internal:host-gateway \
  --tmpfs /tmp:size=64m,mode=1777 \
  --tmpfs /var/tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --volume omega-memory:/PeTTa/repos/Omega/memory \
  --device nvidia.com/gpu=all \
  -e OPENAI_API_KEY \
  -e TG_BOT_TOKEN \
  -e OMEGA_AUTH_SECRET \
  omega:gpu
```

Do not restart this container with `scripts/omega start`: it recreates the
container without the GPU options. `docker stop omega` and `docker start omega`
keep them.
