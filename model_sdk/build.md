
# 构建model sdk

##  安装包测试

python setup.py sdist bdist_wheel


python setup.py sdist bdist_wheel --plat-name=arm64


python setup.py sdist bdist_wheel --plat-name=amd64



## docker 构建测试

amd64:

docker buildx build --platform linux/amd64 -t model-sdk:v0.0.1-amd64 -f Dockerfile-amd64 .

docker tag model-sdk:v0.0.1-amd64 registry.cn-shanghai.aliyuncs.com/jamesxiong/model-sdk:v0.0.1-amd64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/model-sdk:v0.0.1-amd64


arm64:

docker buildx build --platform linux/arm64 -t model-sdk:v0.0.1-arm64 -f Dockerfile-arm64 .

docker tag model-sdk:v0.0.1-arm64 registry.cn-shanghai.aliyuncs.com/jamesxiong/model-sdk:v0.0.1-arm64

docker push registry.cn-shanghai.aliyuncs.com/jamesxiong/model-sdk:v0.0.1-arm64




# 构建pip包

docker buildx build --platform linux/amd64 -t model-sdk:v0.0.1-amd64-wheel -f Dockerfile-amd64-wheel . 

docker run --rm -it model-sdk:v0.0.1-amd64-wheel bash 

python setup.py sdist bdist_wheel

docker cp a6f52eba786a:/app/dist/model_sdk-0.1.0-py3-none-any.whl ./