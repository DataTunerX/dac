# amd64

make docker-build IMG="execution-engine:12-amd64" BUILDPLATFORM=linux/amd64


make deploy IMG="execution-engine:12-amd64"


# 删除crd

make uninstall
