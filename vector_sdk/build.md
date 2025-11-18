
# 构建vector sdk

##  安装包测试

python setup.py sdist bdist_wheel


## docker 构建测试

amd64:

docker buildx build --platform linux/amd64 -t vector-sdk:v0.0.1-amd64 -f Dockerfile-amd64 .

docker tag vector-sdk:v0.0.1-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/vector-sdk:v0.0.1-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/vector-sdk:v0.0.1-amd64


arm64:

docker buildx build --platform linux/arm64 -t vector-sdk:v0.0.1-arm64 -f Dockerfile-arm64 .

docker tag vector-sdk:v0.0.1-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/vector-sdk:v0.0.1-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/vector-sdk:v0.0.1-arm64




# 构建pip包

docker buildx build --platform linux/amd64 -t vector-sdk:v0.0.1-amd64-wheel -f Dockerfile-amd64-wheel . 

docker run --rm -it vector-sdk:v0.0.1-amd64-wheel bash 

python setup.py sdist bdist_wheel

docker cp a6f52eba786a:/app/dist/vector_sdk-0.1.0-py3-none-any.whl ./