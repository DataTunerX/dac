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

