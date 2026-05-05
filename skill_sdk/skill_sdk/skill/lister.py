from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable, Sequence
from typing import Literal

from skill_sdk.api.base import Skill


class SkillLister:
    """
    在内存中保存一组已加载的 :class:`~skill_sdk.api.base.Skill`，并提供多种检索方式。

    典型用法：先用 :class:`~skill_sdk.skill.loader.SkillLoader` 从目录或 zip 加载技能列表，
    再交给本类做查询；也可在构造时传入 ``skills``，或之后调用 :meth:`set_skills` 更新列表。

    示例::

        from skill_sdk.skill import SkillLoader, SkillLister

        with SkillLoader() as loader:
            skills = loader.from_dir_load_skills("/path/to/skills")
        lister = SkillLister(skills)
        hits = lister.find_by_name("github", match="exact")
    """

    def __init__(self, skills: Sequence[Skill] | None = None) -> None:
        """
        构造列表器。

        参数:
            skills: 初始技能列表；为 ``None`` 时表示空列表，后续可用 :meth:`set_skills` 填入。

        示例::

            lister = SkillLister()  # 空
            lister = SkillLister([skill_a, skill_b])  # 已有列表
        """
        self._skills: list[Skill] = list(skills) if skills is not None else []

    def set_skills(self, skills: Iterable[Skill]) -> None:
        """
        用新的技能集合整体替换当前内存中的列表（会拷贝一份，避免外部原地修改影响内部状态）。

        参数:
            skills: 任意可迭代的 :class:`~skill_sdk.api.base.Skill`。

        示例::

            lister.set_skills(loader.from_dir_load_skills("/path/to/skills"))
        """
        self._skills = list(skills)

    @property
    def skills(self) -> list[Skill]:
        """
        当前已注册技能的浅拷贝列表（修改返回的 list 不会影响内部存储，但其中的 ``Skill`` 对象仍是同一引用）。

        返回:
            ``list[Skill]``。

        示例::

            for s in lister.skills:
                print(s.name, s.version)
        """
        return list(self._skills)

    def __len__(self) -> int:
        """返回当前注册的技能数量。示例: ``n = len(lister)``"""
        return len(self._skills)

    @staticmethod
    def _norm(s: str, *, case_insensitive: bool) -> str:
        """内部用：按选项将字符串转为小写或保持原样。"""
        return s.lower() if case_insensitive else s


    def list_skills(self) -> str:
        """
        返回所有技能的 ``name`` 与 ``description`` 的格式化多行字符串。

        每个技能占一块：``Skill {n}:``，下一行缩进 ``name:``，再一行缩进 ``description:``（描述用
        :func:`json.dumps` 生成带转义的 JSON 字符串字面量，避免正文中的引号破坏格式）。

        块与块之间空一行（两个换行）。

        示例::

            Skill 1:
                name: github
                description: "Interact with GitHub using the `gh` CLI. ..."

            Skill 2:
                name: tavily-search
                description: "Web search via Tavily API ..."
        """
        result: list[str] = []
        for idx, skill in enumerate(self._skills, start=1):
            desc_lit = json.dumps(skill.description, ensure_ascii=False)
            skill_str = (
                f"Skill {idx}:\n"
                f"    name: {skill.name}\n"
                f"    description: {desc_lit}\n"
            )
            result.append(skill_str)

        return "\n\n".join(result)

    def find_by_name(
        self,
        name: str,
        *,
        match: Literal["exact", "contains"] = "exact",
        case_insensitive: bool = True,
    ) -> list[Skill]:
        """
        按 ``Skill.name`` 检索。

        参数:
            name: 要匹配的名称或子串；首尾空白会被去掉；传空字符串时返回空列表。
            match:
                - ``exact``: 与技能名全字匹配（是否忽略大小写由 ``case_insensitive`` 决定）。
                - ``contains``: ``name`` 作为子串出现在技能名中即命中。
            case_insensitive: 为 ``True`` 时比较前会转为小写。

        返回:
            命中的 :class:`~skill_sdk.api.base.Skill` 列表（可能为空或多条）。

        示例::

            lister.find_by_name("github", match="exact")           # ['github'] 或 []
            lister.find_by_name("hub", match="contains")         # 名称含 hub 的技能
            lister.find_by_name("GitHub", match="exact", case_insensitive=True)
        """
        if not name:
            return []
        needle = self._norm(name.strip(), case_insensitive=case_insensitive)
        out: list[Skill] = []
        for s in self._skills:
            hay = self._norm(s.name, case_insensitive=case_insensitive)
            if match == "exact":
                if hay == needle:
                    out.append(s)
            else:
                if needle in hay:
                    out.append(s)
        return out

    def find_by_description_contains(
        self,
        query: str,
        *,
        case_insensitive: bool = True,
    ) -> list[Skill]:
        """
        在 ``Skill.description`` 中做**子串包含**检索（常用于“关键词是否在简介里”）。

        参数:
            query: 子串；首尾空白去掉；空字符串返回空列表。
            case_insensitive: ``True`` 时大小写不敏感。

        返回:
            描述中包含 ``query`` 的技能列表。

        示例::

            # 描述里若写有 ``gh issue`` 等即可命中
            lister.find_by_description_contains("gh issue")
            lister.find_by_description_contains("prediction")
        """
        if not query:
            return []
        needle = self._norm(query.strip(), case_insensitive=case_insensitive)
        out: list[Skill] = []
        for s in self._skills:
            hay = self._norm(s.description, case_insensitive=case_insensitive)
            if needle in hay:
                out.append(s)
        return out

    def find_by_detail_contains(
        self,
        query: str,
        *,
        case_insensitive: bool = True,
    ) -> list[Skill]:
        """
        在 ``Skill.detail``（正文/Markdown）中做子串包含检索。

        参数:
            query: 子串；空字符串返回空列表。
            case_insensitive: 是否忽略大小写。

        返回:
            正文中包含 ``query`` 的技能列表。

        示例::

            lister.find_by_detail_contains("gh pr checks")
            lister.find_by_detail_contains("python3 {baseDir}/scripts")
        """
        if not query:
            return []
        needle = self._norm(query.strip(), case_insensitive=case_insensitive)
        out: list[Skill] = []
        for s in self._skills:
            hay = self._norm(s.detail, case_insensitive=case_insensitive)
            if needle in hay:
                out.append(s)
        return out

    def search_any_field(
        self,
        query: str,
        *,
        case_insensitive: bool = True,
    ) -> list[Skill]:
        """
        在多个字段中任一处出现子串即命中：``name``、``description``、``detail``、``version``、
        以及各脚本的 ``script_name``（路径 ``script_path`` 不参与拼接，避免临时目录噪声）。

        参数:
            query: 子串；空字符串返回空列表。
            case_insensitive: 是否忽略大小写。

        返回:
            至少一个上述字段包含 ``query`` 的技能列表。

        示例::

            lister.search_any_field("cron")
            lister.search_any_field("polymarket")
        """
        if not query:
            return []
        needle = self._norm(query.strip(), case_insensitive=case_insensitive)
        out: list[Skill] = []
        for s in self._skills:
            parts = (
                s.name,
                s.description,
                s.detail,
                s.version,
                *(sc.script_name for sc in s.scripts),
            )
            joined = self._norm("\n".join(parts), case_insensitive=case_insensitive)
            if needle in joined:
                out.append(s)
        return out

    def find_by_name_regex(self, pattern: str, *, flags: int = re.IGNORECASE) -> list[Skill]:
        """
        用正则表达式匹配 ``Skill.name``（``re.search``，不要求整串从头匹配）。

        参数:
            pattern: 传给 :func:`re.compile` 的模式字符串；空字符串返回空列表。
            flags: 编译正则时的标志位，默认 ``re.IGNORECASE``。

        返回:
            ``name`` 被模式搜索到的技能列表。

        示例::

            lister.find_by_name_regex(r"^github$")
            lister.find_by_name_regex(r"poly.*", flags=re.IGNORECASE)
        """
        if not pattern:
            return []
        rx = re.compile(pattern, flags)
        return [s for s in self._skills if rx.search(s.name)]
