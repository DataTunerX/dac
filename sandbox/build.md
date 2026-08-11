# build sandbox images

自定义镜像（SQL/文件/代码打入镜像）。第三方镜像用 `make mirror-images`。

默认：`REGISTRY=release.daocloud.io/dac`，`TAG=v0.11.0`。

```bash
cd sandbox
make vendor
make build
make push
# 或一站式（含 mirror）:
make offline-prep
```

然后：

```bash
make apply
```
