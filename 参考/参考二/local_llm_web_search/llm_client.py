"""
大模型调用封装模块
支持 Ollama、vLLM、OpenAI 兼容 API
"""

import json
import requests
from typing import Dict, List, Optional, Generator, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class Message:
    """消息数据结构"""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        result = {"role": self.role, "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


class LLMBackend(ABC):
    """大模型后端基类"""
    
    @abstractmethod
    def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Message:
        """发送聊天请求"""
        pass
    
    @abstractmethod
    def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """流式聊天"""
        pass


class OllamaBackend(LLMBackend):
    """
    Ollama 后端
    支持本地部署的 Ollama 模型
    """
    
    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        **kwargs
    ):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.default_params = kwargs
    
    def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Message:
        """发送聊天请求"""
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            **self.default_params,
            **kwargs
        }
        
        # Ollama 工具调用格式
        if tools:
            payload["tools"] = tools
        
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            
            msg_data = data.get("message", {})
            return Message(
                role=msg_data.get("role", "assistant"),
                content=msg_data.get("content", ""),
                tool_calls=msg_data.get("tool_calls")
            )
            
        except Exception as e:
            raise RuntimeError(f"Ollama 请求失败: {e}")
    
    def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """流式聊天"""
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **self.default_params,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
        
        try:
            response = requests.post(url, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if "message" in data:
                        content = data["message"].get("content", "")
                        if content:
                            yield content
                            
        except Exception as e:
            raise RuntimeError(f"Ollama 流式请求失败: {e}")


class VLLMBackend(LLMBackend):
    """
    vLLM 后端
    支持 OpenAI 兼容的 vLLM API
    """
    
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:8000",
        api_key: str = "EMPTY",
        **kwargs
    ):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.default_params = kwargs
    
    def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Message:
        """发送聊天请求（OpenAI 兼容格式）"""
        url = f"{self.base_url}/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            **self.default_params,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            data = response.json()
            
            choice = data["choices"][0]
            msg_data = choice["message"]
            
            return Message(
                role=msg_data.get("role", "assistant"),
                content=msg_data.get("content", ""),
                tool_calls=msg_data.get("tool_calls")
            )
            
        except Exception as e:
            raise RuntimeError(f"vLLM 请求失败: {e}")
    
    def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """流式聊天"""
        url = f"{self.base_url}/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **self.default_params,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
        
        try:
            response = requests.post(
                url, json=payload, headers=headers, stream=True, timeout=120
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line and line != b"data: [DONE]":
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                            
        except Exception as e:
            raise RuntimeError(f"vLLM 流式请求失败: {e}")


class OpenAICompatibleBackend(LLMBackend):
    """
    通用的 OpenAI 兼容后端
    适用于任何兼容 OpenAI API 的服务
    """
    
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "EMPTY",
        **kwargs
    ):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.default_params = kwargs
        
        # 自动检测 endpoint 格式
        if not self.base_url.endswith('/chat/completions'):
            if not self.base_url.endswith('/v1'):
                self.base_url += '/v1'
    
    def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Message:
        """发送聊天请求"""
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            **self.default_params,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            data = response.json()
            
            choice = data["choices"][0]
            msg_data = choice["message"]
            
            return Message(
                role=msg_data.get("role", "assistant"),
                content=msg_data.get("content", ""),
                tool_calls=msg_data.get("tool_calls")
            )
            
        except Exception as e:
            raise RuntimeError(f"API 请求失败: {e}")
    
    def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """流式聊天"""
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            **self.default_params,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
        
        try:
            response = requests.post(
                url, json=payload, headers=headers, stream=True, timeout=120
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line and line != b"data: [DONE]":
                    line = line.decode('utf-8')
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                            
        except Exception as e:
            raise RuntimeError(f"API 流式请求失败: {e}")


class LLMClient:
    """
    大模型客户端
    统一接口，支持多种后端
    """
    
    def __init__(
        self,
        backend: str = "ollama",
        model: str = "llama3",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs
    ):
        """
        初始化大模型客户端
        
        Args:
            backend: 后端类型 ("ollama", "vllm", "openai_compatible")
            model: 模型名称
            base_url: API 地址
            api_key: API Key（如需要）
            **kwargs: 其他参数
        """
        self.backend_name = backend
        self.model = model
        
        if backend == "ollama":
            self._backend = OllamaBackend(
                model=model,
                base_url=base_url or "http://localhost:11434",
                **kwargs
            )
        elif backend == "vllm":
            self._backend = VLLMBackend(
                model=model,
                base_url=base_url or "http://localhost:8000",
                api_key=api_key or "EMPTY",
                **kwargs
            )
        elif backend == "openai_compatible":
            if not base_url:
                raise ValueError("openai_compatible 后端需要提供 base_url")
            self._backend = OpenAICompatibleBackend(
                model=model,
                base_url=base_url,
                api_key=api_key or "EMPTY",
                **kwargs
            )
        else:
            raise ValueError(f"不支持的后端: {backend}")
    
    def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Message:
        """发送聊天请求"""
        return self._backend.chat(messages, tools, **kwargs)
    
    def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """流式聊天"""
        return self._backend.chat_stream(messages, tools, **kwargs)
    
    def simple_chat(self, user_input: str, system_prompt: str = "") -> str:
        """简单聊天（无工具调用）"""
        messages = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=user_input))
        
        response = self.chat(messages)
        return response.content


# 便捷函数
def create_client(
    backend: str = "ollama",
    model: str = "llama3",
    **kwargs
) -> LLMClient:
    """创建大模型客户端的便捷函数"""
    return LLMClient(backend, model, **kwargs)
