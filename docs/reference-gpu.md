# Reference - GPU Support (Experimental)

> **Experimental.** GPU support is under testing. Neither `scripts/omega start`
> nor the default security policy `profile/policy.yaml` gives the agent GPU
> access. To try it, build the image from the repository and start the
> container with your own `docker run` command that passes the GPUs and
> selects `profile/policy-gpu.yaml`, as described below.

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

Build the image from the repository. It contains the GPU policy
`profile/policy-gpu.yaml`; images released before the policy was added do not.

```sh
git clone https://github.com/singnet/Omega.git
cd Omega
docker build -t omega:gpu .
```

### PyTorch with CUDA

The image installs the CPU-only build of PyTorch, see the `--index-url` option
in [Dockerfile](../Dockerfile). Device access alone does not change that:
`nvidia-smi` and the CUDA driver API work inside the container, but
`torch.cuda.is_available()` stays `False`. To let PyTorch use the GPU, point
the option at the CUDA build matching your driver before building the image,
for example:

```diff
-    --index-url https://download.pytorch.org/whl/cpu \
+    --index-url https://download.pytorch.org/whl/cu130 \
```

The builds published for the pinned PyTorch version are listed at
[download.pytorch.org/whl](https://download.pytorch.org/whl/). The CUDA ones
are large, a few gigabytes to download instead of about 200 MB, and the image
grows accordingly. Check the result after the container starts:

```sh
docker exec omega python3 -c 'import torch; print(torch.cuda.is_available(), torch.cuda.device_count())'
```

## Start the container

Start the container with your own command and pass the GPUs with
`--device nvidia.com/gpu=all`, or a single GPU by its CDI name from
`nvidia-ctk cdi list`, for example `--device nvidia.com/gpu=0`. The other
options and the agent arguments match the ones `scripts/omega` uses, except
for `securityPolicyPath`, which selects the GPU policy. Example for Telegram
and OpenAI, with `OPENAI_API_KEY`, `TG_BOT_TOKEN` and `OMEGA_AUTH_SECRET`
exported in your shell:

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
  omega:gpu \
  commchannel=telegram \
  provider=OpenAI \
  embeddingprovider=OpenAI \
  securityPolicyPath=/PeTTa/repos/Omega/profile/policy-gpu.yaml
```

Without the agent arguments the container starts with the defaults from
[config/config.yaml](../config/config.yaml), which means the IRC channel and
the stock security policy, and the agent gets no GPU access.

Do not restart this container with `scripts/omega start`: it recreates the
container without the GPU options. `docker stop omega` and `docker start omega`
keep them.
