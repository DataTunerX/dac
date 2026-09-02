# Build TDB gateway

The image contains the Rust TDB backend, Node HTTP gateway, PostgreSQL client,
and the V2 migration files used by the Helm init container.

## AMD64

```bash
docker buildx build --platform linux/amd64 \
  -t tdb-gateway:12-amd64 \
  -f docker/Dockerfile.gateway .
```

## ARM64

```bash
docker buildx build --platform linux/arm64 \
  -t tdb-gateway:12-arm64 \
  -f docker/Dockerfile.gateway .
```
