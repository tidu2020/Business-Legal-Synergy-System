# 本地大模型联网搜索工具

让本地部署的大模型（Ollama、vLLM 等）具备联网搜索和法条验证能力，通过 Function Calling 实现智能工具调用。

## 功能特点

- ✅ **多后端支持**：Ollama、vLLM、OpenAI 兼容 API
- ✅ **多搜索引擎**：DuckDuckGo（免费）、Bing、Google
- ✅ **法条搜索**：自动到国家法律法规库验证法条
- ✅ **工具调用**：模型自动决定何时搜索
- ✅ **流式输出**：支持流式响应
- ✅ **交互模式**：命令行交互对话

## 快速开始

### 1. 安装依赖

```bash
pip install requests
```

### 2. 启动本地模型

**Ollama:**
```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 启动模型（需要支持工具调用的模型）
ollama pull llama3
ollama serve
```

**vLLM:**
```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server --model <model_path> --port 8000
```

### 3. 运行程序

```bash
# 交互模式
python main.py

# 指定模型
python main.py --model qwen2

# 单次查询
python main.py --query "今天北京天气怎么样？"

# 法条查询示例
python main.py --query "民法典第1条规定了什么？"

# 使用 vLLM 后端
python main.py --backend vllm --model <model_name> --base-url http://localhost:8000

# 禁用法条搜索
python main.py --disable-law
```

## 使用示例

### 普通搜索
```
👤 你: Python 3.12 有什么新特性？

🔍 正在搜索: Python 3.12 新特性
✅ 搜索完成

🤖 助手: 根据搜索结果，Python 3.12 的主要新特性包括：
1. **改进的错误消息**：更清晰、更精确的报错信息
2. **PEP 695**：类型参数语法糖
...
```

### 法条搜索（带验证）
```
👤 你: 民法典第1条是什么内容？

⚖️ 正在搜索法条: 民法典 第1条
🔍 将到国家法律法规库验证...
✅ 法条搜索完成

🤖 助手: 根据搜索结果，**《中华人民共和国民法典》第1条** ✅ 已验证

**内容**：
为了保护民事主体的合法权益，调整民事关系，维护社会和经济秩序，适应中国特色社会主义发展要求，弘扬社会主义核心价值观，根据宪法，制定本法。

**验证来源**：国家法律法规数据库（flk.npc.gov.cn）
```

## 配置说明

### 大模型后端

| 后端 | 说明 | 默认地址 |
|------|------|----------|
| `ollama` | Ollama 本地部署 | http://localhost:11434 |
| `vllm` | vLLM 推理引擎 | http://localhost:8000 |
| `openai_compatible` | 任何 OpenAI 兼容 API | 需要指定 |

### 搜索引擎

| 引擎 | 说明 | 是否需要 API Key |
|------|------|------------------|
| `duckduckgo` | DuckDuckGo 搜索 | ❌ 免费 |
| `bing` | Bing 搜索 | ✅ 需要 |
| `google` | Google 搜索 | ✅ 需要 |

### 命令行参数

```bash
python main.py [OPTIONS]

选项:
  --backend         大模型后端 (ollama/vllm/openai_compatible)
  --model           模型名称
  --base-url        API 地址
  --api-key         API Key
  --search-engine   搜索引擎 (duckduckgo/bing/google)
  --search-api-key  搜索引擎 API Key
  --enable-law      启用法条搜索（默认启用）
  --disable-law     禁用法条搜索
  --query           单次查询
  --quiet           安静模式
```

## 法条搜索功能

### 功能说明

法条搜索工具 (`law_search`) **直接对接国家法律法规数据库（flk.npc.gov.cn）的真实 API**，无需额外 API Key：

1. **搜索法律**：通过官方 API 搜索法律法规（`POST /law-search/search/list`）
2. **获取详情**：获取法律详情和完整目录树（`GET /law-search/search/flfgDetails`）
3. **时效性标注**：自动标注 ✅ 有效 / ❌ 已废止 / ⚠️ 已修改 / 🕐 尚未生效
4. **官方来源**：所有结果均来自国家法律法规数据库，提供官方链接

### 已验证的 API 接口

| 接口 | 方法 | 说明 | 状态 |
|------|------|------|------|
| `/law-search/search/list` | POST | 搜索法律法规列表 | ✅ 可用 |
| `/law-search/search/flfgDetails` | GET | 获取法律详情+目录树 | ✅ 可用 |
| `/law-search/prompts/search` | GET | 搜索建议（输入提示） | ✅ 可用 |
| `/law-search/search/enumData` | GET | 获取分类枚举数据 | ✅ 可用 |
| `/law-search/index/aggregateData` | GET | 获取统计数据 | ✅ 可用 |

### 适用场景

模型会自动在以下场景使用法条搜索：

- 法律条款查询："民法典第几条说什么"
- 法律概念解释："什么是无因管理"
- 法律责任认定："交通事故责任如何划分"
- 权利义务咨询："消费者有哪些权利"
- 法律程序问题："如何申请劳动仲裁"

### 返回字段说明

| 字段 | 说明 |
|------|------|
| `sxx=3` ✅ 有效 | 现行有效的法律法规 |
| `sxx=1` ❌ 已废止 | 已经废止的法律法规 |
| `sxx=2` ⚠️ 已修改 | 经过修改的法律法规 |
| `sxx=4` 🕐 尚未生效 | 尚未生效的法律法规 |

## 代码集成

### 基础用法

```python
from llm_client import LLMClient
from search_tools import WebSearchTool
from law_search import LawSearchTool
from main import WebSearchAgent

# 创建大模型客户端
llm = LLMClient(
    backend="ollama",
    model="llama3",
    base_url="http://localhost:11434"
)

# 创建搜索工具
search = WebSearchTool(engine="duckduckgo")
law = LawSearchTool(web_search_tool=search)

# 创建智能体
agent = WebSearchAgent(llm, search, law)

# 对话
response = agent.chat("劳动合同法关于试用期怎么规定？")
print(response)
```

### 单独使用法条搜索

```python
from law_search import LawSearchTool, validate_law

# 创建工具
law_tool = LawSearchTool()

# 搜索法条
articles, output = law_tool.search_law("民法典 第1条", num_results=3, verify=True)
print(output)

# 验证法条引用
result = validate_law("中华人民共和国民法典", "第1条")
print(result)
```

## 推荐模型

为获得最佳工具调用效果，建议使用支持 Function Calling 的模型：

**Ollama:**
- `llama3` / `llama3.1` - 推荐
- `qwen2` / `qwen2.5` - 推荐
- `mistral` / `mixtral`
- `gemma2`

**vLLM:**
- 任何支持工具调用的模型

## 注意事项

1. **模型能力**：需要使用支持 Function Calling 的模型
2. **网络访问**：确保程序能访问搜索引擎 API 和国家法律法规库
3. **API 限制**：免费搜索 API 可能有调用频率限制
4. **隐私安全**：搜索查询会发送到搜索引擎服务器
5. **法条验证**：国家法律法规库的验证结果仅供参考，重要法律事务请咨询专业律师

## 项目结构

```
local_llm_web_search/
├── search_tools.py    # 网页搜索工具
├── llm_client.py      # 大模型客户端
├── law_search.py      # 法条搜索和验证
├── main.py            # 主程序
├── config.toml        # 配置文件
├── requirements.txt   # 依赖
└── README.md          # 使用说明
```

## 扩展开发

### 添加新的搜索引擎

```python
from search_tools import SearchEngine, SearchResult

class MySearchEngine(SearchEngine):
    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        # 实现搜索逻辑
        results = []
        # ...
        return results
```

### 添加新的工具

```python
# 定义工具
tools = [{
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "工具描述",
        "parameters": {
            "type": "object",
            "properties": {
                "param": {"type": "string"}
            }
        }
    }
}]

# 添加执行函数
agent.tool_functions["my_tool"] = my_function
```

## 许可证

MIT License
