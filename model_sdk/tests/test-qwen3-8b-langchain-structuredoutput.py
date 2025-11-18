from pydantic import BaseModel, Field, field_validator, conint
from typing import List, Optional
from datetime import date
from langchain_openai import ChatOpenAI
import json

# 1. 定义复杂的结构化模型
class Address(BaseModel):
    street: str = Field(..., description="街道地址")
    city: str = Field(..., description="城市")
    postal_code: str = Field(..., description="邮编", min_length=6, max_length=6)
    
    @field_validator("postal_code")
    @classmethod
    def validate_postal_code(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("邮编必须是6位数字")
        return v

class Education(BaseModel):
    degree: str = Field(..., description="学位")
    university: str = Field(..., description="大学名称")
    graduation_year: conint(ge=1900, le=date.today().year) = Field(..., description="毕业年份")

class Person(BaseModel):
    name: str = Field(..., description="姓名", min_length=2, max_length=20)
    age: conint(ge=0, le=150) = Field(..., description="年龄")
    email: Optional[str] = Field(None, description="电子邮箱")
    is_employed: bool = Field(..., description="是否在职")
    address: Address = Field(..., description="居住地址")
    education: List[Education] = Field(..., description="教育经历", min_items=1)
    skills: List[str] = Field(..., description="技能列表", min_items=1)
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v and "@" not in v:
            raise ValueError("无效的邮箱格式")
        return v

# 2. 初始化LLM
llm = ChatOpenAI(
    base_url="http://10.xxx.xxx.xxx:xxx/v1",
    model="qwen3-8b",
    api_key="EMPTY",
    temperature=0.1
)

# 3. 绑定结构化输出
structured_llm = llm.with_structured_output(Person)

# 4. 生成复杂结构数据
result = structured_llm.invoke("""
生成一个完整的人物档案：
- 姓名：张伟
- 年龄：32岁
- 在职状态：是
- 居住地址：北京市海淀区中关村南大街5号，邮编100190
- 教育经历：
  - 北京大学计算机科学硕士，2020年毕业
  - 清华大学计算机科学学士，2017年毕业
- 技能：Python,机器学习,数据分析
- 邮箱：zhangwei@example.com
""")

# 5. 输出和验证
print("结构化输出：")
print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))

# 6. 访问嵌套字段
print("\n访问嵌套字段：")
print(f"姓名: {result.name}")
print(f"城市: {result.address.city}")
print(f"最高学历: {result.education[0].degree}")



# 输出：
# {
#   "name": "张伟",
#   "age": 32,
#   "email": "zhangwei@example.com",
#   "is_employed": true,
#   "address": {
#     "street": "中关村南大街5号",
#     "city": "北京市",
#     "postal_code": "100190"
#   },
#   "education": [
#     {
#       "degree": "硕士",
#       "university": "北京大学",
#       "graduation_year": 2020
#     },
#     {
#       "degree": "学士",
#       "university": "清华大学",
#       "graduation_year": 2017
#     }
#   ],
#   "skills": [
#     "Python",
#     "机器学习",
#     "数据分析"
#   ]
# }

# 访问嵌套字段：
# 姓名: 张伟
# 城市: 北京市
# 最高学历: 硕士