ARG VARIANT=ubuntu-22.04
FROM mcr.microsoft.com/vscode/devcontainers/base:${VARIANT}

ENV DEBIAN_FRONTEND=noninteractive
ENV PDK_ROOT=/home/vscode/ttsetup/pdk
ENV PDK=gf180mcuD

RUN apt update && apt install -y software-properties-common && add-apt-repository -y ppa:deadsnakes/ppa
RUN apt update && apt install -y iverilog gtkwave python3.11 python3-pip python3.11-venv python3.11-tk python-is-python3 libcairo2 verilator libpng-dev libqhull-dev
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2 && \
    update-alternatives --set python3 /usr/bin/python3.11 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.11 2 && \
    update-alternatives --set python /usr/bin/python3.11

# Clone tt-support-tools
RUN mkdir -p /ttsetup
RUN git clone https://github.com/TinyTapeout/tt-support-tools /ttsetup/tt-support-tools

COPY test/requirements.txt /ttsetup/test_requirements.txt
COPY .devcontainer/copy_tt_support_tools.sh /ttsetup

RUN pip3 install -r /ttsetup/test_requirements.txt -r /ttsetup/tt-support-tools/requirements.txt

# Install verible (for formatting)
RUN umask 022 && \
    curl -L https://github.com/chipsalliance/verible/releases/download/v0.0-3795-gf4d72375/verible-v0.0-3795-gf4d72375-linux-static-x86_64.tar.gz | \
    tar zxf - -C /usr/local --strip-components=1 && \
    chmod 755 /usr/local/bin

# install sv2v
ARG SV2V_VERSION=0.0.13
ARG SV2V_ZIP_NAME=sv2v-Linux.zip
ARG SV2V_ZIP_URL=https://github.com/zachjs/sv2v/releases/download/v${SV2V_VERSION}/${SV2V_ZIP_NAME}
ARG SV2V_ZIP_HASH="552799a1d76cd177b9b4cc63a3e77823a3d2a6eb4ec006569288abeff28e1ff8 ${SV2V_ZIP_NAME}"
RUN mkdir /tmp/sv2v && \
    cd /tmp/sv2v && \
    wget ${SV2V_ZIP_URL} && \
    echo ${SV2V_ZIP_HASH} | sha256sum -c && \
    unzip ${SV2V_ZIP_NAME} && \
    chmod +x sv2v-Linux/sv2v && sudo cp sv2v-Linux/sv2v /usr/local/bin && \
    cd .. && rm -r /tmp/sv2v

# Install LibreLane
RUN pip3 install librelane==2.4.2
