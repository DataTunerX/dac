
# 初始化 工程

go env -w GOPROXY=https://mirrors.aliyun.com/goproxy/,direct

operator-sdk init --domain dac.io --repo github.com/DataTunerX/dac/execution-engine


# 初始化 资源对象和控制器

operator-sdk create api --group dac --version v1alpha1 --kind DataDescriptor --resource --controller

operator-sdk create api --group dac --version v1alpha1 --kind DataAgentContainer --resource --controller

# 本地测试：

macos 系统：

export GOOS=darwin
export GOARCH=arm64
make run



# build

## amd64:

修改 makefile,增加 --platform linux/amd64

.PHONY: docker-build 
docker-build: ## Build docker image with the manager.
	$(CONTAINER_TOOL) build --platform linux/amd64 -t ${IMG} .



make docker-build docker-push IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.0.4-amd64" BUILDPLATFORM=linux/amd64

make deploy IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.0.4-amd64"




## arm64:

修改 makefile,增加 --platform linux/amd64

.PHONY: docker-build 
docker-build: ## Build docker image with the manager.
	$(CONTAINER_TOOL) build --platform linux/amd64 -t ${IMG} .

make docker-build docker-push IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.0.4-amd64" BUILDPLATFORM=linux/arm64

# deploy

## 配置kubeconfig

将kubeconfig文件拿到之后，放到当前用户的.kube文件夹下，命名成config

~/.kube/config

## 下发 controller 到 k8s的execution-engine-system namespace下


make deploy IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.0.4-amd64"




make deploy IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.0.4-arm64"



# 发布

在当前dir下生成dist文件夹，在文件夹下生成一个完整的install的yaml，直接在需要安装的集群，apply这个yaml就完成安装。



make build-installer IMG="registry.cn-shanghai.aliyuncs.com/jamesxiong/execution-engine:v0.0.4-amd64"





# 配置

发送http请求的配置参数

export API_BASE_URL="http://api.example.com:8080"

export API_HTTP_TIMEOUT="30s"      # 30秒
export API_HTTP_TIMEOUT="2m"       # 2分钟
export API_HTTP_TIMEOUT="1h30m"    # 1小时30分钟


export API_MAX_RETRIES="5"


export API_RETRY_DELAY="1s"        # 1秒
export API_RETRY_DELAY="500ms"     # 500毫秒




# 维护


kubectl delete pod execution-engine-controller-manager-6ff889ccc9-mlbgg  -n execution-engine-system --grace-period=0 --force



