"""
主程序：带联网搜索和法条验证能力的本地大模型对话
实现 Function Calling 工具调用循环
"""

import json
import sys
from typing import List, Dict, Optional, Callable
from llm_client import LLMClient, Message
from search_tools import WebSearchTool
from law_search import LawSearchTool


class WebSearchAgent:
    """
    带联网搜索和法条验证能力的智能体
    自动处理工具调用循环
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        search_tool: WebSearchTool,
        law_tool: Optional[LawSearchTool] = None,
        system_prompt: Optional[str] = None,
        max_tool_calls: int = 5,
        verbose: bool = True
    ):
        """
        初始化智能体
        
        Args:
            llm_client: 大模型客户端
            search_tool: 网页搜索工具
            law_tool: 法条搜索工具（可选）
            system_prompt: 系统提示词
            max_tool_calls: 最大工具调用次数（防止无限循环）
            verbose: 是否打印详细信息
        """
        self.llm = llm_client
        self.search_tool = search_tool
        self.law_tool = law_tool
        self.max_tool_calls = max_tool_calls
        self.verbose = verbose
        
        # 默认系统提示词
        self.system_prompt = system_prompt or self._default_system_prompt()
        
        # 工具定义
        self.tools = [search_tool.get_tool_definition()]
        if law_tool:
            self.tools.append(law_tool.get_tool_definition())
        
        # 工具执行函数映射
        self.tool_functions: Dict[str, Callable] = {
            "web_search": self._execute_web_search,
            "law_search": self._execute_law_search
        }
        
        # 对话历史
        self.messages: List[Message] = []
    
    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        return """你是一个智能助手，具有联网搜索和法条查询能力。

当用户询问以下类型的问题时，你应该使用 web_search 工具进行搜索：
1. 实时信息：新闻、天气、股价、汇率等
2. 最新动态：软件版本、技术更新、赛事结果等
3. 事实查询：需要最新数据或不确定的信息
4. 具体事件：近期发生的事件或新闻

当用户询问以下类型的问题时，你应该使用 law_search 工具进行法条搜索：
1. 法律条款：如"民法典第几条说什么"、"刑法关于盗窃罪的规定"
2. 法律解释：如"劳动合同法关于违约金的规定"
3. 法律责任：如"交通事故责任如何划分"
4. 权利义务：如"消费者有哪些权利"
5. 法律程序：如"如何申请劳动仲裁"

使用 law_search 时，搜索关键词应包含法律名称和条款号或核心概念。
法条搜索结果会自动到国家法律法规库（flk.npc.gov.cn）进行验证。

搜索后，请基于搜索结果给出准确、有帮助的回答。
如果搜索结果不足以回答问题，可以再次搜索或说明情况。
回答时请引用搜索结果中的关键信息，并标注法条是否已验证。"""
    
    def _execute_web_search(self, query: str, num_results: int = 5) -> str:
        """执行网页搜索"""
        if self.verbose:
            print(f"\n🔍 正在搜索: {query}")
        
        result = self.search_tool.search(query, num_results)
        
        if self.verbose:
            print(f"✅ 搜索完成\n")
        
        return result
    
    def _execute_law_search(self, query: str, num_results: int = 3, verify: bool = True) -> str:
        """执行法条搜索"""
        if not self.law_tool:
            return "错误：法条搜索工具未启用"
        
        if self.verbose:
            print(f"\n⚖️ 正在搜索法条: {query}")
            if verify:
                print(f"🔍 将到国家法律法规库验证...")
        
        _, result = self.law_tool.search_law(query, num_results, verify)
        
        if self.verbose:
            print(f"✅ 法条搜索完成\n")
        
        return result
    
    def _process_tool_calls(self, tool_calls: List[Dict]) -> List[Message]:
        """处理工具调用"""
        tool_messages = []
        
        for tool_call in tool_calls:
            # 提取工具信息
            if "function" in tool_call:
                # OpenAI 格式
                func_name = tool_call["function"]["name"]
                func_args = json.loads(tool_call["function"]["arguments"])
                tool_call_id = tool_call.get("id")
            else:
                # Ollama 格式
                func_name = tool_call["function"]["name"]
                func_args = tool_call["function"].get("arguments", {})
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)
                tool_call_id = tool_call.get("id")
            
            # 执行工具
            if func_name in self.tool_functions:
                result = self.tool_functions[func_name](**func_args)
                
                # 创建工具响应消息
                tool_messages.append(Message(
                    role="tool",
                    content=result,
                    tool_call_id=tool_call_id
                ))
            else:
                tool_messages.append(Message(
                    role="tool",
                    content=f"错误：未知工具 {func_name}",
                    tool_call_id=tool_call_id
                ))
        
        return tool_messages
    
    def chat(self, user_input: str) -> str:
        """
        处理用户输入并返回响应
        自动处理工具调用循环
        """
        # 添加用户消息
        if not self.messages:
            self.messages.append(Message(role="system", content=self.system_prompt))
        
        self.messages.append(Message(role="user", content=user_input))
        
        # 工具调用循环
        tool_call_count = 0
        
        while tool_call_count < self.max_tool_calls:
            # 调用模型
            response = self.llm.chat(self.messages, tools=self.tools)
            
            # 检查是否有工具调用
            if response.tool_calls:
                # 添加助手消息（包含工具调用）
                self.messages.append(response)
                
                # 处理工具调用
                tool_messages = self._process_tool_calls(response.tool_calls)
                self.messages.extend(tool_messages)
                
                tool_call_count += 1
                
                # 如果助手消息有内容，先显示
                if response.content and self.verbose:
                    print(f"\n💭 {response.content}")
            else:
                # 没有工具调用，返回最终响应
                self.messages.append(response)
                return response.content
        
        # 达到最大工具调用次数
        return "抱歉，工具调用次数已达上限，请简化您的问题或稍后再试。"
    
    def chat_stream(self, user_input: str) -> str:
        """
        流式处理用户输入
        注意：流式模式下工具调用处理较复杂，建议使用 chat()
        """
        if not self.messages:
            self.messages.append(Message(role="system", content=self.system_prompt))
        
        self.messages.append(Message(role="user", content=user_input))
        
        # 先检查是否需要工具调用
        response = self.llm.chat(self.messages, tools=self.tools)
        
        if response.tool_calls:
            # 有工具调用，走非流式处理
            self.messages.append(response)
            tool_messages = self._process_tool_calls(response.tool_calls)
            self.messages.extend(tool_messages)
            
            # 再次获取响应（流式）
            full_response = ""
            print("\n🤖 ", end="", flush=True)
            for chunk in self.llm.chat_stream(self.messages):
                print(chunk, end="", flush=True)
                full_response += chunk
            print()
            
            self.messages.append(Message(role="assistant", content=full_response))
            return full_response
        else:
            # 无工具调用，直接流式输出
            full_response = ""
            print("\n🤖 ", end="", flush=True)
            for chunk in self.llm.chat_stream(self.messages):
                print(chunk, end="", flush=True)
                full_response += chunk
            print()
            
            self.messages.append(Message(role="assistant", content=full_response))
            return full_response
    
    def clear_history(self):
        """清空对话历史"""
        self.messages = []
    
    def get_history(self) -> List[Dict]:
        """获取对话历史"""
        return [m.to_dict() for m in self.messages]


def interactive_chat(agent: WebSearchAgent):
    """交互式命令行聊天"""
    print("\n" + "=" * 50)
    print("🤖 带联网搜索和法条验证的本地大模型")
    print("=" * 50)
    print("输入 'quit' 或 'exit' 退出")
    print("输入 'clear' 清空对话历史")
    print("输入 'history' 查看对话历史")
    print("=" * 50 + "\n")
    
    while True:
        try:
            user_input = input("👤 你: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['quit', 'exit']:
                print("\n👋 再见！")
                break
            
            if user_input.lower() == 'clear':
                agent.clear_history()
                print("✅ 对话历史已清空\n")
                continue
            
            if user_input.lower() == 'history':
                history = agent.get_history()
                print("\n📜 对话历史:")
                for msg in history:
                    role = msg['role']
                    content = msg.get('content', '')[:100]
                    print(f"  [{role}]: {content}...")
                print()
                continue
            
            # 处理用户输入
            print("\n🤖 思考中...", end="", flush=True)
            response = agent.chat(user_input)
            print(f"\n🤖 助手: {response}\n")
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}\n")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="带联网搜索和法条验证的本地大模型")
    parser.add_argument(
        "--backend",
        type=str,
        default="ollama",
        choices=["ollama", "vllm", "openai_compatible"],
        help="大模型后端类型"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3",
        help="模型名称"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="API 地址"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API Key"
    )
    parser.add_argument(
        "--search-engine",
        type=str,
        default="duckduckgo",
        choices=["duckduckgo", "bing", "google"],
        help="搜索引擎"
    )
    parser.add_argument(
        "--search-api-key",
        type=str,
        default=None,
        help="搜索引擎 API Key"
    )
    parser.add_argument(
        "--enable-law",
        action="store_true",
        default=True,
        help="启用法条搜索功能（默认启用）"
    )
    parser.add_argument(
        "--disable-law",
        action="store_true",
        help="禁用法条搜索功能"
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="单次查询（不进入交互模式）"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="安静模式（减少输出）"
    )
    
    args = parser.parse_args()
    
    # 创建大模型客户端
    llm_client = LLMClient(
        backend=args.backend,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key
    )
    
    # 创建搜索工具
    search_tool = WebSearchTool(
        engine=args.search_engine,
        api_key=args.search_api_key
    )
    
    # 创建法条搜索工具
    law_tool = None
    if args.enable_law and not args.disable_law:
        law_tool = LawSearchTool(web_search_tool=search_tool)
    
    # 创建智能体
    agent = WebSearchAgent(
        llm_client=llm_client,
        search_tool=search_tool,
        law_tool=law_tool,
        verbose=not args.quiet
    )
    
    # 单次查询或交互模式
    if args.query:
        response = agent.chat(args.query)
        print(response)
    else:
        interactive_chat(agent)


if __name__ == "__main__":
    main()
