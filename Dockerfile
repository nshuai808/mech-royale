# Built by the scorer on linux/amd64 with network on (10 min limit, repo <= 20 MB).
# The match runs it with no network, a read-only root (writable /tmp, 64 MB), 1 CPU, 512 MB,
# as uid 65534, with the map mounted read-only at /arena.
#
# Runs the Go bot in giddy/: giddygiddyboy's MIT-licensed Mech Royale bot (see giddy/LICENSE and
# giddy/README.md). Our earlier Python bot (bot.py and friends) stays in the repo but is not in this image.
# Base image pinned by digest so finalist rebuilds are identical.
FROM golang:1.26.1-bookworm@sha256:ab3d6955bbc813a0f3fdf220c1d817dd89c0b3f283777db8ece4a32fe7858edd AS build
WORKDIR /src
COPY giddy/go.mod ./
COPY giddy/mech ./mech
COPY giddy/cmd/bot ./cmd/bot
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /mechbot ./cmd/bot

FROM scratch
COPY --from=build /mechbot /mechbot
ENTRYPOINT ["/mechbot"]
