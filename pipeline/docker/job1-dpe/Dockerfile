# DEPRECATED — use docker/dpe-deps/Dockerfile (deps-only, no COPY business code).
# See docker/custom-dpe-image.md and scripts/build_dpe_deps_image.ps1.
# Job1 custom MaxFrame DPE runtime (rosbags only; no maxframe/pyodps SDK)
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV TZ=Asia/Shanghai
ENV MINIFORGE_HOME=/py-runtime
ENV PATH="${MINIFORGE_HOME}/bin:${PATH}"
ENV CONDA_DEFAULT_ENV=py311
ENV MF_PYTHON_EXECUTABLE=/py-runtime/envs/py311/bin/python

RUN apt-get update && \
    apt-get install -y wget ca-certificates locales && \
    locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p ${MINIFORGE_HOME} && \
    rm -f /tmp/miniforge.sh && \
    conda config --remove channels defaults || true && \
    conda config --add channels conda-forge && \
    conda config --set channel_priority strict && \
    conda create -y -n py311 python=3.11 --override-channels -c conda-forge && \
    conda clean -afy

COPY docker/job1-dpe/requirements.txt /tmp/requirements.txt
RUN conda run -n py311 pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY config.yaml /app/config.yaml
COPY clip_id.py /app/clip_id.py
COPY parse_rosbag.py /app/parse_rosbag.py
COPY cloud/job1_worker.py /app/cloud/job1_worker.py

RUN conda run -n py311 python -c "import rosbags; print('rosbags', rosbags.__version__)"

CMD ["conda", "run", "-n", "py311", "python", "/app/cloud/job1_worker.py", "--help"]
