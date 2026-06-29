"""AI 审核编排器：ReviewOrchestrator。

编排 KeywordMatcher（粗筛）+ SimilarityRetriever（精排）双算法，
拼装四段式回复 + 免责声明，作为业务咨询的 AI 引擎入口。

支持 RAG + LLM 模式：双算法检索 Top-K 后，将检索结果作为上下文
调用大模型生成自然语言回复；LLM 不可用时回退到规则拼装。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Dict, Optional

from backend.ai.analyzer import KeywordMatcher, SimilarityRetriever
from backend.ai.llm_client import LlmClient, LlmError
from backend.config import config
from backend.knowledge.models import KnowledgeBase

logger = logging.getLogger(__name__)

# 匹配 LLM 可能生成的【参考案例N】或【参考N】标记
_REF_MARKER_RE = re.compile(r"【参考案例\d+】|【参考\d+】")

# 反馈数据文件路径
_FEEDBACK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "feedback.json")

# 反馈对排序的影响力系数
_FEEDBACK_BOOST = 0.15


class ReviewOrchestrator:
    """AI 审核编排器。

    封装双算法的编排流程：
    1. KeywordMatcher 粗筛 Top-20 候选
    2. SimilarityRetriever 精排 Top-5
    3. 拼装四段式回复 + 免责声明

    通过依赖注入 KnowledgeBase，可在知识库更新后调用 refresh() 重建索引。
    """

    DISCLAIMER = (
        "\n\n⚠️ 本意见由 AI 基于知识库生成，仅供参考。"
        "未提交法务处理，不得作为正式决策依据。"
        "如需正式法律意见，请提交法务处理。"
    )

    # 每段内容在回复中的截断长度（避免单条过长）
    FIELD_TRUNCATE = {
        "legal_answer": 300,
        "compliance_risk": 200,
        "practical_advice": 250,
        "legal_basis": 200,
    }

    # 相关度阈值：决定走哪一级回复策略
    # high：知识库 + LLM 优化（标注原文）
    # mid：参考知识库 + LLM（提示参考）
    # low：纯 LLM 回答（提示未用知识库）
    RELEVANCE_HIGH = 0.45   # >= 0.45 视为高相关度
    RELEVANCE_LOW = 0.15    # < 0.15 视为低相关度
    # 引用来源展示阈值：始终展示所有检索到的来源，让用户自行判断
    SOURCE_MIN_SCORE = 0.0

    # 无大模型时的最低相似度阈值（运行时从 config 读取，此处为类默认值）

    def __init__(self, knowledge_base: KnowledgeBase,
                 llm_client: Optional[LlmClient] = None):
        self.kb = knowledge_base
        self.matcher = KeywordMatcher()
        self.retriever = SimilarityRetriever()
        self.llm = llm_client
        self._llm_forced_off = False
        self.feedback: Dict[str, Dict[str, int]] = {}
        self._load_feedback()
        self.refresh()

    @property
    def llm_enabled(self) -> bool:
        """大模型是否启用（配置完整 + 未被管理员手动关闭）。"""
        return bool(self.llm and self.llm.available and not self._llm_forced_off)

    def set_llm_forced_off(self, off: bool) -> None:
        """管理员手动关闭/开启大模型。"""
        self._llm_forced_off = off

    def refresh(self) -> None:
        """知识库变更后重建检索索引。"""
        self.retriever.fit(self.kb.items)

    # ---------- 公开接口 ----------

    def review(self, user_input: str,
               top_k: int = 5,
               with_disclaimer: bool = True,
               extra_context: str = "") -> Dict:
        """审核业务咨询，返回结构化结果。

        支持三级相关度兜底策略：
        - 高相关度（score >= RELEVANCE_HIGH）：知识库 + LLM 优化，标注原文
        - 中相关度（RELEVANCE_LOW <= score < RELEVANCE_HIGH）：参考知识库 + LLM
        - 低相关度（score < RELEVANCE_LOW）：纯 LLM 回答，提示未用知识库

        Args:
            user_input: 用户的查询文本
            top_k: 返回前 K 条参考
            with_disclaimer: 是否附带免责声明
            extra_context: 额外上下文（如上传材料文本），参与 LLM 生成

        Returns:
            {
                "query": str,
                "candidates_count": int,
                "results": List[Dict],      # 精排 Top-K（含相似度分、来源标记）
                "answer": str,
                "disclaimer": str,
                "mode": str,               # "rag+llm" / "rag" / "llm-only" / "llm-fallback"
                "relevance": str,          # "high" / "mid" / "low" / "none"
                "sources": List[Dict],     # 引用的知识库条目（供前端点开查看）
            }
        """
        # 1. 粗筛
        candidates = self.matcher.filter(user_input, self.kb.items, top_n=20)

        llm_available = self.llm_enabled

        if not candidates:
            # 无候选
            if llm_available:
                answer, mode = self._generate_llm_only(user_input, extra_context)
                relevance = "none"
            else:
                answer = "知识库暂无类似知识，请直接提交法务处理。"
                mode = "rag"
                relevance = "none"
            if with_disclaimer:
                answer += self.DISCLAIMER
            return {
                "query": user_input,
                "candidates_count": 0,
                "results": [],
                "answer": answer,
                "disclaimer": self.DISCLAIMER if with_disclaimer else "",
                "mode": mode,
                "relevance": relevance,
                "sources": [],
            }

        # 2. 精排（含相似度分）
        ranked_with_score = self._rank_with_score(user_input, candidates,
                                                   top_k=top_k)
        items = [r["item"] for r in ranked_with_score]

        # 3. 判定相关度等级
        top_score = ranked_with_score[0]["score"] if ranked_with_score else 0.0

        # 无大模型时：相似度低于阈值不推荐，直接反馈让用户提交法务
        if not llm_available and top_score < config.KB_SIMILARITY_THRESHOLD:
            answer = "知识库暂无类似知识，请直接提交法务处理。"
            if with_disclaimer:
                answer += self.DISCLAIMER
            return {
                "query": user_input,
                "candidates_count": len(candidates),
                "results": [],
                "answer": answer,
                "disclaimer": self.DISCLAIMER if with_disclaimer else "",
                "mode": "rag",
                "relevance": "none",
                "sources": [],
            }

        if top_score >= self.RELEVANCE_HIGH:
            relevance = "high"
        elif top_score >= self.RELEVANCE_LOW:
            relevance = "mid"
        else:
            relevance = "low"

        # 4. 按相关度生成回复
        answer, mode = self._generate(user_input, items, relevance, extra_context)

        if with_disclaimer:
            answer += self.DISCLAIMER

        # 构造引用来源（供前端点开查看），始终展示所有来源
        sources = [
            {
                "id": r["item"]["id"],
                "question": r["item"]["question"],
                "legal_answer": r["item"].get("legal_answer", ""),
                "compliance_risk": r["item"].get("compliance_risk", ""),
                "practical_advice": r["item"].get("practical_advice", ""),
                "legal_basis": r["item"].get("legal_basis", ""),
                "score": r["score"],
                "cited": relevance in ("high", "mid"),
            }
            for r in ranked_with_score
        ]

        return {
            "query": user_input,
            "candidates_count": len(candidates),
            "results": [
                {
                    "id": r["item"]["id"],
                    "question": r["item"]["question"],
                    "score": r["score"],
                    "item": r["item"],
                }
                for r in ranked_with_score
            ],
            "answer": answer,
            "disclaimer": self.DISCLAIMER if with_disclaimer else "",
            "mode": mode,
            "relevance": relevance,
            "sources": sources,
        }

    def review_text(self, user_input: str, top_k: int = 5) -> str:
        """简化版：仅返回回复文本。"""
        return self.review(user_input, top_k=top_k)["answer"]

    # ---------- 内部方法 ----------

    @staticmethod
    def _clean_references(text: str) -> str:
        """移除 LLM 可能生成的【参考案例N】/【参考N】标记。"""
        return _REF_MARKER_RE.sub("", text).strip()

    def _generate(self, query: str, items: List[Dict],
                  relevance: str = "high",
                  extra_context: str = "") -> tuple:
        """按相关度等级生成回复，返回 (answer, mode)。

        - high：知识库 + LLM 优化（标注原文）
        - mid：参考知识库 + LLM（提示参考）
        - low：纯 LLM 回答（提示未用知识库）
        """
        # 规则拼装作为兜底（始终先算好，保证可用）
        fallback = self._compose(items)

        # 低相关度：纯 LLM 回答
        if relevance == "low":
            return self._generate_llm_only(query, extra_context, fallback)

        if not self.llm_enabled:
            # LLM 不可用，回退规则拼装
            return fallback, "rag"

        try:
            answer = self._generate_with_llm(query, items, relevance, extra_context)
            if answer and answer.strip():
                return answer.strip(), "rag+llm"
            logger.warning("LLM 返回空内容，回退规则拼装")
            return fallback, "rag"
        except LlmError as e:
            logger.warning("LLM 调用失败，回退规则拼装：%s", e)
            return fallback, "rag"

    def _generate_llm_only(self, query: str, extra_context: str = "",
                          fallback: str = "") -> tuple:
        """纯 LLM 回答（不依赖知识库）。

        若 LLM 不可用，回退 fallback 或默认提示。
        """
        if not self.llm_enabled:
            return fallback or "未检索到相关知识，且大模型未配置。", "rag"

        system_prompt = (
            "你是国有企业法务合规助手。当前问题在知识库中未找到高相关度案例，"
            "请你基于通用法律知识作答，并明确提示本答复未引用知识库案例，"
            "建议后续提交法务获取正式意见。\n"
            "回答要求：\n"
            "1. 结构清晰，分四段：法律解答、合规风险、实操建议、相关法条；\n"
            "2. 引用具体法条时，必须提供法条原文（格式：根据《XX法》第X条：\u201c法条原文内容\u201d）；\n"
            "3. 若无法确定法条原文的准确措辞，请注明\u201c以下为概括性表述，以官方原文为准\u201d；\n"
            "4. 语言专业但通俗易懂；\n"
            "5. 不要在正文中用【参考案例N】标注任何案例；\n"
            "6. 开头标注【本答复未引用知识库案例】。"
        )
        user_prompt = f"业务咨询：{query}"
        if extra_context:
            user_prompt += f"\n\n附加上下文（用户上传材料）：\n{extra_context[:2000]}"

        try:
            answer = self.llm.chat(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": user_prompt}],
                temperature=self.llm.temperature,
                max_tokens=self.llm.max_tokens,
            )
            if answer and answer.strip():
                answer = self._clean_references(answer)
                return answer.strip(), "llm-only"
            return fallback or "未检索到相关知识。", "rag"
        except LlmError as e:
            logger.warning("纯 LLM 回答失败，回退：%s", e)
            return fallback or "未检索到相关知识。", "rag"

    def _generate_with_llm(self, query: str, items: List[Dict],
                            relevance: str = "high",
                            extra_context: str = "") -> str:
        """用大模型基于检索到的知识生成回复。

        高相关度：严格依据知识库，标注原文来源。
        中相关度：参考知识库 + 通用知识，提示参考。
        """
        # 拼接知识库上下文
        context_parts = []
        for i, it in enumerate(items, 1):
            context_parts.append(
                f"【案例{i}】（id={it.get('id', '')}）\n"
                f"问题：{it.get('question', '')}\n"
                f"法律解答：{it.get('legal_answer', '')}\n"
                f"合规风险：{it.get('compliance_risk', '')}\n"
                f"实操建议：{it.get('practical_advice', '')}\n"
                f"相关法条：{it.get('legal_basis', '')}"
            )
        context = "\n\n".join(context_parts)

        if relevance == "high":
            system_prompt = (
                "你是国有企业法务合规助手。请严格依据下方提供的知识库案例回答业务咨询，"
                "不得编造知识库外的法律结论。\n"
                "回答要求：\n"
                "1. 结构清晰，分四段：法律解答、合规风险、实操建议、相关法条；\n"
                "2. 引用具体法条时，必须提供法条原文（格式：根据《XX法》第X条：\u201c法条原文内容\u201d）；\n"
                "3. 若引用的法条有具体条款号，必须写出完整的法条原文，不得仅写编号；\n"
                "4. 若无法确定法条原文的准确措辞，请注明\u201c以下为概括性表述，以官方原文为准\u201d；\n"
                "5. 语言专业但通俗易懂，适合业务人员理解；\n"
                "6. 不要在正文中用【参考案例N】标注任何案例；\n"
                "7. 若知识库案例不能完全覆盖用户问题，明确指出需进一步咨询法务。"
            )
        else:  # mid
            system_prompt = (
                "你是国有企业法务合规助手。下方知识库案例与用户问题相关度中等，"
                "请参考这些案例并结合通用法律知识作答。\n"
                "回答要求：\n"
                "1. 结构清晰，分四段：法律解答、合规风险、实操建议、相关法条；\n"
                "2. 引用具体法条时，必须提供法条原文（格式：根据《XX法》第X条：\u201c法条原文内容\u201d）；\n"
                "3. 若无法确定法条原文的准确措辞，请注明\u201c以下为概括性表述，以官方原文为准\u201d；\n"
                "4. 明确区分哪些内容来自知识库、哪些来自通用知识；\n"
                "5. 不要在正文中用【参考案例N】标注任何案例；\n"
                "6. 提示用户本问题与知识库相关度中等，建议提交法务确认；\n"
                "7. 不要编造法条编号，不确定的法条请说明\u201c仅供参考\u201d。"
            )

        user_prompt = f"知识库参考案例：\n{context}\n\n业务咨询：{query}"
        if extra_context:
            user_prompt += (
                f"\n\n附加上下文（用户上传材料）：\n{extra_context[:2000]}"
            )
        user_prompt += "\n\n请基于上述信息给出四段式法务意见。"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        answer = self.llm.chat(
            messages,
            temperature=self.llm.temperature,
            max_tokens=self.llm.max_tokens,
        )
        # 清理参考标记
        if answer:
            answer = self._clean_references(answer)
        return answer

    # ---------- 用户反馈 ----------

    def _load_feedback(self) -> None:
        """从文件加载反馈数据。"""
        try:
            if os.path.exists(_FEEDBACK_FILE):
                with open(_FEEDBACK_FILE, "r", encoding="utf-8") as f:
                    self.feedback = json.load(f)
                logger.info("已加载反馈数据: %d 条", len(self.feedback))
        except Exception as e:
            logger.warning("加载反馈数据失败: %s", e)
            self.feedback = {}

    def _save_feedback(self) -> None:
        """保存反馈数据到文件。"""
        try:
            os.makedirs(os.path.dirname(_FEEDBACK_FILE), exist_ok=True)
            with open(_FEEDBACK_FILE, "w", encoding="utf-8") as f:
                json.dump(self.feedback, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存反馈数据失败: %s", e)

    def record_feedback(self, faq_id: str, relevant: bool) -> None:
        """记录用户对某条知识库引用的反馈（相关/不相关）。

        反馈数据会持久化到文件，并自动影响后续检索的排序：
        - 标记为"有关"的知识条目在后续检索中排名会提升
        - 标记为"无关"的知识条目在后续检索中排名会降低
        """
        if faq_id not in self.feedback:
            self.feedback[faq_id] = {"relevant": 0, "irrelevant": 0}
        key = "relevant" if relevant else "irrelevant"
        self.feedback[faq_id][key] += 1
        self._save_feedback()
        logger.info(
            "反馈记录 faq_id=%s relevant=%s (有关=%d 无关=%d)",
            faq_id, relevant,
            self.feedback[faq_id]["relevant"],
            self.feedback[faq_id]["irrelevant"],
        )

    def _feedback_boost(self, faq_id: str) -> float:
        """计算某条知识库条目的反馈加权系数。

        公式：1.0 + (有关次数 - 无关次数) * 0.15
        - 纯有关：每次 +0.15，排名逐渐提升
        - 纯无关：每次 -0.15，排名逐渐降低
        - 范围限制在 [0.3, 2.0]
        """
        if faq_id not in self.feedback:
            return 1.0
        fb = self.feedback[faq_id]
        net = fb["relevant"] - fb["irrelevant"]
        boost = 1.0 + net * _FEEDBACK_BOOST
        return max(0.3, min(2.0, boost))

    def feedback_stats(self) -> Dict:
        """返回反馈统计。"""
        total_relevant = sum(fb["relevant"] for fb in self.feedback.values())
        total_irrelevant = sum(fb["irrelevant"] for fb in self.feedback.values())
        return {
            "total_entries": len(self.feedback),
            "total_relevant": total_relevant,
            "total_irrelevant": total_irrelevant,
            "details": self.feedback,
        }

    def _rank_with_score(self, query: str,
                         candidates: List[Dict],
                         top_k: int = 5) -> List[Dict]:
        """精排并附带相似度分数，应用用户反馈加权。"""
        q_vec = self.retriever._vectorize(query)
        q_norm = self.retriever._norm(q_vec)

        scored = []
        for cand in candidates:
            idx = self.retriever._find_item_index(cand)
            if idx >= 0:
                doc_vec = self.retriever.doc_vectors[idx]
            else:
                doc_vec = self.retriever._vectorize(
                    self.retriever._doc_text(cand))
            score = self.retriever._cosine(q_vec, doc_vec, q_norm)
            # 应用用户反馈加权
            faq_id = cand.get("id", "")
            boost = self._feedback_boost(faq_id) if faq_id else 1.0
            final_score = score * boost
            scored.append({"score": final_score, "raw_score": score,
                          "boost": boost, "item": cand})

        scored.sort(key=lambda x: -x["score"])
        return scored[:top_k]

    def _compose(self, items: List[Dict]) -> str:
        """将 Top-K 条目拼装为四段式回复文本。"""
        if not items:
            return "未检索到相关知识。"

        parts = []
        for i, it in enumerate(items, 1):
            section = [
                f"知识库条目{i}：{it.get('question', '')}",
                f"  法律解答：{self._truncate(it.get('legal_answer', ''), 'legal_answer')}",
                f"  合规风险：{self._truncate(it.get('compliance_risk', ''), 'compliance_risk')}",
                f"  实操建议：{self._truncate(it.get('practical_advice', ''), 'practical_advice')}",
                f"  依据法条：{self._truncate(it.get('legal_basis', ''), 'legal_basis')}",
            ]
            parts.append("\n".join(section))

        return "\n\n".join(parts)

    def _truncate(self, text: str, field_name: str) -> str:
        """按字段配置截断文本，超出加省略号。"""
        if not text:
            return ""
        limit = self.FIELD_TRUNCATE.get(field_name, 200)
        text = text.replace("\n", " ").strip()
        if len(text) > limit:
            return text[:limit] + "..."
        return text
