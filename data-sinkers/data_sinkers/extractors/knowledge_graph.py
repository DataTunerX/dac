from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
import json
import logging
import time
import os
from ..llm_output_json import parse_llm_output_string

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("knowledge_graph")

manager = ModelManager()

llm = manager.get_llm(
    provider=os.getenv("PROVIDER","openai_compatible"),
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model=os.getenv("Model"),
    temperature=0.01,
    extra_body={
        "enable_thinking": False
    },
)

class Knowledge_Graph:
    def __init__(self):
        self.llm = llm

    def format_llm_output(self, answer) -> dict:
        logger.info(f"code -> format_llm_output, answer: {answer}")
        return parse_llm_output_string(
            answer.content,
            use_single_key_fallback=True,
        )

    def knowledge_graph(self, data, max_retries: int = 3, retry_delay: float = 1.0, exponential_backoff: bool = True):
        """
        将文本内容转换为知识图谱数据，支持重试机制
        
        Args:
            data: 要转换的文本内容
            max_retries: 最大重试次数（默认: 3）
            retry_delay: 重试延迟时间（秒，默认: 1.0）
            exponential_backoff: 是否使用指数退避（默认: True）
            
        Returns:
            dict: 包含 nodes 和 relationships 的知识图谱数据
            
        Raises:
            RuntimeError: 如果所有重试尝试都失败
        """
        prompt = """
        请将提供的文本内容转换为可直接导入图数据库的结构化知识图谱数据。

        ## 输出要求
        请生成以下两种格式的数据：

        ### 格式一：标准JSON（通用程序处理）
        ```json
        {
          "nodes": [
            {
              "id": "实体唯一标识符",
              "name": "实体唯一名称",
              "labels": ["实体类型标签"],
              "properties": {
                "属性名1": "属性值1",
                "属性名2": "属性值2"
              }
            }
          ],
          "relationships": [
            {
              "type": "关系类型名称",
              "start": "起始节点ID",
              "end": "目标节点ID",
              "properties": {
                "关系属性名": "关系属性值"
              }
            }
          ]
        }
        ```

        ## 数据处理规则
        1. **实体提取**：识别名词短语作为节点，生成唯一ID（格式：类型_序号，如Employee_001）
        2. **关系提取**：识别动词/连接词作为关系，关系类型使用英文大写（如MANAGES、BELONGS_TO）
        3. **属性提取**：识别描述性内容作为属性，属性名使用小写驼峰式
        4. **去重处理**：相同实体只创建一个节点
        5. **外键转换**：数据库外键关系转换为图关系，不存储为节点属性

        ## 特别要求
        - 优先识别业务核心实体（部门、员工、项目等）
        - 明确区分实体类型（类）和实体实例（个体）


        **【注意：请严格遵循JSON格式输出，不要包含任何额外的解释或文本。】**

        """

        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content=f"content is : {data}")
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempting knowledge graph extraction (attempt {attempt + 1}/{max_retries})")
                
                # Call LLM
                response = self.llm.invoke([system_message, human_message])
                
                # Format output
                llm_result = self.format_llm_output(response)
                
                if llm_result is not None:
                    logger.info(f"Knowledge graph extraction successful on attempt {attempt + 1}")
                    return llm_result
                else:
                    logger.warning(f"LLM returned None result on attempt {attempt + 1}")
                    # Treat None result as a failure and retry
                    last_exception = ValueError("LLM returned None result")
                    
            except Exception as e:
                last_exception = e
                logger.warning(f"Knowledge graph extraction failed on attempt {attempt + 1}/{max_retries}: {e}")
                
                # Don't retry on the last attempt
                if attempt < max_retries - 1:
                    # Calculate delay
                    if exponential_backoff:
                        delay = retry_delay * (2 ** attempt)
                    else:
                        delay = retry_delay
                    
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed. Last error: {e}")
        
        # All retries failed
        logger.error(f"Failed to extract knowledge graph after {max_retries} attempts")
        if last_exception:
            raise RuntimeError(f"Failed to extract knowledge graph after {max_retries} attempts: {last_exception}") from last_exception
        else:
            raise RuntimeError(f"Failed to extract knowledge graph after {max_retries} attempts")
