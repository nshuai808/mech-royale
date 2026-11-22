# Built by the scorer on linux/amd64 with network on (10 min limit, repo <= 20 MB).
# The match runs it with no network, a read-only root (writable /tmp, 64 MB), 1 CPU, 512 MB,
# as uid 65534, with the map mounted read-only at /arena.
#
# Runs the Go bot in zoro/: Team Sulertia's "V2" fork (TEMOtkesh/mech-royale-bot, branch v2, 6da1573) of
# Specz04's zoro, both MIT licensed (see zoro/LICENSE and zoro/README.md). Only change: the bot name.
# giddy/ (our previous entry) and the Python bot stay in the repo but are not in this image.
# Toolchain image pinned by digest (the one zoro's own Dockerfile uses) so finalist rebuilds are identical.
FROM golang:1.25.4-alpine3.22@sha256:d3f0cf7723f3429e3f9ed846243970b20a2de7bae6a5b66fc5914e228d831bbb AS build
WORKDIR /src
COPY zoro/go.mod ./
COPY zoro/cmd ./cmd
COPY zoro/internal ./internal
ENV CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOTOOLCHAIN=local
RUN go build -trimpath -ldflags="-s -w" -o /out/zoro ./cmd/zoro

FROM scratch
COPY --from=build /out/zoro /zoro
USER 65534:65534
ENTRYPOINT ["/zoro"]
