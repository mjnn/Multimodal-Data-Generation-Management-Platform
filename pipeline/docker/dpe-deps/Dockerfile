# MaxCompute DPE deps-only runtime: rosbag 解析 + OSS 挂载（无业务代码、无 maxframe/pyodps）
# 构建（仓库根目录）:
#   docker build -f docker/dpe-deps/Dockerfile -t <acr>/rosbag-dpe-deps:latest .
# 推送 ACR 后在 MaxCompute 控制台「镜像管理」登记，工作流参数 dpe_image=<登记名>

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
    apt-get install -y wget ca-certificates locales fuse && \
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

RUN mkdir -p /root/.pip && \
    printf '%s\n' \
        '[global]' \
        'index-url = https://mirrors.aliyun.com/pypi/simple/' \
        'trusted-host = mirrors.aliyun.com' \
        > /root/.pip/pip.conf

COPY docker/dpe-deps/requirements.txt /tmp/requirements.txt
RUN conda run -n py311 pip install --no-cache-dir -r /tmp/requirements.txt && \
    conda run -n py311 python -c "import rosbags, yaml; print('rosbags', rosbags.__version__)"

# OSS @with_fs_mount 需要 ossfs2（x86_64）
RUN wget -O /tmp/ossfs2.deb \
        "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260123/ynfgkj/ossfs2_2.0.3.1_linux_x86_64.deb" && \
    dpkg -i /tmp/ossfs2.deb && \
    ossfs2 --version && \
    rm -f /tmp/ossfs2.deb
