ARG S_IMAGE="fedora:41"
ARG S_TOOL="signalbackup-tools"
ARG S_PATH="/opt/${S_TOOL}"
ARG S_GHUB_REPO="bepaald/${S_TOOL}"
ARG S_GHUB="https://github.com/${S_GHUB_REPO}.git"
ARG S_GHUB_REFS_HEAD="https://api.github.com/repos/${S_GHUB_REPO}/git/refs/heads/master"

FROM "${S_IMAGE}" AS build

ARG S_PATH
ARG S_GHUB
ARG S_GHUB_REFS_HEAD

RUN \
dnf -y install \
    gcc-g++ \
    openssl-devel \
    sqlite-devel \
    dbus-devel \
    which \
    git
RUN \
echo "### Setup build structure ###" && \
mkdir -p "${S_PATH}"

ADD "${S_GHUB_REFS_HEAD}" /tmp/version.json
RUN git clone "${S_GHUB}" "${S_PATH}"
RUN cd "${S_PATH}" && \
bash BUILDSCRIPT.bash

FROM "${S_IMAGE}"

ARG S_TOOL
ARG S_PATH
ENV PATH="${S_PATH}:${PATH}"

RUN dnf -y install \
sqlite \
dbus-devel \
openssl

COPY --from=build "${S_PATH}/${S_TOOL}" "${S_PATH}/"

WORKDIR "${S_PATH}"
ENTRYPOINT [ "signalbackup-tools" ]
