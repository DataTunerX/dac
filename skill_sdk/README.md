# 测试

## tavily_search

TAVILY_BASE_URL='https://api.tavily.com' TAVILY_API_KEY='xxx' python -m skill_sdk.tool.tavily_search "java有哪些特性" --pretty


## tavily_extract

TAVILY_BASE_URL='https://api.tavily.com' TAVILY_API_KEY='xxx' python -m skill_sdk.tool.tavily_extract "https://juejin.cn/post/7272621935006187556" --pretty


##  pdf vision test

PDF_VISION_API_KEY， DASHSCOPE_API_KEY， OPENAI_API_KEY的生效顺序

1. 若PDF_VISION_API_KEY非空：多模态就只用这个，不再去读 DASHSCOPE_* / OPENAI_*。

2. 若PDF_VISION_API_KEY为空，再按 PDF_VISION_PROVIDER选默认环境变量：
dashscope → 用 DASHSCOPE_API_KEY
openai / openai_compatible → 用 OPENAI_API_KEY


### 触发多模态处理pdf，每页一张图片。

python3 tests/pdf_vision_test.py \
  --pdf /Users/james/daocloud/code/raytest/dac/tests-data/files/manual-1page.pdf \
  --provider dashscope \
  --model qwen-vl-ocr-latest \
  --api-key 'sk-xxx' \
  --min-text-chars '100000' \
  --prompt '请用中文描述这一页的所有的内容。'


### 不触发多模态处理pdf，使用pymupdf处理pdf

python3 tests/pdf_vision_test.py \
  --pdf /Users/james/daocloud/code/raytest/dac/tests-data/files/laws.pdf \
  --provider dashscope \
  --model qwen-vl-ocr-latest \
  --api-key 'sk-xxx' \
  --min-text-chars '200' \
  --prompt '请用中文简要描述这一页的主要内容。'


## lsp

### 全局 workspace_folder（覆盖所有 LSP server 的 workspaceFolder，适用于 Go module / Python 项目根目录）

export WORKSPACE_FOLDER=/Users/james/daocloud/code/dac/dac-apiserver


### 所有的lsp server 共享一个workspace dir

WORKSPACE_PATH="/Users/james/daocloud/code/dac/skill_sdk/tests/fixtures" && SKILL_SDK_LSP_SERVERS='{"gopls":{"command":"gopls","extensionToLanguage":{".go":"go"},"args":[],"startupTimeoutMs":30000,"workspaceFolder":"'$WORKSPACE_PATH'"},"basedpyright":{"command":"basedpyright-langserver","extensionToLanguage":{".py":"python"},"args":["--stdio"],"startupTimeoutMs":30000,"workspaceFolder":"'$WORKSPACE_PATH'"},"jdtls":{"command":"jdtls","extensionToLanguage":{".java":"java"},"args":[],"startupTimeoutMs":30000,"workspaceFolder":"'$WORKSPACE_PATH'"},"clangd":{"command":"clangd","extensionToLanguage":{".c":"c",".h":"c",".cpp":"cpp",".hpp":"cpp"},"args":[],"startupTimeoutMs":30000,"workspaceFolder":"'$WORKSPACE_PATH'"},"rust-analyzer":{"command":"rust-analyzer","extensionToLanguage":{".rs":"rust"},"args":[],"startupTimeoutMs":60000,"workspaceFolder":"'$WORKSPACE_PATH'"},"vtsls":{"command":"vtsls","extensionToLanguage":{".ts":"typescript",".tsx":"typescriptreact",".js":"javascript",".jsx":"javascriptreact"},"args":["--stdio"],"startupTimeoutMs":30000,"workspaceFolder":"'$WORKSPACE_PATH'"}}' python lsp_plugin_test.py


#### clangd 旧版本不支持 outgoingCalls

clangd --version              
Homebrew clangd version 22.1.4

支持outgoingCalls，所以安装的时候要注意验证版本

