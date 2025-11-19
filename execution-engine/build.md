
# amd64

make docker-build docker-push IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.2.0-amd64" BUILDPLATFORM=linux/amd64

make deploy IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.2.0-amd64"


# 删除crd

make uninstall