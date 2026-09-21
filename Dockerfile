# syntax=docker/dockerfile:1.27

# For maximum integrity, set this to an immutable digest in CI/CD.
ARG SWIPL_IMAGE=docker.io/library/swipl:10.0.2

FROM ${SWIPL_IMAGE} AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/opt/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/opt/sentence_transformers

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      git \
      build-essential \
      cmake \
      pkg-config \
      python3 \
      python3-dev \
      python3-pip \
      libopenblas-dev \
      libblas-dev \
      liblapack-dev \
      gfortran \
      libgflags-dev \
      nano \
 && rm -rf /var/lib/apt/lists/*

# Build dependencies from source. Pin refs at build time for reproducibility.
ARG PETTA_REPO=https://github.com/trueagi-io/PeTTa.git
ARG PETTA_REF=v1.0.4
ARG FAISS_REPO=https://github.com/facebookresearch/faiss.git
ARG FAISS_REF=v1.8.0
ARG CHROMADB_REPO=https://github.com/patham9/petta_lib_chromadb.git
ARG CHROMADB_REF=master

# Embedding model to pre-download at build time.
ARG EMBEDDING_MODEL=intfloat/e5-large-v2

RUN git clone --depth 1 --branch "${PETTA_REF}" "${PETTA_REPO}" /PeTTa
RUN git clone --depth 1 --branch "${FAISS_REF}" "${FAISS_REPO}" /faiss

WORKDIR /faiss
RUN cmake -B build -DFAISS_ENABLE_GPU=OFF -DFAISS_ENABLE_PYTHON=OFF -DBUILD_SHARED_LIBS=OFF \
 && cmake --build build --config Release --parallel \
 && cmake --install build

WORKDIR /PeTTa
RUN sh build.sh
RUN mkdir -p /PeTTa/repos \
 && git clone --depth 1 --branch "${CHROMADB_REF}" "${CHROMADB_REPO}" /PeTTa/repos/petta_lib_chromadb

COPY ./requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --break-system-packages \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple/ \
    torch==2.12.1 \
 && python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Pre-download the sentence-transformers model so runtime does not need network access.
RUN mkdir -p "${HF_HOME}" "${SENTENCE_TRANSFORMERS_HOME}" \
 && python3 - <<PY
from sentence_transformers import SentenceTransformer
model_name = "${EMBEDDING_MODEL}"
print(f"Downloading embedding model: {model_name}")
SentenceTransformer(model_name)
print("Model download complete.")
PY

FROM builder AS versioned-source

WORKDIR /omega-source
COPY . .
RUN : > /tmp/omega-ignored-tracked \
 && if [ -e .git ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      git ls-files -ci --exclude-from=.dockerignore -z > /tmp/omega-ignored-tracked; \
      git checkout-index --force --stdin -z < /tmp/omega-ignored-tracked; \
    fi \
 && python3 -c 'from src.helper import omega_version; print(omega_version())' > /tmp/omega-version \
 && mv /tmp/omega-version ./version \
 && while IFS= read -r -d '' path; do rm -f -- "$path"; done < /tmp/omega-ignored-tracked \
 && rm -rf ./.git \
 && chmod 0444 ./version

FROM ${SWIPL_IMAGE} AS runtime

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/opt/sentence_transformers

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      python3 \
      libopenblas-dev \
      libblas-dev \
      liblapack-dev \
      gfortran \
      libgflags-dev \
      nano \
      git \
      nginx-light \
      gettext-base \
      poppler-utils \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /PeTTa

COPY --from=builder /usr/local /usr/local
COPY --from=builder /PeTTa /PeTTa
COPY --from=builder /opt/huggingface /opt/huggingface
COPY --from=builder /opt/sentence_transformers /opt/sentence_transformers

# setup nginx proxy
RUN usermod -a -G tty www-data
RUN mkdir /opt/nginx
RUN chown www-data:www-data /opt/nginx
RUN chmod 0700 /opt/nginx
COPY --chown=www-data:www-data --chmod=0600 ./proxy/* /opt/nginx/

ENV OMEGA_DIR=/PeTTa/repos/Omega
ENV MEMORY_DIR=${OMEGA_DIR}/memory
# Start defaults for import-kb
ENV IMPORT_KB_ON_START=0

# Bring in the clean source tree and its version generated from Git metadata.
COPY --from=versioned-source /omega-source ${OMEGA_DIR}

RUN cp ${OMEGA_DIR}/run.metta /PeTTa/run.metta \
 && mkdir -p ${MEMORY_DIR}/chroma_db \
 && mkdir -p /memory-transfer \
 && ln -s ${MEMORY_DIR}/chroma_db ./chroma_db \
 && chmod +x ${OMEGA_DIR}/entrypoint.sh \
 && chmod +x ${OMEGA_DIR}/scripts/import_knowledge.sh \
 && chmod +x ${OMEGA_DIR}/scripts/omega \
 && chown -R 65534:65534 ${MEMORY_DIR} \
 && chown 65534:65534 /memory-transfer \
 && chmod 0700 /memory-transfer \
 && find ${MEMORY_DIR} -type f -exec chmod 0644 {} \; \
 && chmod 0444 ${MEMORY_DIR}/prompt.txt \
 && chown -R 65534:65534 /opt/huggingface /opt/sentence_transformers

ENTRYPOINT ["/PeTTa/repos/Omega/entrypoint.sh"]
CMD []
